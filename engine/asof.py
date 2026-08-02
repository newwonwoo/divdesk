"""과거 임의 시점(as-of) 기준 스코어 입력 조립 — 백테스트·프로덕션 공용.

왜 필요한가: `api.main.recompute()` 는 "지금" 을 전제로 DB에서 값을 뽑아
ScoreInput 을 만든다(ORDER BY date DESC LIMIT ...). 백테스트는 같은 조립을
**과거 시점 D 기준으로** 재현해야 한다. 두 벌로 만들면 "프로덕션과 다른
채점기를 검증" 하는 셈이 되므로, 조립을 여기 한 곳으로 모으고 recompute() 도
이 함수를 쓰게 한다.

핵심 원칙(= look-ahead 차단):
 - 지표는 저장값(ma200 컬럼)을 읽지 않고 **종가 시계열에서 D까지의 창으로
   다시 계산**한다. 저장 ma200 은 서버에 마지막 날짜치만 있어 과거 재구성이
   불가능하고, 애초에 매일 backfill 되지 않았다. 종가에서 후향 창으로 내면
   D 시점에 알 수 있던 값과 정확히 같다.
 - 모든 배당·환율·수익 창은 D 로 끝난다. 수정종가(adj_close)는 최신 시점으로
   재보정되지만, D 로 끝나는 창 안의 **비율**만 쓰면 사후 배당보정이 양 끝을
   같은 배수로 스케일해 상쇄되므로 안전하다. 절대 레벨은 쓰지 않는다.

store.py / recompute() 의 창 정의를 그대로 미러링한다:
 - ma200  = 최근 200 거래일 종가 단순평균 (store.py: daily[i-199:i+1] 평균)
 - 52주   = 최근 252 거래일 종가 max/min
 - slope  = ma200(D) 대비 ma200(D-60일) 변화율
 - 20일   = 최근 21행 중 첫 행 대비 변화율
 - 위험   = 최근 3년 수정종가
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta

from .dividend import compute as compute_dividend
from .dividend import describe as describe_dividend
from .exdrop import ExDropSample, ExDropStat, compute_sample, summarize
from .exdrop import RECOVERY_LIMIT
from .risk import compute as compute_risk
from .risk import describe as describe_risk
from .score import ScoreInput, ScoreResult, score


@dataclass
class TickerSeries:
    """한 종목의 일별 시계열. 날짜 오름차순 정렬된 병렬 배열."""
    dates: list          # list[date]
    close: list          # list[float]
    adj: list            # list[float | None]
    open: list           # list[float | None]
    low: list            # list[float | None]


@dataclass
class Panel:
    """모든 종목의 원본 시계열 + 환율 + 메타. 백테스트·프로덕션 공용 입력.

    provider 가 이 Panel 을 채워 넘기면, build_input/score_asof 는 DB 든 CSV 든
    출처를 모른 채 과거 임의 시점을 채점한다.
    """
    px: dict = field(default_factory=dict)       # ticker -> TickerSeries
    divs: dict = field(default_factory=dict)     # ticker -> list[(ex_date, dps)] asc
    fx_dates: list = field(default_factory=list)  # list[date] asc
    fx_vals: list = field(default_factory=list)   # list[float] asc
    meta: dict = field(default_factory=dict)     # ticker -> dict


def bench_ticker(ticker: str, meta: dict) -> str:
    """이 종목의 시장 기준(기초자산 국적). api.main.market_ticker 와 동일 규칙.

    자기 자신을 기준으로 보정하면 배당 효과까지 상쇄되므로 벤치마크는 자기 자신.
    """
    if ticker in ("SPY", "VOO", "QQQ", "069500"):
        return ticker
    idx = (meta.get("index") or "").upper()
    if meta.get("market") == "US":
        return "SPY"
    if any(k in idx for k in ("DOW JONES", "S&P", "NASDAQ", "U.S.", "US ")):
        return "SPY"
    return "069500"


def _mean(values: list) -> float | None:
    return sum(values) / len(values) if values else None


def _ma_at(ts: TickerSeries, upto_idx: int, window: int = 200) -> float | None:
    """upto_idx(=D 이하 종가 개수) 기준 최근 window 종가 단순평균."""
    if upto_idx < window:
        return None
    return _mean(ts.close[upto_idx - window:upto_idx])


def _risk_prices(ts: TickerSeries, as_of: date, i: int, years: int = 3) -> list:
    """최근 years 년 수정종가(None 제외). i = D 이하 행 개수."""
    cut = as_of - timedelta(days=365 * years)
    start = bisect_right(ts.dates, cut)
    return [a for a in ts.adj[start:i] if a is not None]


def _exdrop_at(panel: Panel, ticker: str, ts: TickerSeries, i: int,
               as_of: date, limit: int = 16) -> ExDropStat:
    """배당락 지표. open 이 없으면 drop_ratio 가 안 나와 자동으로 중립 처리된다.

    시장 보정은 기초자산 벤치마크의 D 이하 종가 변동으로 한다.
    """
    meta = panel.meta.get(ticker, {})
    bench = bench_ticker(ticker, meta)
    moves: dict = {}
    if bench != ticker and bench in panel.px:
        bts = panel.px[bench]
        bj = bisect_right(bts.dates, as_of)
        prev = None
        for k in range(bj):
            c = bts.close[k]
            if prev:
                moves[bts.dates[k]] = (c - prev) / prev
            prev = c

    index = {ts.dates[k]: k for k in range(i)}
    divs = [(exd, dps) for (exd, dps) in panel.divs.get(ticker, []) if exd <= as_of]
    samples = []
    for exd, dps in list(reversed(divs))[:limit]:
        pos = index.get(exd)
        if not pos:                       # 배당락 당일 시세 없음(또는 pos==0)
            continue
        before = ts.close[pos - 1]
        sample = ExDropSample(
            ex_date=exd, dps=float(dps), before_close=float(before),
            open_px=ts.open[pos], close_px=ts.close[pos], low_px=ts.low[pos],
            market_change=moves.get(exd))
        fwd = [(ts.dates[k], ts.close[k]) for k in range(pos, min(pos + RECOVERY_LIMIT, i))]
        samples.append(compute_sample(sample, fwd))
    return summarize(samples)


def build_input(panel: Panel, ticker: str, as_of: date) -> ScoreInput | None:
    """D(as_of) 시점에 알 수 있던 데이터만으로 ScoreInput 을 만든다.

    데이터가 부족하면(가격 없음 / 배당 1년 미만) None 을 돌려 그 시점은 건너뛴다.
    recompute() 의 스킵 조건(px 없음 or len(dv) < pays)과 같다.
    """
    ts = panel.px.get(ticker)
    if ts is None:
        return None
    meta = panel.meta.get(ticker, {})
    pays = int(meta.get("pays_per_year") or 4)

    i = bisect_right(ts.dates, as_of)       # D 이하 종가 행 개수
    if i == 0:
        return None
    price = ts.close[i - 1]
    if not price or price <= 0:
        return None

    # ── 배당 (≤ D, 최신순) ──────────────────────────
    div_upto = [(exd, dps) for (exd, dps) in panel.divs.get(ticker, []) if exd <= as_of]
    amounts = [float(dps) for _, dps in reversed(div_upto)][:pays * 8]
    if len(amounts) < pays:
        return None                         # 1년치 미만이면 채점 불가(recompute 와 동일)
    ttm = sum(amounts[:pays])
    prev = sum(amounts[pays:pays * 2]) if len(amounts) >= pays * 2 else None
    yield_hist = [sum(amounts[j:j + pays]) / price * 100
                  for j in range(0, max(0, len(amounts) - pays))]
    dividend = compute_dividend(amounts, pays)
    dps_label, dps_sub = describe_dividend(dividend)

    # ── 가격 지표 (종가에서 재계산) ─────────────────
    ma_now = _ma_at(ts, i, 200)
    past_cut = as_of - timedelta(days=60)
    j = bisect_right(ts.dates, past_cut)
    ma_past = _ma_at(ts, j, 200)
    ma200_slope = None
    if ma_now and ma_past and ma_past > 0:
        ma200_slope = round((ma_now - ma_past) / ma_past, 4)

    high52 = max(ts.close[i - 252:i]) if i >= 252 else None
    low52 = min(ts.close[i - 252:i]) if i >= 252 else None
    drawdown = round(price / high52 - 1, 4) if high52 and high52 > 0 else None

    change_20d = None
    if i >= 21 and ts.close[i - 21] > 0:
        change_20d = round((price - ts.close[i - 21]) / ts.close[i - 21], 4)

    # ── 1년 총수익 (수정종가 비율, 없으면 근사) ─────
    total_ret = None
    year_cut = as_of - timedelta(days=365)
    k = bisect_right(ts.dates, year_cut)
    now_adj = next((a for a in reversed(ts.adj[:i]) if a is not None), None)
    if k > 0:
        base_adj = ts.adj[k - 1]
        base_close = ts.close[k - 1]
        if base_adj and now_adj and float(base_adj) > 0:
            total_ret = round((float(now_adj) / float(base_adj) - 1) * 100, 2)
        elif base_close and base_close > 0:
            total_ret = round((price - base_close + ttm) / base_close * 100, 2)

    # ── 위험조정 수익 (최근 3년 수정종가) ──────────
    bench = bench_ticker(ticker, meta)
    bench_cagr = None
    if bench != ticker and bench in panel.px:
        bstat = compute_risk(_risk_prices(panel.px[bench], as_of,
                                          bisect_right(panel.px[bench].dates, as_of)))
        bench_cagr = bstat.cagr if bstat.available else None
    risk = compute_risk(_risk_prices(ts, as_of, i), bench_cagr)
    if risk.available:
        risk_label, risk_sub = describe_risk(risk, ttm / price * 100 if price else None)
    else:
        risk_label = (f"{total_ret:+.1f}%" if total_ret is not None else "데이터 없음")
        risk_sub = (f"1년 총수익 (위험 지표 없음: {risk.reason})"
                    if total_ret is not None else risk.reason)

    # ── 환율 (≤ D) ─────────────────────────────────
    f = bisect_right(panel.fx_dates, as_of)
    fx_now = panel.fx_vals[f - 1] if f > 0 else None
    fx_hist = panel.fx_vals[max(0, f - 780):f]

    # ── 배당락 ─────────────────────────────────────
    drop = _exdrop_at(panel, ticker, ts, i, as_of)

    return ScoreInput(
        ticker=ticker, price=price, ttm_dps=ttm, yield_history=yield_hist,
        ma200=ma_now, high52=high52, low52=low52,
        dps_ttm_prev=prev, total_return_1y_pct=total_ret,
        fx_history=fx_hist, fx_now=fx_now,
        dps_score=dividend.score if dividend.available else None,
        dps_label=dps_label, dps_sub=dps_sub,
        risk_score=risk.score if risk.available else None,
        risk_label=risk_label, risk_sub=risk_sub,
        fx_exposed=(bench != "069500"),
        fx_hedged=bool(meta.get("fx_hedged")),
        ma200_slope=ma200_slope, drawdown=drawdown,
        days_to_ex=None,
        exdrop_ratio=drop.drop_ratio, exdrop_samples=drop.samples,
        exdrop_recovery=drop.open_recovery, exdrop_unrecovered=drop.unrecovered,
        exdrop_gap=drop.intraday_gap, change_20d=change_20d,
        is_covered_call=bool(meta.get("is_covered_call")),
        is_krw_listed=meta.get("market") == "KR",
    )


def score_asof(panel: Panel, ticker: str, as_of: date) -> ScoreResult | None:
    """D 시점 채점 결과. 데이터 부족이면 None."""
    inp = build_input(panel, ticker, as_of)
    if inp is None:
        return None
    return score(inp, today=as_of)


def panel_from_rows(meta_rows, price_rows, div_rows, fx_rows) -> Panel:
    """이미 조회된 행 리스트로 Panel 을 조립한다(출처 무관: DB rows / CSV).

    프로덕션(api.main)과 백테스트가 각자 방식으로 행을 읽어와 이 함수로 넘기면
    조립 로직이 한 곳에 모인다. 채점기(build_input)와 함께 '한 코드 경로'.

    입력 형식:
      meta_rows : dict(ticker, market, is_benchmark, is_covered_call,
                       pays_per_year, index, fx_hedged)
      price_rows: (ticker, date, close, adj_close, open, low)  # open/low 는 None 가능
      div_rows  : (ticker, ex_date, dps)                       # is_estimate=false 만
      fx_rows   : (date, usdkrw)                               # 날짜 오름차순
    """
    panel = Panel()
    for m in meta_rows:
        panel.meta[m["ticker"]] = {
            "market": m.get("market"),
            "is_benchmark": m.get("is_benchmark"),
            "is_covered_call": m.get("is_covered_call"),
            "pays_per_year": m.get("pays_per_year"),
            "index": m.get("index"),
            "fx_hedged": bool(m.get("fx_hedged")),
        }

    build: dict = {}
    for t, d, close, adj, op, lo in price_rows:
        acc = build.setdefault(t, ([], [], [], [], []))
        acc[0].append(d)
        acc[1].append(float(close))
        acc[2].append(float(adj) if adj is not None else None)
        acc[3].append(float(op) if op is not None else None)
        acc[4].append(float(lo) if lo is not None else None)
    for t, (dts, cl, aj, op, lo) in build.items():
        panel.px[t] = TickerSeries(dates=dts, close=cl, adj=aj, open=op, low=lo)

    for t, exd, dps in div_rows:
        panel.divs.setdefault(t, []).append((exd, float(dps)))
    for t in panel.divs:
        panel.divs[t].sort()

    fx_sorted = sorted(fx_rows)
    panel.fx_dates = [d for d, _ in fx_sorted]
    panel.fx_vals = [float(v) for _, v in fx_sorted]
    return panel
