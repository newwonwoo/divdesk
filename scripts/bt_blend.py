#!/usr/bin/env python3
"""낙폭 혼합안(절대 × 자기이력) 검증 + 200일선 기울기 기간 분할.

## 왜 혼합인가

앞선 검증에서 A(절대 -10% 기준)와 C(자기 이력 백분위)는 성능이 사실상 같았다
(+0.319 vs +0.313). 우열을 가릴 수 없으므로 선택은 **각자의 실패 모드**로 한다.

  A 의 약점  종목마다 불공평. DIV 는 관측 최대낙폭이 -54%, 국내 신규 상장은
             -14%. 같은 -10% 가 한쪽엔 일상, 한쪽엔 역대급이다.
  C 의 약점  이력이 짧으면 왜곡. 2022~23 상장 종목은 아직 위기를 안 겪어
             평범한 -8% 조정이 곧 '역대 최악'(백분위 100%)이 된다.

혼합하면 서로를 막는다. 이력 짧은 종목이 -8% 에서 C=1.0 을 받아도 A=0.8 이
끌어내리고, DIV 가 -15% 에서 A=1.0 을 받아도 자기 이력상 평범하면 C 가 끌어내린다.
**절대적으로도 큰 낙폭이고 자기 이력으로도 드문 낙폭**일 때만 높은 점수가 된다.

두 방식으로 잰다:
  D평균  (A + C) / 2      완만한 혼합
  D최소  min(A, C)        '둘 다 만족' 을 엄격히 구현한 버전

## 이 검증이 답해야 할 것

1. **A 와 C 가 실제로 다른 신호인가.** 상관이 0.95 면 같은 것을 두 번 쓰는
   셈이라 혼합이 무의미하다. 이걸 먼저 잰다.
2. 혼합의 기간 안정성. 앞서 A·C 모두 2022년 이후 무너졌으므로 혼합도
   무너질 것으로 예상한다 — **예측력 개선을 기대하고 하는 것이 아니다.**
3. 이력이 짧은 종목에서 혼합이 실제로 C 의 왜곡을 잡아주는가.

## 함께 확인하는 것 — 기울기 기간 분할

분해 검증은 200일선 기울기의 전 기간 통합값(-0.238)만 냈다. 낙폭이 기간에 따라
무너지는 것을 확인한 이상, 기울기도 기간을 나눠 보지 않고 제거를 확정하면
같은 실수가 된다.

실행:
  python3 -m scripts.bt_blend --dsn "$DIVDESK_DSN"
  python3 -m scripts.bt_blend --csv /tmp
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from datetime import date, timedelta

from scripts.backtest import (bench_slope, forward_return, load_csv, load_db,
                              month_ends)
from scripts.bt_report import corr, pct
from scripts.bt_variants import (OUT_H, SPLIT, rolling_dd, variants,
                                 within_ticker_key)

LONG_HISTORY_YEARS = 5          # 이 이상이면 '이력 충분' 으로 본다


def _pdate(s) -> date:
    return date.fromisoformat(str(s)[:10])


def slope_at(ts, as_of: date):
    """200일선 기울기(최근 200종가 평균 대비 60일 전 200종가 평균)."""
    i = bisect_right(ts.dates, as_of)
    if i < 200:
        return None
    ma_now = sum(ts.close[i - 200:i]) / 200
    j = bisect_right(ts.dates, as_of - timedelta(days=60))
    if j < 200:
        return None
    ma_past = sum(ts.close[j - 200:j]) / 200
    return (ma_now - ma_past) / ma_past if ma_past > 0 else None


def build(panel, start: date, end: date, bench: str = "SPY"):
    cal = (panel.px[bench].dates if bench in panel.px
           else sorted({d for ts in panel.px.values() for d in ts.dates}))
    mes = month_ends(cal, start, end)
    dd_cache = {t: rolling_dd(ts.close) for t, ts in panel.px.items()}

    rows = []
    for me in mes:
        regime = ""
        slp = bench_slope(panel.px[bench], me) if bench in panel.px else None
        if slp is not None:
            regime = "up" if slp > 0 else "down"
        for t, meta in panel.meta.items():
            if meta.get("is_benchmark"):
                continue
            ts = panel.px.get(t)
            if ts is None:
                continue
            i = bisect_right(ts.dates, me)
            v = variants(dd_cache[t], i)
            if v is None:
                continue
            a, c = v["A"], v["C"]
            rows.append({
                "ticker": t, "date": me, "regime": regime,
                "A": a, "C": c,
                "Davg": (a + c) / 2,
                "Dmin": min(a, c),
                "dd": v["dd"], "worst": v["worst"],
                "slope": slope_at(ts, me),
                "hist_years": i / 252,
                "usd": forward_return(ts, me, OUT_H),
            })
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

    print("== 낙폭 혼합안 검증 (forward 12개월, 달러 기준) ==")
    print(f"월말 {len(mes)}개 ({mes[0]} ~ {mes[-1]}) / 관측 {len(usd)} / "
          f"종목 {len(set(r['ticker'] for r in usd))}")

    # ① A 와 C 가 애초에 다른 신호인가 — 혼합의 전제
    ac = corr(usd, "A", "C")
    print(f"\n[전제 확인] A↔C 상관 {ac:+.3f}" if ac is not None else "\n[전제] n/a")
    print("  0.95 이상이면 같은 신호를 두 번 쓰는 것이라 혼합에 의미가 없다.")

    print(f"\n{'방식':<14}{'상관':>9}{'동일종목차':>11}{'양(+)':>9}"
          f"{'~2021':>10}{'2022~':>10}")
    for key, lab in (("A", "A 절대"), ("C", "C 백분위"),
                     ("Davg", "D 평균"), ("Dmin", "D 최소")):
        print(line(usd, key, "usd", lab))

    # ② 이력 길이별 — 혼합이 C 의 왜곡을 잡아주는가
    longs = [r for r in usd if r["hist_years"] >= LONG_HISTORY_YEARS]
    shorts = [r for r in usd if r["hist_years"] < LONG_HISTORY_YEARS]
    print(f"\n[이력 길이별] 장기 {len(longs)}관측 / 단기 {len(shorts)}관측 "
          f"(기준 {LONG_HISTORY_YEARS}년)")
    if len(shorts) >= 50 and len(longs) >= 50:
        print(f"  {'방식':<12}{'장기종목':>10}{'단기종목':>10}")
        for key, lab in (("A", "A 절대"), ("C", "C 백분위"),
                         ("Davg", "D 평균"), ("Dmin", "D 최소")):
            cl_ = corr(longs, key, "usd")
            cs_ = corr(shorts, key, "usd")
            f = lambda x: f"{x:+.3f}" if x is not None else "  n/a"   # noqa: E731
            print(f"  {lab:<12}{f(cl_):>10}{f(cs_):>10}")
        # 단기 종목에서 C 가 얼마나 자주 만점 부근인지 — 왜곡의 크기
        hi_c = sum(1 for r in shorts if r["C"] >= 0.95)
        hi_a = sum(1 for r in shorts if r["A"] >= 0.95)
        hi_d = sum(1 for r in shorts if r["Dmin"] >= 0.95)
        print(f"  단기 종목 만점(0.95+) 비율 — C {hi_c / len(shorts):.0%} / "
              f"A {hi_a / len(shorts):.0%} / D최소 {hi_d / len(shorts):.0%}")
        print("  C 만 유독 높으면 '아직 위기를 안 겪은 종목' 을 과대평가하는 것이다.")
    else:
        print("  한쪽 표본 부족 — 비교 생략")

    # ③ 200일선 기울기 기간 분할 (제거 확정 전 확인)
    sl = [r for r in usd if r["slope"] is not None]
    print(f"\n== 200일선 기울기 기간 분할 (관측 {len(sl)}) ==")
    print("  음(-)이면 '기울기가 클수록(상승추세일수록) 이후 수익이 나빴다'.")
    print(f"\n{'방식':<14}{'상관':>9}{'동일종목차':>11}{'양(+)':>9}"
          f"{'~2021':>10}{'2022~':>10}")
    print(line(sl, "slope", "usd", "기울기"))
    for reg in ("up", "down"):
        sub = [r for r in sl if r["regime"] == reg]
        if len(sub) < 50:
            print(f"  [국면 {reg}] n{len(sub)} 부족")
            continue
        c = corr(sub, "slope", "usd")
        print(f"  [국면 {reg}] n{len(sub)} 상관 {c:+.3f}" if c is not None
              else f"  [국면 {reg}] n/a")

    print("\n주의: 12개월 창 중첩으로 유효 독립표본은 표시 n 보다 훨씬 적다. "
          "두 기간의 부호 일관성만 읽을 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
