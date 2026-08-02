#!/usr/bin/env python3
"""순수 가격위치(타점) 확장 백테스트.

full 백테스트(scripts.backtest)는 배당 1년치가 있어야 채점돼 관측이 2021년
이후로 몰린다 — 정작 타점 검증에 좋은 2018 조정·2020 코로나 급락이 빠진다.
여기서는 **배당과 무관한 '가격 위치' 점수(0~20)만** 종가에서 내서, 2017년부터
전체 가격 이력으로 타점의 예측력을 본다.

가격 위치 점수는 engine.score 의 ② 블록(200일선 기울기 8 + 고점낙폭 6 +
20일 과열 6)이다. 배당 없이도 계산되므로, 최소 입력만 담아 score() 를 그대로
호출해 그 점수를 읽는다 — 채점 로직은 프로덕션과 동일하다.

집계·판정은 scripts.bt_report 의 함수를 재사용한다(같은 잣대).
겹치는 12개월 창이라 유의성은 단정하지 않는다. 방향·단조성·동일종목 검증만 본다.

실행:
  python3 -m scripts.bt_price --dsn "$DIVDESK_DSN"
  python3 -m scripts.bt_price --csv /tmp
"""
from __future__ import annotations

import argparse
import statistics as st
from bisect import bisect_right
from datetime import date, timedelta

from engine.score import ScoreInput, score
from scripts.backtest import (HORIZONS, bench_slope, forward_return, load_csv,
                              load_db, month_ends)
from scripts.bt_report import corr, pct, quintile_table, within_ticker

OUT = "fwd_12m"


def _pdate(s) -> date:
    return date.fromisoformat(str(s)[:10])


def price_pos(ts, as_of: date):
    """가격 위치 점수(0~20). 배당 불필요, 종가에서만. 최소 260 거래일 필요."""
    i = bisect_right(ts.dates, as_of)
    if i < 260:
        return None
    price = ts.close[i - 1]
    if not price or price <= 0:
        return None
    ma_now = sum(ts.close[i - 200:i]) / 200
    j = bisect_right(ts.dates, as_of - timedelta(days=60))
    if j < 200:
        return None
    ma_past = sum(ts.close[j - 200:j]) / 200
    slope = round((ma_now - ma_past) / ma_past, 4) if ma_past > 0 else None
    high52 = max(ts.close[i - 252:i])
    low52 = min(ts.close[i - 252:i])
    drawdown = round(price / high52 - 1, 4) if high52 > 0 else None
    ch20 = (round((price - ts.close[i - 21]) / ts.close[i - 21], 4)
            if ts.close[i - 21] > 0 else None)
    if slope is None:
        return None
    r = score(ScoreInput(ticker="_", price=price, ttm_dps=0.0, ma200=ma_now,
                         high52=high52, low52=low52, ma200_slope=slope,
                         drawdown=drawdown, change_20d=ch20), today=as_of)
    return r.price_pos


def build_rows(panel, start: date, end: date, bench: str = "SPY"):
    cal = (panel.px[bench].dates if bench in panel.px
           else sorted({d for ts in panel.px.values() for d in ts.dates}))
    mes = month_ends(cal, start, end)
    rows, dropped = [], 0
    for me in mes:
        regime = ""
        slp = bench_slope(panel.px[bench], me) if bench in panel.px else None
        if slp is not None:
            regime = "up" if slp > 0 else "down"
        for t, meta in panel.meta.items():
            pp = price_pos(panel.px[t], me)
            if pp is None:
                continue
            row = {"ticker": t, "date": me.isoformat(),
                   "is_benchmark": "1" if meta.get("is_benchmark") else "0",
                   "is_cc": "1" if meta.get("is_covered_call") else "0",
                   "timing": float(pp), "regime": regime}   # 재사용 위해 key 는 'timing'
            ts = panel.px[t]
            for h, hz in HORIZONS.items():
                row[h] = forward_return(ts, me, hz)
            if row[OUT] is None:
                dropped += 1
            rows.append(row)
    return rows, mes, dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv")
    src.add_argument("--dsn")
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--end", default="")
    args = ap.parse_args()

    panel = load_csv(args.csv) if args.csv else load_db(args.dsn)
    start = _pdate(args.start)
    end = _pdate(args.end) if args.end else max(ts.dates[-1] for ts in panel.px.values())

    rows, mes, dropped = build_rows(panel, start, end)
    cand = [r for r in rows if r["is_benchmark"] == "0"]
    bench = [r for r in rows if r["is_benchmark"] == "1" and r[OUT] is not None]
    cc = [r for r in cand if r["is_cc"] == "1"]

    print(f"== 순수 가격위치 백테스트 ({OUT}, 배당게이트 없음) ==")
    print(f"월말 {len(mes)}개 ({mes[0] if mes else '-'} ~ {mes[-1] if mes else '-'})")
    print(f"관측 {len(cand)} / 종목 {len(set(r['ticker'] for r in cand))} / "
          f"미래부족 드롭 {dropped}")
    if bench:
        print(f"벤치 baseline {OUT} 평균 {pct(st.mean([r[OUT] for r in bench]))} "
              f"(n{len(bench)})")

    print("\n[가격위치 5분위 → 이후수익]")
    print(quintile_table(cand, "timing", OUT))
    print("\n[동일종목 내 가격위치 (타점상위−하위, 품질 교란 제거)]")
    print(within_ticker(cand, OUT))
    ct = corr(cand, "timing", OUT)
    print(f"\n상관 가격위치↔{OUT}: {ct:+.3f}" if ct is not None else "\n상관 표본 부족")

    for reg in ("up", "down"):
        d = [(r["timing"], r[OUT]) for r in cand
             if r["regime"] == reg and r[OUT] is not None]
        if len(d) < 25:
            print(f"\n[국면 {reg}] 표본 {len(d)} — 부족")
            continue
        d.sort(key=lambda x: x[0])
        n = len(d)
        top = [v for _, v in d[n // 2:]]
        bot = [v for _, v in d[:n // 2]]
        print(f"\n[국면 {reg}] n{n} | 상위절반 {pct(st.mean(top))} vs "
              f"하위절반 {pct(st.mean(bot))} | 차 {pct(st.mean(top) - st.mean(bot))}")

    if len(cc) >= 25:
        d = [(r["timing"], r[OUT]) for r in cc if r[OUT] is not None]
        d.sort(key=lambda x: x[0])
        n = len(d)
        top = [v for _, v in d[n // 2:]]
        bot = [v for _, v in d[:n // 2]]
        print(f"\n[커버드콜만] n{n} | 상위절반 {pct(st.mean(top))} vs "
              f"하위절반 {pct(st.mean(bot))} | 차 {pct(st.mean(top) - st.mean(bot))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
