#!/usr/bin/env python3
"""골든크로스 검증 — 타점 3요소(환율·골든크로스·낙폭) 확정을 위한 마지막 관문.

## 왜 다시 추세를 보는가

앞선 검증에서 제거한 것은 **200일선 기울기**(지금 추세가 위냐 아래냐)다.
23/23 종목에서 음(-)이었고 어느 기간에서도 양(+)인 적이 없었다.

골든크로스는 그것과 다른 신호다. 기울기가 '추세의 방향' 이라면
골든크로스는 '추세의 전환' 이다 — 빠졌다가 **이제 돌아서는 중**인가.

  낙폭        싸다
  골든크로스   그런데 반등이 시작됐다

낙폭만 보면 떨어지는 칼날을 잡을 수 있다. 골든크로스는 그걸 막는 확인 장치다.
그래서 단독 예측력보다 **낙폭과의 조합**이 이 검증의 핵심이다.

## 재는 것

  gc_state  단기(50일) 이평이 장기(200일) 이평 위에 있는가        상태
  gc_gap    (MA50 - MA200) / MA200                              이격 정도
  gc_fresh  최근 60거래일 안에 상향 돌파가 일어났는가              전환 직후

세 형태는 파라미터 튜닝이 아니라 **구조가 다른 가설**이다(상태 / 정도 / 신선도).
이평 기간은 관행적인 50·200 을 그대로 쓴다 — 여러 조합을 훑으면 그것이 곧
과최적화다.

## 핵심 질문

낙폭이 큰 구간에서 골든크로스가 **추가 정보를 주는가.** 낙폭 상위 절반만
떼어내 골든크로스 유무로 갈랐을 때 수익 차가 나야 조합에 의미가 있다.
차이가 없으면 골든크로스는 낙폭이 이미 말한 것을 반복하는 것뿐이다.

실행:
  python3 -m scripts.bt_gc --dsn "$DIVDESK_DSN"
  python3 -m scripts.bt_gc --csv /tmp
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
FRESH_DAYS = 60                 # '최근 돌파' 로 볼 기간


def _pdate(s) -> date:
    return date.fromisoformat(str(s)[:10])


def ma_series(close: list):
    """누적합으로 MA50·MA200 시계열을 한 번에 낸다. 미성립 구간은 None."""
    cum = [0.0]
    for v in close:
        cum.append(cum[-1] + v)

    def ma(k, w):
        return (cum[k + 1] - cum[k + 1 - w]) / w if k + 1 >= w else None

    return ([ma(k, MA_SHORT) for k in range(len(close))],
            [ma(k, MA_LONG) for k in range(len(close))])


def gc_signals(short: list, long: list, k: int):
    """index k(= as_of 마지막 행) 기준 골든크로스 세 형태."""
    s, l = short[k], long[k]
    if s is None or l is None or l <= 0:
        return None
    state = 1.0 if s > l else 0.0
    gap = (s - l) / l
    # 최근 FRESH_DAYS 안에 '아래→위' 전환이 있었는가
    fresh = 0.0
    if state:
        for j in range(max(0, k - FRESH_DAYS), k):
            if short[j] is not None and long[j] is not None and short[j] <= long[j]:
                fresh = 1.0
                break
    return {"gc_state": state, "gc_gap": gap, "gc_fresh": fresh}


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
            g = gc_signals(short, long, i - 1)
            if g is None:
                continue
            row = {"ticker": t, "date": me,
                   "dd_pos": min(v["A"], v["C"]),          # D최소 = 채택 예정 낙폭
                   "usd": forward_return(ts, me, OUT_H)}
            row.update(g)
            rows.append(row)
    return rows, mes


def line(rows, key, out, label):
    sub = [r for r in rows if r.get(key) is not None]
    c = corr(sub, key, out)
    wt, pos, used = within_ticker_key(rows, key, out)
    ce = corr([r for r in sub if r["date"] < SPLIT], key, out)
    cl = corr([r for r in sub if r["date"] >= SPLIT], key, out)
    f = lambda x: f"{x:+.3f}" if x is not None else "  n/a"      # noqa: E731
    ws = pct(wt) if wt is not None else "  n/a"
    return (f"{label:<14}{f(c):>9}{ws:>11}{f'{pos}/{used}':>9}"
            f"{f(ce):>10}{f(cl):>10}")


def split_mean(rows, out, cond):
    yes = [r[out] for r in rows if cond(r)]
    no = [r[out] for r in rows if not cond(r)]
    if len(yes) < 25 or len(no) < 25:
        return None
    return st.mean(yes), st.mean(no), len(yes), len(no)


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
    print(f"월말 {len(mes)}개 ({mes[0]} ~ {mes[-1]}) / 관측 {len(usd)} / "
          f"종목 {len(set(r['ticker'] for r in usd))}")
    gc_on = sum(1 for r in usd if r["gc_state"])
    print(f"골든크로스 상태 비율 {gc_on / len(usd):.0%} / "
          f"최근 돌파 {sum(1 for r in usd if r['gc_fresh']) / len(usd):.0%}")

    print(f"\n[단독 예측력]\n{'신호':<14}{'상관':>9}{'동일종목차':>11}{'양(+)':>9}"
          f"{'~2021':>10}{'2022~':>10}")
    for key, lab in (("gc_state", "GC 상태"), ("gc_gap", "GC 이격"),
                     ("gc_fresh", "GC 최근돌파"), ("dd_pos", "낙폭(D최소)")):
        print(line(usd, key, "usd", lab))

    # ── 핵심: 낙폭과의 조합 ─────────────────────
    print("\n[핵심 — 낙폭이 큰 구간에서 골든크로스가 추가 정보를 주는가]")
    med = st.median(r["dd_pos"] for r in usd)
    cheap = [r for r in usd if r["dd_pos"] >= med]
    rich = [r for r in usd if r["dd_pos"] < med]
    for label, sub in (("낙폭 상위(싼 구간)", cheap), ("낙폭 하위(비싼 구간)", rich)):
        res = split_mean(sub, "usd", lambda r: r["gc_state"] > 0)
        if res is None:
            print(f"  {label}: 표본 부족")
            continue
        y, n, ny, nn = res
        print(f"  {label:<18} GC있음
