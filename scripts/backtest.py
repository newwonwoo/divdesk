#!/usr/bin/env python3
"""배당 ETF 스코어 백테스트.

매월 말 시점에 그 시점 데이터만으로 as-of 채점 → 이후 3/6/12개월 총수익을 기록.
점수(특히 타점)가 실제 예측력이 있는지 과거로 검증한다. 채점은 engine.asof 를
쓰며, 이는 프로덕션 recompute() 와 같은 경로다 — '다른 채점기를 검증'하지 않는다.

look-ahead 차단:
 - 채점은 D 이하 데이터만 본다(engine.asof 가 보장, 유닛테스트 있음).
 - forward 수익은 D 이후 수정종가로만 낸다. D 로 끝나는 채점과 D 로 시작하는
   측정이 분리돼 있어 미래가 점수로 새지 않는다.

산출: 관측당 한 행짜리 결과 CSV(작다). 버킷 집계·그림은 이 CSV 로 로컬에서 한다.
서버에서 무겁게 돌리고 이 작은 파일만 가져오는 구조.

실행:
  python3 -m scripts.backtest --csv /tmp                 # CSV 4종에서
  python3 -m scripts.backtest --dsn "$DIVDESK_DSN"       # DB 에서
옵션: --start 2016-01-01 --out /tmp/bt_results.csv
"""
from __future__ import annotations

import argparse
import csv
import os
from bisect import bisect_right
from datetime import date, timedelta

from engine.asof import panel_from_rows, score_asof

# forward 수익 구간(거래일). 3/6/12개월 ≈ 63/126/252 거래일.
HORIZONS = {"fwd_3m": 63, "fwd_6m": 126, "fwd_12m": 252}


def _pdate(s) -> date:
    return date.fromisoformat(str(s)[:10])


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("t", "true", "1", "y", "yes")


# ---------- 데이터 적재 ----------
def load_csv(folder: str):
    """서버에서 덤프한 bt_*.csv 4종으로 Panel 구성. open/low 는 없어 None."""
    meta = []
    with open(os.path.join(folder, "bt_meta.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            meta.append({
                "ticker": r["ticker"], "market": r["market"],
                "is_benchmark": _truthy(r["is_benchmark"]),
                "is_covered_call": _truthy(r["is_covered_call"]),
                "pays_per_year": int(r["pays_per_year"]) if r["pays_per_year"] else None,
                "index": (r.get("idx") or None),
                "fx_hedged": _truthy(r.get("fx_hedged")),
            })
    price = []
    with open(os.path.join(folder, "bt_price.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            price.append((r["ticker"], _pdate(r["date"]), r["close"],
                          (r.get("adj_close") or None), None, None))
    div = []
    with open(os.path.join(folder, "bt_div.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            div.append((r["ticker"], _pdate(r["ex_date"]), r["dps"]))
    fx = []
    with open(os.path.join(folder, "bt_fx.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            fx.append((_pdate(r["date"]), r["usdkrw"]))
    return panel_from_rows(meta, price, div, fx)


def load_db(dsn: str):
    """서버 DB 에서 직접 Panel 구성. open/low 컬럼이 없으면 NULL 로 채운다."""
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT ticker,market,is_benchmark,is_covered_call,"
                    "pays_per_year,tags->>'index',tags->>'fx_hedged' FROM etf_master")
        meta = [{"ticker": t, "market": m, "is_benchmark": b, "is_covered_call": cc,
                 "pays_per_year": p, "index": idx, "fx_hedged": _truthy(fh)}
                for t, m, b, cc, p, idx, fh in cur.fetchall()]
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='etf_price_daily'")
        cols = {c for (c,) in cur.fetchall()}
        oc = "open" if "open" in cols else "NULL"
        lc = "low" if "low" in cols else "NULL"
        cur.execute(f"SELECT ticker,date,close,adj_close,{oc},{lc} "
                    "FROM etf_price_daily WHERE date>='2014-01-01' ORDER BY ticker,date")
        price = cur.fetchall()
        cur.execute("SELECT ticker,ex_date,dps FROM dividend_history "
                    "WHERE is_estimate=false ORDER BY ticker,ex_date")
        div = cur.fetchall()
        cur.execute("SELECT date,usdkrw FROM fx_rate ORDER BY date")
        fx = cur.fetchall()
    return panel_from_rows(meta, price, div, fx)


# ---------- 핵심 로직 (순수 함수 — 단위 검증 대상) ----------
def month_ends(cal_dates: list, start: date, end: date) -> list:
    """거래일 리스트에서 각 달의 마지막 거래일을 뽑는다([start, end] 범위)."""
    out, last = [], None
    for d in cal_dates:
        if last is not None and (d.year, d.month) != (last.year, last.month):
            if start <= last <= end:
                out.append(last)
        last = d
    if last is not None and start <= last <= end:
        out.append(last)
    return out


def bench_slope(ts, as_of: date):
    """벤치의 200일선 기울기(최근 200종가 평균 대비 60일 전 200종가 평균).

    국면 판정용. 배당 유무와 무관하게 종가만으로 낸다(엔진 build_input 은 배당이
    없으면 None 을 돌려주므로, 벤치가 배당이 없어도 국면은 나오게 분리한다).
    """
    i = bisect_right(ts.dates, as_of)
    if i < 200:
        return None
    ma_now = sum(ts.close[i - 200:i]) / 200
    j = bisect_right(ts.dates, as_of - timedelta(days=60))
    if j < 200:
        return None
    ma_past = sum(ts.close[j - 200:j]) / 200
    return (ma_now - ma_past) / ma_past if ma_past > 0 else None


def forward_return(ts, as_of: date, horizon: int):
    """D 이후 horizon 거래일 총수익(수정종가 비율). 미래가 모자라면 None."""
    i = bisect_right(ts.dates, as_of)
    if i == 0:
        return None
    base = ts.adj[i - 1]
    tgt = i - 1 + horizon
    if base is None or float(base) <= 0 or tgt >= len(ts.dates):
        return None
    fut = ts.adj[tgt]
    if fut is None:
        return None
    return round(float(fut) / float(base) - 1, 6)


def run(panel, start: date, end: date, bench: str = "SPY"):
    """월말×종목 관측을 만든다. (관측 리스트, 월말 리스트, 구간부족 드롭수)."""
    if bench in panel.px:
        cal = panel.px[bench].dates
    else:                                   # 벤치 없으면 전 종목 거래일 합집합
        cal = sorted({d for ts in panel.px.values() for d in ts.dates})
    mes = month_ends(cal, start, end)

    obs, dropped = [], {h: 0 for h in HORIZONS}
    for me in mes:
        # 국면: 벤치의 200일선 기울기 부호(상승/하락). 커버드콜은 국면 의존이 커서
        # 나중에 이 값으로 나눠 본다.
        regime = ""
        slope = bench_slope(panel.px[bench], me) if bench in panel.px else None
        if slope is not None:
            regime = "up" if slope > 0 else "down"

        for t, meta in panel.meta.items():
            r = score_asof(panel, t, me)
            if r is None:
                continue
            row = {
                "ticker": t, "date": me.isoformat(), "market": meta.get("market") or "",
                "is_benchmark": 1 if meta.get("is_benchmark") else 0,
                "is_cc": 1 if meta.get("is_covered_call") else 0,
                "timing": r.timing, "quality": r.quality, "total": r.total,
                "grade": r.grade, "excluded": 1 if r.excluded else 0,
                "confidence": r.confidence, "regime": regime,
            }
            ts = panel.px[t]
            for h, hz in HORIZONS.items():
                fr = forward_return(ts, me, hz)
                row[h] = "" if fr is None else fr
                if fr is None:
                    dropped[h] += 1
            obs.append(row)
    return obs, mes, dropped


def write_csv(obs: list, path: str) -> None:
    cols = ["ticker", "date", "market", "is_benchmark", "is_cc", "timing",
            "quality", "total", "grade", "excluded", "confidence", "regime",
            "fwd_3m", "fwd_6m", "fwd_12m"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(obs)


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="bt_*.csv 4종이 있는 폴더")
    src.add_argument("--dsn", help="PostgreSQL DSN")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="")
    ap.add_argument("--out", default="/tmp/bt_results.csv")
    args = ap.parse_args()

    panel = load_csv(args.csv) if args.csv else load_db(args.dsn)
    start = _pdate(args.start)
    end = (_pdate(args.end) if args.end
           else max(ts.dates[-1] for ts in panel.px.values()))

    obs, mes, dropped = run(panel, start, end)
    write_csv(obs, args.out)

    tickers = len({o["ticker"] for o in obs})
    print(f"월말 시점 {len(mes)}개 ({mes[0] if mes else '-'} ~ {mes[-1] if mes else '-'})")
    print(f"관측 {len(obs)}행, 종목 {tickers}종 → {args.out}")
    print("미래 구간 부족으로 비운 값(무단 절단 아님, 값만 공란): "
          + ", ".join(f"{h} {n}건" for h, n in dropped.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
