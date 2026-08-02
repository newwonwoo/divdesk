#!/usr/bin/env python3
"""백테스트 결과(bt_results.csv) → 화면에 들어가는 작은 요약 표.

무거운 CSV 를 옮기지 않고 서버에서 바로 집계해 붙여넣기 쉬운 크기로 출력한다.

핵심 질문: 타점(timing) 점수가 이후 수익을 실제로 예측하는가.
 - 횡단면 분위: 매 시점 전 종목을 타점으로 나눠 이후 수익 비교
 - 동일종목 내: 종목 고정, 그 종목의 타점이 높을 때 vs 낮을 때 (품질 교란 제거)
 - 국면 분리: 상승/하락장 각각
겹치는 12개월 창이라 유의성은 단정하지 않는다. 방향과 단조성만 본다.
"""
from __future__ import annotations

import csv
import statistics as st
import sys
from collections import defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bt_results.csv"
OUT = "fwd_12m"          # 주 outcome. fwd_6m 로 바꿔도 됨


def load(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                r["timing"] = float(r["timing"])
                r["total"] = float(r["total"])
                r["quality"] = float(r["quality"])
                r["confidence"] = float(r["confidence"])
            except (ValueError, KeyError):
                continue
            for h in ("fwd_3m", "fwd_6m", "fwd_12m"):
                r[h] = float(r[h]) if r.get(h) not in ("", None) else None
            rows.append(r)
    return rows


def pct(x):
    return f"{x * 100:+5.1f}%"


def quintile_table(rows, key, out):
    data = [(r[key], r[out]) for r in rows if r[out] is not None]
    if len(data) < 25:
        return f"  (표본 {len(data)} — 부족)"
    data.sort(key=lambda t: t[0])
    n = len(data)
    lines = []
    for q in range(5):
        lo, hi = q * n // 5, (q + 1) * n // 5
        chunk = data[lo:hi]
        vals = [v for _, v in chunk]
        krange = f"{chunk[0][0]:.0f}~{chunk[-1][0]:.0f}"
        lines.append(f"  Q{q + 1} 점수{krange:>7} | n{len(vals):4d} | "
                     f"평균 {pct(st.mean(vals))} | 중앙 {pct(st.median(vals))}")
    top = [v for _, v in data[4 * n // 5:]]
    bot = [v for _, v in data[:n // 5]]
    lines.append(f"  최상위−최하위 분위 평균차: {pct(st.mean(top) - st.mean(bot))}")
    return "\n".join(lines)


def within_ticker(rows, out):
    """종목 고정: 타점 상위 1/3 vs 하위 1/3 의 이후 수익 차 (품질 교란 제거)."""
    by_t = defaultdict(list)
    for r in rows:
        if r[out] is not None:
            by_t[r["ticker"]].append((r["timing"], r[out]))
    diffs, pos = [], 0
    used = 0
    for t, data in by_t.items():
        if len(data) < 12:
            continue
        data.sort(key=lambda x: x[0])
        k = len(data) // 3
        low = [v for _, v in data[:k]]
        high = [v for _, v in data[-k:]]
        d = st.mean(high) - st.mean(low)
        diffs.append(d)
        pos += 1 if d > 0 else 0
        used += 1
    if not diffs:
        return "  (종목별 표본 부족)"
    return (f"  종목 {used}종 평균차(타점상위−하위): {pct(st.mean(diffs))} | "
            f"양(+) 종목 {pos}/{used}")


def corr(rows, key, out):
    xy = [(r[key], r[out]) for r in rows if r[out] is not None]
    if len(xy) < 25:
        return None
    xs = [a for a, _ in xy]
    ys = [b for _, b in xy]
    try:
        return st.correlation(xs, ys)
    except (st.StatisticsError, AttributeError):
        mx, my = st.mean(xs), st.mean(ys)
        num = sum((a - mx) * (b - my) for a, b in xy)
        den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
        return num / den if den else None


def main():
    rows = load(PATH)
    cand = [r for r in rows if r["is_benchmark"] == "0" and r["confidence"] >= 50]
    bench = [r for r in rows if r["is_benchmark"] == "1" and r[OUT] is not None]

    print(f"== 백테스트 요약 ({OUT}, 신뢰도>=50, 벤치 제외) ==")
    print(f"관측 {len(cand)} (전체 {len(rows)}) / 종목 {len(set(r['ticker'] for r in cand))}")
    if bench:
        bvals = [r[OUT] for r in bench]
        print(f"벤치 매수후보 baseline {OUT} 평균 {pct(st.mean(bvals))} (n{len(bvals)})")

    print("\n[타점 5분위 → 이후수익]")
    print(quintile_table(cand, "timing", OUT))
    print("\n[종합 5분위 → 이후수익]")
    print(quintile_table(cand, "total", OUT))
    print("\n[동일종목 내 타점]")
    print(within_ticker(cand, OUT))

    ct = corr(cand, "timing", OUT)
    cq = corr(cand, "total", OUT)
    print(f"\n상관 timing↔{OUT}: {ct:+.3f} | total↔{OUT}: {cq:+.3f}"
          if ct is not None else "\n상관 계산 표본 부족")

    for reg in ("up", "down"):
        sub = [r for r in cand if r["regime"] == reg]
        d = [(r["timing"], r[OUT]) for r in sub if r[OUT] is not None]
        if len(d) < 25:
            print(f"\n[국면 {reg}] 표본 {len(d)} — 부족")
            continue
        d.sort(key=lambda x: x[0])
        n = len(d)
        top = [v for _, v in d[n // 2:]]
        bot = [v for _, v in d[:n // 2]]
        print(f"\n[국면 {reg}] n{n} | 타점 상위절반 {pct(st.mean(top))} vs "
              f"하위절반 {pct(st.mean(bot))} | 차 {pct(st.mean(top) - st.mean(bot))}")


if __name__ == "__main__":
    main()
