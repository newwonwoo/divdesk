#!/usr/bin/env python3
"""골든크로스 검증 — 타점 3요소(환율·골든크로스·낙폭) 확정을 위한 마지막 관문.

앞서 제거한 것은 200일선 기울기(추세의 '방향')다. 골든크로스는 다른 신호로,
추세의 '전환' 을 본다 — 빠졌다가 이제 돌아서는 중인가.

  낙폭        싸다
  골든크로스   그런데 반등이 시작됐다

낙폭만 보면 떨어지는 칼날을 잡을 수 있고, 골든크로스는 그걸 막는 확인 장치다.
그래서 단독 예측력보다 낙폭과의 조합이 이 검증의 핵심이다.

재는 형태 셋 (파라미터 튜닝이 아니라 구조가 다른 가설):
  gc_state  MA50 이 MA200 위에 있는가            상태
  gc_gap    (MA50 - MA200) / MA200              이격 정도
  gc_fresh  최근 60거래일 안에 상향 돌파했는가     전환 직후

이평 기간은 관행적인 50·200 을 그대로 쓴다. 여러 조합을 훑으면 과최적화다.

핵심 질문: 낙폭이 큰 구간에서 골든크로스가 추가 정보를 주는가.
차이가 없으면 낙폭이 이미 말한 것을 반복하는 것뿐이다.

실행: python3 -m scripts.bt_gc --dsn "$DIVDESK_DSN"
"""
from __future__ import annotations

import argparse
import statistics as st
from bisect import bisect_right
from datetime import date

from scripts.backtest import forward_return, load_csv, load_db, month_ends
from scripts.bt_report import corr, pct
from scripts.bt_variants import (OUT_H, SPLIT, rolling_dd, variants,
                                 within_ticker_key)

MA_SHORT, MA_LONG = 50, 200
FRESH_DAYS = 60


def _pdate(s) -> date:
    return date.fromisoformat(str(s)[:10])


def ma_series(close: list):
    """누적합으로 MA50·MA200 시계열. 미성립 구간은 None."""
    cum = [0.0]
    for v in close:
        cum.append(cum[-1] + v)

    def ma(k, w):
        return (cum[k + 1] - cum[k + 1 - w]) / w if k + 1 >= w else None

    return ([ma(k, MA_SHORT) for k in range(len(close))],
            [ma(k, MA_LONG) for k in range(len(close))])


def gc_signals(short: list, long: list, k: int):
    """index k 기준 골든크로스 세 형태. 미성립이면 None."""
    s, g = short[k], long[k]
    if s is None or g is None or g <= 0:
        return None
    state = 1.0 if s > g else 0.0
    fresh = 0.0
    if state:
        for j in range(max(0, k - FRESH_DAYS), k):
            if short[j] is not None and long[j] is not None and short[j] <= long[j]:
                fresh = 1.0
                break
    return {"gc_state": state, "gc_gap": (s - g) / g, "gc_fresh": fresh}


def build(panel, start: date, end: date, bench: str = "SPY"):
    cal = (panel.px[bench].dates if bench in panel.px
           else sorted({d for ts in panel.px.values() for d in ts.dates}))
    mes = month_ends(cal, start, end)
    dd_cache = {t: rolling_dd(ts.close) for t, ts in panel.px.items()}
    ma_cache = {t: ma_series(ts.close) for t, ts in panel.px.items()}

    rows = []
    for me in mes:
        for t, meta in panel.meta.items():
            if meta.get("is_benchmark"):
                continue
            ts = panel.px.get(t)
            if ts is None:
                continue
            i = bisect_right(ts.dates, me)
            if i == 0:
                continue
            v = variants(dd_cache[t], i)
            if v is None:
                continue
            short, long = ma_cache[t]
            sig = gc_signals(short, long, i - 1)
            if sig is None:
                continue
            row = {"ticker": t, "date": me,
                   "dd_pos": min(v["A"], v["C"]),
                   "usd": forward_return(ts, me, OUT_H)}
            row.update(sig)
            rows.append(row)
    return rows, mes


def fmt(x):
    return f"{x:+.3f}" if x is not None else "  n/a"


def line(rows, key, out, label):
    sub = [r for r in rows if r.get(key) is not None]
    c = corr(sub, key, out)
    wt, pos, used = within_ticker_key(rows, key, out)
    ce = corr([r for r in sub if r["date"] < SPLIT], key, out)
    cl = corr([r for r in sub if r["date"] >= SPLIT], key, out)
    ws = pct(wt) if wt is not None else "  n/a"
    head = f"{label:<14}{fmt(c):>9}{ws:>11}{f'{pos}/{used}':>9}"
    return head + f"{fmt(ce):>10}{fmt(cl):>10}"


HEADER = f"{'신호':<14}{'상관':>9}{'동일종목차':>11}{'양(+)':>9}{'~2021':>10}{'2022~':>10}"


def split_mean(rows, cond):
    yes = [r["usd"] for r in rows if cond(r)]
    no = [r["usd"] for r in rows if not cond(r)]
    if len(yes) < 25 or len(no) < 25:
        return None
    return st.mean(yes), st.mean(no), len(yes), len(no)


def show_split(label, rows, cond):
    res = split_mean(rows, cond)
    if res is None:
        print(f"  {label:<20} 표본 부족")
        return
    y, n, ny, nn = res
    body = f"있음 {pct(y)} (n{ny}) / 없음 {pct(n)} (n{nn})"
    print(f"  {label:<20} {body} | 차 {pct(y - n)}")


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
    rows, mes = build(panel, start, end)
    usd = [r for r in rows if r["usd"] is not None]

    print(f"== 골든크로스 검증 (MA{MA_SHORT}/{MA_LONG}, forward 12개월) ==")
    print(f"월말 {len(mes)}개 ({mes[0]} ~ {mes[-1]})")
    print(f"관측 {len(usd)} / 종목 {len(set(r['ticker'] for r in usd))}")
    on = sum(1 for r in usd if r["gc_state"]) / len(usd)
    fr = sum(1 for r in usd if r["gc_fresh"]) / len(usd)
    print(f"골든크로스 상태 {on:.0%} / 최근 돌파 {fr:.0%}")

    print("\n[단독 예측력]")
    print(HEADER)
    for key, lab in (("gc_state", "GC 상태"), ("gc_gap", "GC 이격"),
                     ("gc_fresh", "GC 최근돌파"), ("dd_pos", "낙폭(D최소)")):
        print(line(usd, key, "usd", lab))

    print("\n[핵심 — 싼 구간에서 GC 가 추가 정보를 주는가]")
    med = st.median(r["dd_pos"] for r in usd)
    cheap = [r for r in usd if r["dd_pos"] >= med]
    rich = [r for r in usd if r["dd_pos"] < med]
    show_split("낙폭상위·GC", cheap, lambda r: r["gc_state"] > 0)
    show_split("낙폭하위·GC", rich, lambda r: r["gc_state"] > 0)
    show_split("낙폭상위·최근돌파", cheap, lambda r: r["gc_fresh"] > 0)

    print("\n[역방향 — GC 상태에서 낙폭이 여전히 작동하는가]")
    for label, sub in (("GC 있음", [r for r in usd if r["gc_state"]]),
                       ("GC 없음", [r for r in usd if not r["gc_state"]])):
        c = corr(sub, "dd_pos", "usd")
        print(f"  {label:<8} n{len(sub):5d} 낙폭 상관 {fmt(c)}")

    print("\n[조합 — 낙폭 단독 vs 낙폭+GC 가점]")
    for r in usd:
        r["combo"] = r["dd_pos"] * (1.0 + 0.5 * r["gc_state"])
    print(HEADER)
    print(line(usd, "dd_pos", "usd", "낙폭 단독"))
    print(line(usd, "combo", "usd", "낙폭×GC가점"))

    print("\n주의: 12개월 창 중첩으로 유효 독립표본은 표시 n 보다 훨씬 적다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
