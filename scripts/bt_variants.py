#!/usr/bin/env python3
"""낙폭 정규화 3방식 비교 + 환율 밴드 검증 (기간 분할 포함).

## 왜

분해 검증에서 '고점 낙폭' 만 방향이 맞았다(+0.310, 28/29종). 그런데 현재 배점은
낙폭 -10% 를 만점으로 **모든 종목에 같은 기준**을 쓴다. 저변동 ETF(SCHD)는
-10% 까지 빠지는 일이 드물어 사실상 이 점수를 못 받고, 고변동(QYLD·JEPQ)은
수시로 받는다. 종목 성격 차이가 점수 차이로 둔갑한다.

그래서 '자기 이력 대비' 로 정규화하는 두 방식을 현행과 나란히 잰다.
배당률 위치가 이미 쓰는 철학(자기 과거 대비 백분위)과 같은 발상이다.

  A 현행     clip(-낙폭 / 0.10)            절대 기준, 하드코딩된 -10%
  B 최대대비  낙폭 / 과거최대낙폭            자기 최악 대비 지금 위치
  C 백분위    과거 낙폭 분포에서의 위치       자기 이력 분포 대비

셋 다 **값이 클수록 많이 빠진 상태**로 맞춰 놓았다. 이후 수익과 양(+)이면
"많이 빠졌을 때 사는 게 나았다" 는 뜻이고, 그 방향이 곧 배점 방향이 된다.

## look-ahead

낙폭 이력·최대낙폭·환율 밴드 모두 **as_of 이하만** 쓴다. 2019년 시점에서
2020년 코로나 낙폭을 알 수 없다. 미래를 넣으면 어떤 지표든 잘 맞는 것처럼 보인다.
상장 초기 종목이 첫 하락에서 곧바로 '역대 최대' 를 받는 것도 막기 위해
낙폭 이력 최소 요건을 둔다(MIN_DD_HISTORY).

## 환율

환율 점수는 원화 투자자의 환전 타이밍을 재는 항목인데, 앞선 백테스트는
forward 수익을 **달러 기준**으로 재서 환율 효과가 아예 들어가지 않았다.
영향을 줄 수 없는 결과로 그 항목을 평가한 셈이라, 여기서는 **원화 환산 수익**을
따로 계산해 3년 밴드와 5년 밴드를 비교한다.

다만 환율 신호는 **같은 날 모든 종목에 동일**하다. 종목 수가 표본을 늘려주지
않으므로 실질 표본은 월말 시점 수뿐이고, 12개월 창이 겹쳐 독립 관측은 손에 꼽는다.
결과는 참고용이며 이 스크립트도 그 사실을 함께 출력한다.

실행:
  python3 -m scripts.bt_variants --dsn "$DIVDESK_DSN"
  python3 -m scripts.bt_variants --csv /tmp
"""
from __future__ import annotations

import argparse
import statistics as st
from bisect import bisect_right
from collections import defaultdict, deque
from datetime import date, timedelta

from scripts.backtest import (bench_slope, forward_return, load_csv, load_db,
                              month_ends)
from scripts.bt_report import corr, pct

OUT_H = 252                     # forward 12개월 (거래일)
WIN52 = 252                     # 52주 창
MIN_DD_HISTORY = 252            # 낙폭 이력 최소 1년 — 상장 초기 왜곡 방지
SPLIT = date(2022, 1, 1)        # 기간 분할 경계


def _pdate(s) -> date:
    return date.fromisoformat(str(s)[:10])


def rolling_dd(close: list) -> list:
    """일자별 52주 고점 대비 낙폭. 앞쪽 미성립 구간은 None.

    dd[k] = close[k] / max(close[k-251:k+1]) - 1   (0 이하, 클수록 고점 근처)
    단조 덱으로 슬라이딩 최대값을 O(n) 에 낸다.
    """
    out = [None] * len(close)
    dq: deque = deque()                      # 내림차순 인덱스
    for k, v in enumerate(close):
        while dq and close[dq[-1]] <= v:
            dq.pop()
        dq.append(k)
        while dq[0] <= k - WIN52:
            dq.popleft()
        if k >= WIN52 - 1:
            hi = close[dq[0]]
            if hi > 0:
                out[k] = v / hi - 1
    return out


def variants(dd_series: list, i: int):
    """as_of 기준 세 방식의 '많이 빠진 정도' (0~1). i = as_of 이하 행 개수.

    반환 None 은 판단 불가(이력 부족)로, 점수화하지 않고 제외한다.
    """
    k = i - 1
    cur = dd_series[k] if 0 <= k < len(dd_series) else None
    if cur is None:
        return None
    past = [d for d in dd_series[:k + 1] if d is not None]
    if len(past) < MIN_DD_HISTORY:
        return None

    pos_a = max(0.0, min(1.0, -cur / 0.10))              # 현행: -10% 만점

    worst = min(past)                                     # 과거 최대 낙폭(최소값)
    pos_b = max(0.0, min(1.0, cur / worst)) if worst < 0 else 0.0

    # 백분위: 과거 낙폭 중 '지금보다 덜 빠진' 비율. 지금이 최악이면 1.0
    above = sum(1 for d in past if d > cur)
    pos_c = above / len(past)

    return {"A": pos_a, "B": pos_b, "C": pos_c, "dd": cur, "worst": worst}


def fx_signal(fx_dates: list, fx_vals: list, as_of: date, years: int):
    """환율 밴드 위치를 '싼 정도'(0~1)로. 값이 클수록 원화가 강해 매수에 유리."""
    f = bisect_right(fx_dates, as_of)
    if f == 0:
        return None
    now = fx_vals[f - 1]
    cut = as_of - timedelta(days=365 * years)
    s = bisect_right(fx_dates, cut)
    hist = fx_vals[s:f]
    if len(hist) < 250 * years * 0.8:        # 해당 기간 데이터가 실제로 있어야 한다
        return None
    below = sum(1 for v in hist if v < now)
    return 1 - below / len(hist)


def fx_at(fx_dates: list, fx_vals: list, d: date):
    f = bisect_right(fx_dates, d)
    return fx_vals[f - 1] if f > 0 else None


def forward_return_krw(ts, panel, as_of: date, horizon: int):
    """원화 환산 forward 수익. 달러 수익 × 환율 변화."""
    i = bisect_right(ts.dates, as_of)
    tgt = i - 1 + horizon
    if i == 0 or tgt >= len(ts.dates):
        return None
    base, fut = ts.adj[i - 1], ts.adj[tgt]
    if base is None or fut is None or float(base) <= 0:
        return None
    fx0 = fx_at(panel.fx_dates, panel.fx_vals, ts.dates[i - 1])
    fx1 = fx_at(panel.fx_dates, panel.fx_vals, ts.dates[tgt])
    if not fx0 or not fx1:
        return None
    return (float(fut) * fx1) / (float(base) * fx0) - 1


def within_ticker_key(rows, key, out):
    by_t = defaultdict(list)
    for r in rows:
        if r.get(out) is not None and r.get(key) is not None:
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
        f3 = fx_signal(panel.fx_dates, panel.fx_vals, me, 3)
        f5 = fx_signal(panel.fx_dates, panel.fx_vals, me, 5)
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
            rows.append({
                "ticker": t, "date": me, "regime": regime,
                "A": v["A"], "B": v["B"], "C": v["C"],
                "dd": v["dd"], "worst": v["worst"],
                "fx3": f3, "fx5": f5,
                "usd": forward_return(ts, me, OUT_H),
                "krw": forward_return_krw(ts, panel, me, OUT_H),
            })
    return rows, mes


def line(rows, key, out, label):
    c = corr([r for r in rows if r.get(key) is not None], key, out)
    wt, pos, used = within_ticker_key(rows, key, out)
    early = [r for r in rows if r["date"] < SPLIT]
    late = [r for r in rows if r["date"] >= SPLIT]
    ce = corr([r for r in early if r.get(key) is not None], key, out)
    cl = corr([r for r in late if r.get(key) is not None], key, out)
    f = lambda x: f"{x:+.3f}" if x is not None else "  n/a"      # noqa: E731
    ws = pct(wt) if wt is not None else "  n/a"
    return (f"{label:<18}{f(c):>9}{ws:>11}{f'{pos}/{used}':>9}"
            f"{f(ce):>11}{f(cl):>11}")


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
    print("== 낙폭 정규화 3방식 (forward 12개월, 달러 기준) ==")
    print(f"월말 {len(mes)}개 ({mes[0]} ~ {mes[-1]}) / 관측 {len(usd)} / "
          f"종목 {len(set(r['ticker'] for r in usd))}")
    print("값이 클수록 '많이 빠진 상태'. 양(+)이면 그때 사는 게 나았다는 뜻.\n")
    print(f"{'방식':<18}{'상관':>9}{'동일종목차':>11}{'양(+)':>9}"
          f"{'~2021':>11}{'2022~':>11}")
    print(line(usd, "A", "usd", "A 현행(-10%)"))
    print(line(usd, "B", "usd", "B 최대낙폭대비"))
    print(line(usd, "C", "usd", "C 낙폭백분위"))

    for reg in ("up", "down"):
        sub = [r for r in usd if r["regime"] == reg]
        if len(sub) < 50:
            print(f"\n[국면 {reg}] n{len(sub)} 부족")
            continue
        print(f"\n[국면 {reg}] n{len(sub)}")
        for k, lab in (("A", "A 현행"), ("B", "B 최대대비"), ("C", "C 백분위")):
            c = corr(sub, k, "usd")
            print(f"  {lab:<12} 상관 {c:+.3f}" if c is not None
                  else f"  {lab:<12} n/a")

    # 낙폭 크기 자체가 얼마나 되는지 — 종목별 기준 차이를 눈으로 확인
    worst_by_t = {}
    for r in usd:
        w = worst_by_t.get(r["ticker"])
        if w is None or r["worst"] < w:
            worst_by_t[r["ticker"]] = r["worst"]
    ws = sorted(worst_by_t.items(), key=lambda kv: kv[1])
    print("\n[종목별 관측 최대낙폭 — 절대기준이 왜 불공평한지]")
    print("  최악 3종: " + ", ".join(f"{t} {w * 100:.0f}%" for t, w in ws[:3]))
    print("  최소 3종: " + ", ".join(f"{t} {w * 100:.0f}%" for t, w in ws[-3:]))

    # ── 환율 ─────────────────────────────────────
    krw = [r for r in rows if r["krw"] is not None and r["fx3"] is not None]
    print("\n== 환율 밴드 (forward 12개월, 원화 환산) ==")
    if len(krw) < 50:
        print(f"  관측 {len(krw)} — 부족(환율 이력이 2021-08 부터)")
    else:
        dates = sorted({r["date"] for r in krw})
        print(f"  관측 {len(krw)} / 월말 {len(dates)}개 "
              f"({dates[0]} ~ {dates[-1]})")
        for k, lab in (("fx3", "3년 밴드"), ("fx5", "5년 밴드")):
            sub = [r for r in krw if r.get(k) is not None]
            if len(sub) < 50:
                print(f"  {lab:<10} 관측 {len(sub)} — 부족")
                continue
            c = corr(sub, k, "krw")
            print(f"  {lab:<10} 상관 {c:+.3f} (n{len(sub)})" if c is not None
                  else f"  {lab:<10} n/a")
        print("  ※ 환율 신호는 같은 날 전 종목이 동일하다. 종목 수가 표본을 "
              f"늘려주지 않으며\n    실질 표본은 월말 {len(dates)}개, "
              "12개월 창이 겹쳐 독립 관측은 한 자릿수다. 참고용.")

    print("\n주의: 12개월 창 중첩으로 유효 독립표본은 표시 n 보다 훨씬 적다. "
          "방향과 기간 일관성만 읽을 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
