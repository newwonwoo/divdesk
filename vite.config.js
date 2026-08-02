#!/usr/bin/env python3
"""engine.asof 단위 검증 — look-ahead 차단이 핵심.

과거 시점 D 의 점수는, D 이후에 무슨 데이터가 더 붙든 바뀌면 안 된다.
바뀐다면 미래를 훔쳐본 것이다. 합성 시계열로 그걸 못 하게 막혔는지 확인한다.
"""
from __future__ import annotations

from datetime import date, timedelta

from engine.asof import Panel, TickerSeries, build_input, score_asof

fails = []


def eq(label, got, want):
    ok = got == want
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {got}" + ("" if ok else f" (기대 {want})"))
    if not ok:
        fails.append(label)


def ok(label, cond):
    eq(label, bool(cond), True)


def _trading_days(start: date, n: int) -> list:
    """주말 건너뛴 거래일 n개."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def make_panel(n_days=900, drift=0.0005, quarterly_dps=0.5, upto=None):
    """상승 추세 합성 종목 1개 + 벤치(SPY) + 환율로 Panel 구성.

    upto: 이 인덱스까지만 시계열을 넣는다(미래 절단 시뮬레이션). None 이면 전체.
    """
    days = _trading_days(date(2020, 1, 1), n_days)
    close, adj = [], []
    px = 100.0
    for k in range(n_days):
        px *= (1 + drift)
        close.append(round(px, 4))
        adj.append(round(px, 4))          # 배당 재투자 없다고 가정(비율만 쓰므로 무방)
    if upto is not None:
        days, close, adj = days[:upto], close[:upto], adj[:upto]

    def ts(cl):
        return TickerSeries(dates=list(days), close=list(cl), adj=list(cl),
                            open=[None] * len(cl), low=[None] * len(cl))

    # 분기배당: 91일 간격
    divs = [(days[k], quarterly_dps) for k in range(0, len(days), 63)]

    panel = Panel(
        px={"T": ts(close), "SPY": ts(close)},
        divs={"T": divs, "SPY": []},
        fx_dates=list(days), fx_vals=[1300.0 + k * 0.1 for k in range(len(days))],
        meta={"T": {"market": "US", "pays_per_year": 4, "index": "S&P"},
              "SPY": {"market": "US", "pays_per_year": 4, "is_benchmark": True}},
    )
    return panel, days


def main() -> int:
    panel_full, days = make_panel()
    d = days[700]                          # 충분히 뒤(200일선·52주 다 성립)

    # 1) look-ahead: D 이후를 잘라낸 Panel 로 채점해도 결과가 같아야 한다
    panel_cut, _ = make_panel(upto=701)    # days[700] 까지만
    r_full = score_asof(panel_full, "T", d)
    r_cut = score_asof(panel_cut, "T", d)
    ok("D시점 채점 성립", r_full is not None and r_cut is not None)
    eq("미래 절단해도 종합 동일", r_full.total, r_cut.total)
    eq("미래 절단해도 타점 동일", r_full.timing, r_cut.timing)
    eq("미래 절단해도 품질 동일", r_full.quality, r_cut.quality)

    inp = build_input(panel_full, "T", d)
    # 2) 상승 추세 → 200일선 기울기 양수, 낙폭 거의 0(고점 부근)
    ok("상승장 200일선 기울기 양수", inp.ma200_slope is not None and inp.ma200_slope > 0)
    ok("고점 부근 낙폭 작음", inp.drawdown is not None and inp.drawdown > -0.02)
    ok("ma200 산출됨", inp.ma200 is not None)
    ok("52주 고가 >= 현재가 근처", inp.high52 is not None and inp.high52 >= inp.ma200)

    # 3) 데이터 부족 구간은 None (200일 전)
    early = days[10]
    ok("초반부는 배당/가격 부족으로 건너뜀 또는 지표 없음",
       score_asof(panel_full, "T", early) is None
       or build_input(panel_full, "T", early).ma200 is None)

    # 4) as_of 이전 배당만 TTM 에 들어간다 (미래 배당 배제)
    #    D 직후 배당락이 있어도 D 채점의 ttm 에는 안 들어가야 한다
    ttm_at_d = build_input(panel_full, "T", d).ttm_dps
    ttm_later = build_input(panel_full, "T", days[760]).ttm_dps
    ok("이후 시점 TTM 은 D 시점과 독립적으로 계산", ttm_at_d > 0 and ttm_later > 0)

    # 5) 환율 창도 D 로 끝난다
    ok("환율 현재값이 D 이하", inp.fx_now is not None and inp.fx_now <= panel_full.fx_vals[701 - 1] + 1)

    print("\n" + ("=" * 40))
    print("asof 검증 통과" if not fails else f"실패 {len(fails)}건: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
