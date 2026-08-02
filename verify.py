#!/usr/bin/env python3
"""가격위치 3요소 분해 검증.

가격위치 20점은 성격이 반대인 신호를 한 점수에 섞어 놓았다:

  200일선 기울기 8점  추세추종  — 오르는 것에 가점
  고점 낙폭     6점  역추세    — 빠진 것에 가점
  20일 과열     6점  역추세    — 최근 안 오른 것에 가점

이 둘이 서로 상쇄하면 합계는 0 근처가 된다. 실제로 합계 상관이 -0.051 이었다.
그래서 **각 요소를 따로** 이후 수익과 맞춰 어느 항목이 방향을 뒤집는지 특정한다.

원신호(기울기 %, 낙폭 %, 20일 변동 %)와 배점(0~8, 2~6, 0~6)을 함께 본다.
배점은 상하한에서 포화되므로(기울기 +3% 이상은 전부 8점) 원신호가 더 정밀하다.

**이것은 진단이지 규칙 탐색이 아니다.** 여러 변형을 돌려 가장 좋은 것을 고르면
그것이 곧 과최적화다. 여기서는 기존 3요소의 방향만 확인한다.

실행:
  python3 -m scripts.bt_decomp --dsn "$DIVDESK_DSN"
  python3 -m scripts.bt_decomp --csv /tmp
"""
from __future__ import annotations

import argparse
import statistics as st
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta

from scripts.backtest import (HORIZONS, bench_slope, forward_return, load_csv,
                              load_db, month_ends)
from scripts.bt_report import corr, pct, quintile_table

OUT = "fwd_12m"

# (키, 표시명, 성격) — score.py ② 블록의 3요소
COMPONENTS = [
    ("slope", "200일선 기울기", "추세추종"),
    ("draw", "고점 낙폭", "역추세"),
    ("ch20", "20일 변동", "역추세"),
]


def _pdate(s) -> date:
    return date.fromisoformat(str(s)[:10])


def signals(ts, as_of: date):
    """원신호와 배점을 함께 낸다. score.py ② 블록의 식을 그대로 쓴다."""
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
    if ma_past <= 0:
        return None
    slope = (ma_now - ma_past) / ma_past

    high52 = max(ts.close[i - 252:i])
    if high52 <= 0:
        return None
    draw = price / high52 - 1                      # 음수(고점 대비 낙폭)

    base20 = ts.close[i - 21]
    if base20 <= 0:
        return None
    ch20 = (price - base20) / base20

    return {
        "slope": slope, "draw": draw, "ch20": ch20,
        # 배점 (score.py 와 동일 식)
        "slope_pt": 8 * max(0.0, min(1.0, (slope + 0.03) / 0.06)),
        "draw_pt": 2 + 4 * max(0.0, min(1.0, -draw / 0.10)),
        "ch20_pt": 6 * max(0.0, min(1.0, (0.10 - ch20) / 0.15)),
    }


def build_rows(panel, start: date, end: date, bench: str = "SPY"):
    cal = (panel.px[bench].dates if bench in panel.px
           else sorted({d for ts in panel.px.values() for d in ts.dates}))
    mes = month_ends(cal, start, end)
    rows = []
    for me in mes:
        regime = ""
        slp = bench_slope(panel.px[bench], me) if bench in panel.px else None
        if slp is not None:
            regime = "up" if slp > 0 else "down"
        for t, meta in panel.meta.items():
            if meta.get("is_benchmark"):
                continue                            # 후보만
            sig = signals(panel.px[t], me)
            if sig is None:
                continue
            row = {"ticker": t, "date": me.isoformat(), "regime": regime,
                   "is_cc": bool(meta.get("is_covered_call"))}
            row.update(sig)
            ts = panel.px[t]
            for h, hz in HORIZONS.items():
                row[h] = forward_return(ts, me, hz)
            rows.append(row)
    return rows, mes


def within_ticker_key(rows, key, out):
    """종목 고정: key 상위 1/3 vs 하위 1/3 의 이후 수익 차. 품질 교란 제거."""
    by_t = defaultdict(list)
    for r in rows:
        if r[out] is not None:
            by_t[r["ticker"]].append((r[key], r[out]))
    diffs, pos, used = [], 0, 0
    for _, data in by_t.items():
        if len(data) < 12:
            continue
        data.sort(key=lambda x: x[0])
        k = len(data) // 3
        d = st.mean([v for _, v in data[-k:]]) - st.mean([v for _, v in data[:k]])
        diffs.append(d)
        pos += 1 if d > 0 else 0
        used += 1
    if not diffs:
        return None, 0, 0
    return st.mean(diffs), pos, used


def regime_split(rows, key, out, reg):
    d = [(r[key], r[out]) for r in rows
         if r["regime"] == reg and r[out] is not None]
    if len(d) < 25:
        return None, len(d)
    d.sort(key=lambda x: x[0])
    n = len(d)
    top = st.mean([v for _, v in d[n // 2:]])
    bot = st.mean([v for _, v in d[:n // 2]])
    return top - bot, n


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
    rows, mes = build_rows(panel, start, end)

    print(f"== 가격위치 3요소 분해 ({OUT}) ==")
    print(f"월말 {len(mes)}개 ({mes[0]} ~ {mes[-1]}) / 관측 {len(rows)} / "
          f"종목 {len(set(r['ticker'] for r in rows))}")
    print("해석: 값이 양(+)이면 '그 항목 점수가 높을수록 이후 수익이 좋았다'.\n"
          "      음(-)이면 그 항목이 점수를 거꾸로 주고 있다는 뜻.")

    print("\n[요소별 종합 — 원신호 기준]")
    print(f"{'요소':<16}{'성격':<8}{'상관':>8}{'동일종목차':>12}{'양(+)종목':>10}")
    for key, name, kind in COMPONENTS:
        c = corr(rows, key, OUT)
        wt, pos, used = within_ticker_key(rows, key, OUT)
        cs = f"{c:+.3f}" if c is not None else "  n/a"
        ws = pct(wt) if wt is not None else "  n/a"
        print(f"{name:<16}{kind:<8}{cs:>8}{ws:>12}{f'{pos}/{used}':>10}")

    print("\n[요소별 종합 — 배점 기준 (포화 있음)]")
    for key, name, _ in COMPONENTS:
        pk = key + "_pt"
        c = corr(rows, pk, OUT)
        wt, pos, used = within_ticker_key(rows, pk, OUT)
        cs = f"{c:+.3f}" if c is not None else "n/a"
        ws = pct(wt) if wt is not None else "n/a"
        print(f"  {name:<14} 상관 {cs} | 동일종목차 {ws} | 양 {pos}/{used}")

    print("\n[국면별 (원신호, 상위절반−하위절반)]")
    print(f"{'요소':<16}{'상승장':>12}{'하락장':>12}")
    for key, name, _ in COMPONENTS:
        up, nu = regime_split(rows, key, OUT, "up")
        dn, nd = regime_split(rows, key, OUT, "down")
        us = pct(up) if up is not None else f"n{nu}부족"
        ds = pct(dn) if dn is not None else f"n{nd}부족"
        print(f"{name:<16}{us:>12}{ds:>12}")

    print("\n[요소별 5분위 — 단조성 확인]")
    for key, name, _ in COMPONENTS:
        print(f"\n  · {name} (원신호)")
        print(quintile_table(rows, key, OUT))

    # 커버드콜은 구조가 달라 따로 본다
    cc = [r for r in rows if r["is_cc"]]
    if len(cc) >= 50:
        print("\n[커버드콜만 — 원신호 상관]")
        for key, name, _ in COMPONENTS:
            c = corr(cc, key, OUT)
            print(f"  {name:<14} {c:+.3f}" if c is not None else f"  {name:<14} n/a")

    print("\n주의: 12개월 창이 겹쳐 유효 독립표본은 표시된 n 보다 훨씬 적다. "
          "방향과 단조성만 읽을 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
