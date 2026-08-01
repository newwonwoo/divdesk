"""DivDesk API 서버.

실행: uvicorn api.main:app --host 127.0.0.1 --port 8000
     (nginx 뒤에 두거나 Vercel에서 프록시. 0.0.0.0 로 열지 말 것)

원칙:
 - 데이터가 없으면 없다고 답한다. 추정으로 채우지 않는다.
 - 세율은 tax_param 에서 읽는다. 이 파일에 세율 숫자는 없다.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from collector.store import Store
from engine.calc import ALLOC_EQUAL, Holding, forward, reverse
from engine.calendar import (TradingCalendar, monthly_ledger, next_ex_date,
                             predict_schedule)
from engine.score import ScoreInput, score
from engine.projection import common_start
from engine.projection import compare as compare_projections
from engine.projection import growth_quality, simulate
from engine.returns import Lot, portfolio_return, position_return
from engine.tax import MODES, TaxEngine
from alerts import push

app = FastAPI(title="DivDesk API", version="0.1.0")

origins = [o for o in os.environ.get("DIVDESK_ORIGINS", "").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["http://localhost:5173"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

_store = Store()


def db():
    try:
        conn = _store.connect()
        if conn is None:
            raise RuntimeError("DB 미연결")
        return conn
    except Exception as exc:                                  # noqa: BLE001
        raise HTTPException(503, f"DB에 연결할 수 없습니다: {type(exc).__name__}") from exc


def rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = db()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def latest_fx() -> tuple[float, str]:
    found = rows("SELECT usdkrw, date FROM fx_rate ORDER BY date DESC LIMIT 1")
    if not found:
        raise HTTPException(503, "환율 데이터가 없습니다. 수집 배치를 먼저 실행하세요.")
    return float(found[0]["usdkrw"]), str(found[0]["date"])


def load_holdings(tickers: list[str]) -> list[Holding]:
    """티커 목록으로 계산 입력을 만든다. 데이터 없는 종목은 조용히 빼지 않고 알린다."""
    if not tickers:
        raise HTTPException(400, "종목을 하나 이상 지정하세요")
    found: list[Holding] = []
    missing: list[str] = []
    for ticker in tickers:
        meta = rows("""SELECT ticker,name,pays_per_year,is_covered_call,market
                       FROM etf_master WHERE ticker=%s""", (ticker,))
        if not meta:
            missing.append(ticker)
            continue
        m = meta[0]
        px = rows("""SELECT close FROM etf_price_daily
                     WHERE ticker=%s ORDER BY date DESC LIMIT 1""", (ticker,))
        pays = int(m["pays_per_year"] or 4)
        dv = rows("""SELECT dps FROM dividend_history
                     WHERE ticker=%s AND is_estimate=false
                     ORDER BY ex_date DESC LIMIT %s""", (ticker, pays))
        if not px or not dv:
            missing.append(ticker)
            continue
        # 실제 지급월을 이력에서 뽑는다. 주기로 추정(분기=3·6·9·12월)하면
        # 계산 탭과 일지 탭의 월별 숫자가 어긋난다 — 같은 앱에서 두 화면이
        # 다른 값을 보이면 안 된다.
        observed = rows("""SELECT DISTINCT EXTRACT(MONTH FROM ex_date)::int AS m
                           FROM dividend_history
                           WHERE ticker=%s AND is_estimate=false
                             AND ex_date > CURRENT_DATE - INTERVAL '18 months'""",
                        (ticker,))
        pay_months = sorted({r["m"] for r in observed})
        if len(pay_months) not in (pays, 12):
            pay_months = []          # 이력이 어중간하면 주기 추정에 맡긴다

        found.append(Holding(
            ticker=ticker, name=m["name"] or "",
            price=float(px[0]["close"]),
            ttm_dps=float(sum(float(d["dps"]) for d in dv)),
            pays_per_year=pays,
            pay_months=pay_months,
            currency="KRW" if m["market"] == "KR" else "USD",
            is_covered_call=bool(m["is_covered_call"]),
        ))
    if missing:
        raise HTTPException(422, f"데이터가 없는 종목: {', '.join(missing)}. "
                                 "수집 배치를 먼저 실행하거나 종목을 제외하세요.")
    return found


_CAL_CACHE: dict = {}


def trading_calendar(market: str) -> TradingCalendar:
    """관측된 시세 날짜에서 거래일 달력을 만든다. 공휴일 표를 따로 두지 않는다."""
    cached = _CAL_CACHE.get(market)
    if cached:
        return cached
    days = [r["date"] for r in rows(
        """SELECT DISTINCT p.date FROM etf_price_daily p
           JOIN etf_master m USING (ticker)
           WHERE m.market=%s ORDER BY 1""", (market,))]
    cal = TradingCalendar.from_dates(market, days)
    _CAL_CACHE[market] = cal
    return cal


def dividend_rows(ticker: str) -> list[dict]:
    return rows("""SELECT ex_date, pay_date, dps FROM dividend_history
                   WHERE ticker=%s AND is_estimate=false
                   ORDER BY ex_date DESC LIMIT 60""", (ticker,))


def ytd_income() -> float:
    got = rows("""SELECT COALESCE(SUM(gross_krw),0) AS s FROM income_ledger
                  WHERE year=%s""", (date.today().year,))
    return float(got[0]["s"]) if got else 0.0


def engine() -> TaxEngine:
    return TaxEngine.from_store(_store)


# ---------- 조회 ----------
@app.get("/health")
def health():
    try:
        rows("SELECT 1 AS ok")
        return {"ok": True, "db": True}
    except HTTPException:
        return {"ok": True, "db": False}


@app.get("/etfs")
def list_etfs(market: str | None = None):
    sql = """SELECT m.ticker, m.name, m.market, m.strategy, m.pay_freq,
                    m.expense_ratio, m.is_covered_call, m.is_benchmark, m.kr_alt_ticker,
                    p.close, p.date AS price_date,
                    s.total AS score, s.reason
             FROM etf_master m
             LEFT JOIN LATERAL (SELECT close,date FROM etf_price_daily
                                WHERE ticker=m.ticker ORDER BY date DESC LIMIT 1) p ON true
             LEFT JOIN LATERAL (SELECT total,reason FROM score_snapshot
                                WHERE ticker=m.ticker ORDER BY date DESC LIMIT 1) s ON true
             WHERE m.is_benchmark = false"""
    params: tuple = ()
    if market:
        sql += " AND m.market=%s"
        params = (market.upper(),)
    return {"items": rows(sql + " ORDER BY s.total DESC NULLS LAST", params)}


@app.get("/etfs/duplicates")
def duplicate_index():
    """같은 지수를 추종하는 종목 묶음.

    동일 지수를 여러 개 담으면 분산이 아니라 중복이다. 하나만 고르면 되고,
    고르는 기준은 배당률이 아니라 총보수와 유동성이다.
    """
    groups: dict = {}
    for row in rows("""SELECT ticker, name, market, expense_ratio,
                              COALESCE((tags->>'aum_eok')::numeric,
                                       (tags->>'aum_busd')::numeric) AS aum_eok,
                              tags->>'listed' AS listed,
                              tags->>'index' AS idx
                       FROM etf_master WHERE tags->>'index' IS NOT NULL"""):
        groups.setdefault(row["idx"], []).append(row)

    out = []
    for idx, members in groups.items():
        if len(members) < 2:
            continue
        no_fee = [m["ticker"] for m in members if m["expense_ratio"] is None]
        # 보수 차이가 무의미한 수준이면 순자산으로 가른다.
        # 0.0099% vs 0.01% 는 1억원에 연 1원 차이다. 그걸로 유동성 7배를
        # 뒤집으면 매매 시 호가 손실이 훨씬 크다.
        FEE_TIE = 0.02          # %p. 이 이내는 같은 값으로 본다.
        known = [m for m in members if m["expense_ratio"] is not None]
        cheapest = min((float(m["expense_ratio"]) for m in known), default=None)

        def sort_key(m):
            if m["expense_ratio"] is None:
                return (2, 0.0, 0.0)
            fee = float(m["expense_ratio"])
            tier = 0 if (cheapest is not None and fee - cheapest <= FEE_TIE) else 1
            return (tier, fee if tier else 0.0, -float(m["aum_eok"] or 0))

        ranked = sorted(members, key=sort_key)
        tied = [m for m in known
                if cheapest is not None and float(m["expense_ratio"]) - cheapest <= FEE_TIE]
        if len(tied) > 1:
            advice = (f"같은 지수를 추종하고 총보수도 사실상 같습니다({len(tied)}종). "
                      "남는 기준은 순자산·거래량이며, 큰 쪽이 호가가 촘촘해 "
                      "매매할 때 손실이 작습니다.")
        else:
            advice = ("같은 지수를 추종합니다. 여러 개 담아도 분산 효과가 없으니 하나만 "
                      "고르세요. 기준은 배당률이 아니라 총보수와 순자산입니다.")
        out.append({
            "index": idx, "members": ranked, "advice": advice,
            "recommended": ranked[0]["ticker"],
            "fee_tie_count": len(tied),
            "missing_fee": no_fee,
        })
    return {"groups": out}


@app.get("/etfs/{ticker}")
def etf_detail(ticker: str):
    meta = rows("SELECT * FROM etf_master WHERE ticker=%s", (ticker,))
    if not meta:
        raise HTTPException(404, f"{ticker} 를 찾을 수 없습니다")
    return {
        "meta": meta[0],
        "dividends": rows("""SELECT ex_date,pay_date,dps,is_estimate,conflict,src
                             FROM dividend_history WHERE ticker=%s
                             ORDER BY ex_date DESC LIMIT 24""", (ticker,)),
        "prices": rows("""SELECT date,close FROM etf_price_daily
                          WHERE ticker=%s ORDER BY date DESC LIMIT 260""", (ticker,)),
        "score": rows("""SELECT * FROM score_snapshot WHERE ticker=%s
                         ORDER BY date DESC LIMIT 1""", (ticker,)),
    }


# ---------- 계산 ----------
class ForwardReq(BaseModel):
    amount_krw: float = Field(gt=0)
    tickers: list[str]
    account_mode: str = "US_TAXABLE"
    weights: dict[str, float] | None = None


@app.post("/calc/forward")
def calc_forward(req: ForwardReq):
    if req.account_mode not in MODES:
        raise HTTPException(400, f"계좌모드는 {MODES} 중 하나여야 합니다")
    holdings = load_holdings(req.tickers)
    fx, fx_date = latest_fx()

    raw = ([max(0.0, req.weights.get(h.ticker, 0)) for h in holdings]
           if req.weights else [1.0] * len(holdings))
    total = sum(raw)
    if total <= 0:
        raise HTTPException(400, "비중의 합이 0입니다")
    for h, w in zip(holdings, raw):
        unit = h.price * (fx if h.currency == "USD" else 1)
        h.qty = float(int(req.amount_krw * (w / total) / unit)) if unit > 0 else 0.0

    result = forward(holdings, fx, req.account_mode, engine(), ytd_income())
    return {"fx": fx, "fx_date": fx_date, "result": result}


class ReverseReq(BaseModel):
    target_monthly_krw: float = Field(gt=0)
    tickers: list[str]
    account_mode: str = "US_TAXABLE"
    alloc: str = ALLOC_EQUAL
    weights: dict[str, float] | None = None


@app.post("/calc/reverse")
def calc_reverse(req: ReverseReq):
    if req.account_mode not in MODES:
        raise HTTPException(400, f"계좌모드는 {MODES} 중 하나여야 합니다")
    fx, fx_date = latest_fx()
    try:
        result = reverse(req.target_monthly_krw, load_holdings(req.tickers), fx,
                         req.account_mode, engine(), req.alloc, req.weights, ytd_income())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"fx": fx, "fx_date": fx_date, "result": result}


# ---------- 매수기록 ----------
class PurchaseIn(BaseModel):
    ticker: str
    trade_date: date
    qty: float = Field(gt=0)
    price: float = Field(gt=0)
    fx_at_buy: float | None = None
    fee: float = 0
    account_mode: str
    memo: str | None = None


@app.get("/purchases")
def list_purchases():
    return {"items": rows("""SELECT p.*, m.name, m.market
                             FROM purchase p JOIN etf_master m USING (ticker)
                             ORDER BY trade_date DESC, id DESC""")}


@app.post("/purchases")
def add_purchase(item: PurchaseIn):
    if item.account_mode not in MODES:
        raise HTTPException(400, f"계좌모드는 {MODES} 중 하나여야 합니다")
    if item.trade_date > date.today():
        raise HTTPException(400, "매수일이 미래입니다")
    if not rows("SELECT 1 FROM etf_master WHERE ticker=%s", (item.ticker,)):
        raise HTTPException(404, f"{item.ticker} 는 등록된 종목이 아닙니다")
    conn = db()
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO purchase
                       (ticker,trade_date,qty,price,fx_at_buy,fee,account_mode,memo)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (item.ticker, item.trade_date, item.qty, item.price,
                     item.fx_at_buy, item.fee, item.account_mode, item.memo))
        new_id = cur.fetchone()[0]
    conn.commit()
    return {"id": new_id}


@app.delete("/purchases/{purchase_id}")
def delete_purchase(purchase_id: int):
    conn = db()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM purchase WHERE id=%s", (purchase_id,))
        gone = cur.rowcount
    conn.commit()
    if not gone:
        raise HTTPException(404, "해당 매수기록이 없습니다")
    return {"deleted": purchase_id}


# ---------- 포트폴리오 / 워치독 ----------
@app.get("/portfolio")
def portfolio(account_mode: str = "US_TAXABLE"):
    if account_mode not in MODES:
        raise HTTPException(400, f"계좌모드는 {MODES} 중 하나여야 합니다")
    owned = rows("""SELECT ticker, SUM(qty) AS qty FROM purchase
                    WHERE account_mode=%s GROUP BY ticker HAVING SUM(qty)>0""",
                 (account_mode,))
    if not owned:
        return {"empty": True, "message": "매수기록이 없습니다."}
    fx, fx_date = latest_fx()
    holdings = load_holdings([o["ticker"] for o in owned])
    qty_map = {o["ticker"]: float(o["qty"]) for o in owned}
    for h in holdings:
        h.qty = qty_map[h.ticker]
    return {"fx": fx, "fx_date": fx_date,
            "result": forward(holdings, fx, account_mode, engine(), ytd_income())}


@app.get("/watchdog")
def watchdog():
    tax = engine()
    threshold = tax.params["fin_income_threshold"]
    ratio_limit = tax.params["watchdog_ratio"]
    current = ytd_income()
    ratio = current / threshold if threshold else 0.0
    if ratio >= 1:
        level, msg = "over", "금융소득종합과세 기준을 넘었습니다. 초과분은 누진세율이 적용됩니다."
    elif ratio >= ratio_limit:
        level, msg = "warn", ("종합과세 기준에 근접했습니다. 절세계좌(ISA/연금) 활용을 "
                              "검토해 보세요. 절세계좌에는 국내상장 ETF만 담을 수 있습니다.")
    else:
        level, msg = "ok", "여유가 있습니다."
    return {"year": date.today().year, "gross_krw": current,
            "threshold_krw": threshold, "ratio": round(ratio, 4),
            "level": level, "message": msg}


# ---------- 스코어 ----------
@app.get("/scores")
def scores(limit: int = 20):
    return {"items": rows("""SELECT DISTINCT ON (ticker) s.*, m.name, m.is_covered_call
                             FROM score_snapshot s JOIN etf_master m USING (ticker)
                             ORDER BY ticker, date DESC LIMIT %s""", (limit,))}


@app.post("/scores/recompute")
def recompute():
    """저장된 데이터로 스코어를 다시 계산해 오늘 날짜로 적재한다."""
    fx, _ = latest_fx()
    fx_hist = [float(r["usdkrw"]) for r in
               rows("SELECT usdkrw FROM fx_rate ORDER BY date DESC LIMIT 780")]
    made, skipped = 0, []
    estimate_notes: list[str] = []
    conn = db()
    for meta in rows("SELECT * FROM etf_master"):
        ticker = meta["ticker"]
        pays = int(meta["pays_per_year"] or 4)
        px = rows("""SELECT close,ma200,high52,low52 FROM etf_price_daily
                     WHERE ticker=%s ORDER BY date DESC LIMIT 1""", (ticker,))
        dv = rows("""SELECT ex_date,dps FROM dividend_history
                     WHERE ticker=%s AND is_estimate=false
                     ORDER BY ex_date DESC LIMIT %s""", (ticker, pays * 6))
        if not px or len(dv) < pays:
            skipped.append(ticker)
            continue
        amounts = [float(d["dps"]) for d in dv]
        ttm = sum(amounts[:pays])
        prev = sum(amounts[pays:pays * 2]) if len(amounts) >= pays * 2 else None
        price = float(px[0]["close"])
        yield_hist = [sum(amounts[i:i + pays]) / price * 100
                      for i in range(0, max(0, len(amounts) - pays))]
        # 1년 총수익률. 수정종가(분배금 재투자 반영)의 비율이 정확한 총수익이다.
        # 수정종가가 없을 때만 근사식으로 물러선다.
        year_ago = rows("""SELECT close, adj_close FROM etf_price_daily
                           WHERE ticker=%s AND date <= CURRENT_DATE - INTERVAL '1 year'
                           ORDER BY date DESC LIMIT 1""", (ticker,))
        now_adj = rows("""SELECT adj_close FROM etf_price_daily
                          WHERE ticker=%s AND adj_close IS NOT NULL
                          ORDER BY date DESC LIMIT 1""", (ticker,))
        total_ret = None
        if year_ago:
            base_adj = year_ago[0]["adj_close"]
            if base_adj and now_adj and float(base_adj) > 0:
                total_ret = round(
                    (float(now_adj[0]["adj_close"]) / float(base_adj) - 1) * 100, 2)
            else:
                base = float(year_ago[0]["close"])
                if base > 0:
                    total_ret = round((price - base + ttm) / base * 100, 2)

        # 다음 배당락일은 캘린더 엔진이 낸다. 확정 공시가 있으면 그것, 없으면
        # 관측된 거래일 위에서 추정하고 estimated 로 표시한다.
        cal = trading_calendar(meta["market"])
        ex_history = [(r["ex_date"], float(r["dps"]), r.get("pay_date"))
                      for r in reversed(dividend_rows(ticker))]
        ex_day, days, confirmed = next_ex_date(ticker, meta["market"], ex_history, cal)
        if ex_day and not confirmed:
            estimate_notes.append(f"{ticker} 배당락일은 추정치")
        result = score(ScoreInput(
            ticker=ticker, price=price, ttm_dps=ttm, yield_history=yield_hist,
            ma200=px[0]["ma200"] and float(px[0]["ma200"]),
            high52=px[0]["high52"] and float(px[0]["high52"]),
            low52=px[0]["low52"] and float(px[0]["low52"]),
            dps_ttm_prev=prev, total_return_1y_pct=total_ret,
            fx_history=fx_hist, fx_now=fx,
            days_to_ex=days, is_covered_call=bool(meta["is_covered_call"]),
            is_krw_listed=meta["market"] == "KR"))
        note = result.reason + (" ⚠ " + " / ".join(result.warnings) if result.warnings else "")
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO score_snapshot
                (ticker,date,total,yield_pctile,price_pos,dps_health,total_ret,fx_pos,exdate_pen,reason)
                VALUES (%s,CURRENT_DATE,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (ticker,date) DO UPDATE SET
                  total=EXCLUDED.total, reason=EXCLUDED.reason,
                  yield_pctile=EXCLUDED.yield_pctile, price_pos=EXCLUDED.price_pos,
                  dps_health=EXCLUDED.dps_health, total_ret=EXCLUDED.total_ret,
                  fx_pos=EXCLUDED.fx_pos, exdate_pen=EXCLUDED.exdate_pen""",
                (ticker, result.total, result.yield_pctile, result.price_pos,
                 result.dps_health, result.total_ret, result.fx_pos,
                 result.exdate_pen, note))
        made += 1
    conn.commit()
    return {"computed": made, "skipped": skipped,
            "estimated_ex_dates": len(estimate_notes),
            "at": datetime.now().isoformat(timespec="seconds")}


@app.get("/portfolio/returns")
def portfolio_returns(account_mode: str = "US_TAXABLE"):
    """배당 + 시세차익 + 환차익을 합친 실제 손익."""
    if account_mode not in MODES:
        raise HTTPException(400, f"계좌모드는 {MODES} 중 하나여야 합니다")

    lots_raw = rows("""SELECT p.ticker, p.qty, p.price, p.fx_at_buy, p.fee,
                              p.trade_date, p.is_opening_balance, m.name, m.market
                       FROM purchase p JOIN etf_master m USING (ticker)
                       WHERE p.account_mode=%s ORDER BY p.ticker, p.trade_date""",
                    (account_mode,))
    if not lots_raw:
        return {"empty": True, "message": "매수기록이 없습니다."}

    fx, fx_date = latest_fx()
    grouped: dict = {}
    for row in lots_raw:
        grouped.setdefault(row["ticker"], []).append(row)

    positions, missing = [], []
    for ticker, group in grouped.items():
        px = rows("""SELECT close FROM etf_price_daily
                     WHERE ticker=%s ORDER BY date DESC LIMIT 1""", (ticker,))
        if not px:
            missing.append(ticker)
            continue
        currency = "KRW" if group[0]["market"] == "KR" else "USD"

        # 보유 시작 이후 받은 배당. 매수건별로 그 시점 이후 배당만 센다.
        dividend_krw = 0.0
        for row in group:
            paid = rows("""SELECT COALESCE(SUM(dps),0) AS s FROM dividend_history
                           WHERE ticker=%s AND is_estimate=false AND ex_date > %s""",
                        (ticker, row["trade_date"]))
            per_share = float(paid[0]["s"])
            rate = 1.0 if currency == "KRW" else fx
            dividend_krw += per_share * float(row["qty"]) * rate

        lots = [Lot(ticker=ticker, qty=float(r["qty"]), price=float(r["price"]),
                    fx_at_buy=float(r["fx_at_buy"]) if r["fx_at_buy"] else None,
                    fee=float(r["fee"] or 0), currency=currency,
                    name=r["name"] or "",
                    is_opening=bool(r["is_opening_balance"])) for r in group]
        positions.append(position_return(lots, float(px[0]["close"]), fx, dividend_krw))

    if not positions:
        raise HTTPException(422, f"시세 데이터가 없는 종목뿐입니다: {', '.join(missing)}")

    result = portfolio_return(positions, account_mode, engine(), ytd_income())
    return {"fx": fx, "fx_date": fx_date, "result": result, "no_price": missing}


def adj_series(ticker: str) -> list:
    return [(r["date"], r["adj_close"]) for r in rows(
        """SELECT date, adj_close FROM etf_price_daily
           WHERE ticker=%s AND adj_close IS NOT NULL ORDER BY date""", (ticker,))]


class ProjectionReq(BaseModel):
    monthly_krw: float = Field(gt=0)
    years: int = Field(gt=0, le=30)
    tickers: list[str]
    with_benchmark: bool = True


@app.post("/projection")
def projection(req: ProjectionReq):
    """매달 얼마씩 몇 년 넣으면 얼마가 되는지. 단일 값이 아니라 범위로 답한다."""
    targets = list(dict.fromkeys(req.tickers))
    benchmarks = []
    if req.with_benchmark:
        benchmarks = [r["ticker"] for r in rows(
            "SELECT ticker FROM etf_master WHERE is_benchmark ORDER BY ticker")]
        targets += [b for b in benchmarks if b not in targets]

    series_map, missing = {}, []
    for ticker in targets:
        series = adj_series(ticker)
        if series:
            series_map[ticker] = series
        else:
            missing.append(ticker)

    # 종목마다 상장일이 다르다. 각자의 전체 이력으로 돌리면 오래된 종목만
    # 과거 폭락장을 겪은 것으로 나와 비교가 왜곡되므로 공통 구간으로 자른다.
    # 다만 이력이 짧은 종목 하나 때문에 전체가 막히면 안 되니, 요청 기간을
    # 못 채우는 종목은 공통 구간 계산에서 빼고 따로 알린다.
    need_months = req.years * 12 + 1
    eligible, too_short = {}, []
    for ticker, series in series_map.items():
        months = len({(d.year, d.month) for d, _ in series})
        if months >= need_months:
            eligible[ticker] = series
        else:
            too_short.append(ticker)
    if not eligible:
        raise HTTPException(
            422, f"{req.years}년을 시뮬레이션할 만큼 이력이 긴 종목이 없습니다. "
                 f"기간을 줄여보세요.")

    since = common_start(eligible)
    results = []
    for ticker, series in eligible.items():
        try:
            results.append(simulate(ticker, series, req.monthly_krw,
                                    req.years, since=since))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    if not results:
        raise HTTPException(422, f"수정종가 데이터가 없습니다: {', '.join(missing)}")

    payload = compare_projections(results)
    return {
        "monthly_krw": req.monthly_krw, "years": req.years,
        "total_invested_krw": round(req.monthly_krw * req.years * 12),
        "benchmarks": benchmarks, "no_data": missing,
        "common_start": since,
        "excluded_short_history": too_short,
        "period_note": ("모든 종목을 공통 보유 구간으로 맞춰 계산했습니다. "
                        "상장일이 다른 종목을 각자의 전체 이력으로 비교하면 "
                        "오래된 종목만 과거 폭락장을 겪은 것으로 나와 왜곡됩니다."
                        + (f" 상장이 늦어 제외한 종목: {', '.join(too_short)}"
                           if too_short else "")),
        "results": [{
            "ticker": p.ticker, "is_benchmark": p.ticker in benchmarks,
            "windows": p.windows,
            "median_final_krw": p.median_final_krw,
            "median_profit_krw": p.median_profit_krw,
            "median_return_pct": p.median_return_pct,
            "median_annual_pct": p.median_annual_pct,
            "worst_final_krw": round(p.worst.final_value) if p.worst else None,
            "best_final_krw": round(p.best.final_value) if p.best else None,
            "worst_start": p.worst.start if p.worst else None,
            "loss_windows": p.loss_windows,
            "notes": p.notes,
        } for p in payload.get("items", results)],
        "spread_krw": payload.get("spread_krw"),
    }


@app.get("/etfs/{ticker}/quality")
def quality(ticker: str, years: int = 5):
    """꾸준히 올랐는지. 배당만 보고 고르면 주가가 빠지는 종목을 사게 된다."""
    meta = rows("SELECT name, is_covered_call FROM etf_master WHERE ticker=%s", (ticker,))
    if not meta:
        raise HTTPException(404, f"{ticker} 를 찾을 수 없습니다")
    stat = growth_quality(adj_series(ticker), years)
    bench = {b["ticker"]: growth_quality(adj_series(b["ticker"]), years)
             for b in rows("SELECT ticker FROM etf_master WHERE is_benchmark")}
    gap = None
    spy = bench.get("SPY")
    if stat.get("available") and spy and spy.get("available"):
        gap = round(stat["cagr_pct"] - spy["cagr_pct"], 2)
    return {"ticker": ticker, "name": meta[0]["name"], "quality": stat,
            "benchmarks": bench, "vs_spy_pp": gap,
            "note": ("연평균 총수익이 SPY보다 낮다면, 배당을 받아도 시장을 그냥 사는 것보다 "
                     "못한 결과입니다." if gap is not None and gap < 0 else None)}


# ---------- 푸시 알림 ----------
class PushSub(BaseModel):
    endpoint: str
    keys: dict
    expirationTime: object | None = None


@app.get("/push/key")
def push_key():
    """프론트가 구독을 만들 때 필요한 공개키. 없으면 알림 기능을 숨긴다."""
    return {"public_key": push.public_key(), "enabled": push.keys_present()}


@app.post("/push/subscribe")
def push_subscribe(sub: PushSub):
    if not push.keys_present():
        raise HTTPException(503, "서버에 VAPID 키가 설정되지 않아 알림을 켤 수 없습니다")
    payload = {"endpoint": sub.endpoint, "keys": sub.keys}
    conn = db()
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO push_subscription (endpoint, payload)
                       VALUES (%s,%s)
                       ON CONFLICT (endpoint) DO UPDATE
                         SET payload=EXCLUDED.payload, enabled=true
                       RETURNING id""", (sub.endpoint, json.dumps(payload)))
        new_id = cur.fetchone()[0]
    conn.commit()
    return {"id": new_id}


@app.post("/push/unsubscribe")
def push_unsubscribe(sub: PushSub):
    conn = db()
    with conn.cursor() as cur:
        cur.execute("UPDATE push_subscription SET enabled=false WHERE endpoint=%s",
                    (sub.endpoint,))
    conn.commit()
    return {"ok": True}


@app.post("/push/test")
def push_test():
    subs = rows("SELECT id, payload FROM push_subscription WHERE enabled")
    if not subs:
        raise HTTPException(404, "등록된 구독이 없습니다")
    sent = sum(1 for s in subs
               if push.send(s["payload"], "DivDesk 알림 테스트",
                            "알림이 정상적으로 도착했습니다.")[0])
    return {"subscriptions": len(subs), "delivered": sent}


@app.get("/alerts")
def alert_history(limit: int = 30):
    return {"items": rows("""SELECT ticker, kind, message, delivered, fired_at
                             FROM alert_log ORDER BY fired_at DESC LIMIT %s""", (limit,))}


# ---------- 배당예상일지 ----------
@app.get("/calendar")
def dividend_calendar(account_mode: str = "US_TAXABLE", months: int = 12):
    """앞으로 12개월 월별 입금 예정. 확정분과 추정분을 구분해서 돌려준다."""
    if account_mode not in MODES:
        raise HTTPException(400, f"계좌모드는 {MODES} 중 하나여야 합니다")
    owned = rows("""SELECT ticker, SUM(qty) AS qty FROM purchase
                    WHERE account_mode=%s GROUP BY ticker HAVING SUM(qty)>0""",
                 (account_mode,))
    if not owned:
        return {"empty": True, "message": "매수기록이 없어 일지를 만들 수 없습니다."}

    fx, fx_date = latest_fx()
    tax = engine()
    keep = 1 - tax.effective_rate(account_mode)
    qty_map = {o["ticker"]: float(o["qty"]) for o in owned}

    payouts, currency_map, missing = [], {}, []
    for ticker in qty_map:
        meta = rows("SELECT market FROM etf_master WHERE ticker=%s", (ticker,))
        if not meta:
            missing.append(ticker)
            continue
        market = meta[0]["market"]
        currency_map[ticker] = "KRW" if market == "KR" else "USD"
        hist = [(r["ex_date"], float(r["dps"]), r["pay_date"])
                for r in reversed(dividend_rows(ticker))]
        if not hist:
            missing.append(ticker)
            continue
        payouts += predict_schedule(ticker, market, hist,
                                    trading_calendar(market), months)

    ledger = monthly_ledger(payouts, qty_map, keep, fx, currency_map)
    return {
        "fx": fx, "fx_date": fx_date, "keep_rate": round(keep, 4),
        "months": ledger, "no_data": missing,
        "notes": [
            "지급일은 배당락일에서 시장별 규칙으로 계산한 값입니다. "
            "미국은 배당락 4영업일 뒤, 국내는 지급기준일 다음 달 초를 기준으로 잡습니다.",
            "휴장일은 수집된 시세에서 도출한 실제 거래일로 계산합니다.",
            "확정 표시가 없는 항목은 과거 이력으로 만든 추정치입니다.",
            "계산 탭보다 금액이 조금 높거나 낮게 나올 수 있습니다. "
            "계산 탭은 최근 배당이 그대로 유지된다고 보고, 일지는 분배금 증감 추세를 반영합니다.",
        ],
    }


@app.get("/calendar/holidays")
def holidays(market: str = "KR", year: int = 0):
    """관측된 시세에서 도출한 휴장일. 공휴일 표를 손으로 관리하지 않는다."""
    cal = trading_calendar(market.upper())
    target = year or date.today().year
    days = cal.holidays_in(target)
    return {"market": market.upper(), "year": target,
            "observed_from": cal.days[0] if cal.days else None,
            "observed_to": cal.last_observed,
            "holidays": [d.isoformat() for d in days]}
