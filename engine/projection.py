"""적립 투자 시뮬레이션.

"매달 100만원씩 10년 넣으면 얼마가 되나?"에 답한다.

**단일 숫자를 내지 않는다.** 과거 평균 수익률로 복리를 굴려 "10년 뒤 3억"이라고
말하는 건 거짓말에 가깝다. 언제 시작했느냐에 따라 결과가 두 배 넘게 갈리기 때문이다.

그래서 실제 과거 데이터 위에서 **시작 시점을 바꿔가며 여러 번 돌린다**(롤링 백테스트).
2015년 1월에 시작한 경우, 2015년 2월에 시작한 경우… 각각의 결과를 모아
최악·중간·최선을 함께 보여준다. 범위를 보여주는 것이 정직하다.

수정종가(adj_close)를 쓰므로 분배금 재투자가 반영된 총수익 기준이다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Scenario:
    start: date
    end: date
    invested: float
    final_value: float

    @property
    def profit(self) -> float:
        return self.final_value - self.invested

    @property
    def return_pct(self) -> float:
        return (self.final_value / self.invested - 1) * 100 if self.invested else 0.0

    @property
    def annualized_pct(self) -> float:
        """연평균 수익률. 적립식은 돈이 들어간 기간이 제각각이라
        단순 CAGR이 아니라 평균 투자기간(약 절반)을 반영해 근사한다."""
        years = (self.end - self.start).days / 365.25
        if years <= 0 or self.invested <= 0:
            return 0.0
        avg_years = years / 2 + 0.5      # 매달 넣으면 평균 보유기간은 대략 절반
        ratio = self.final_value / self.invested
        return ((ratio ** (1 / avg_years)) - 1) * 100 if ratio > 0 else 0.0


@dataclass
class Projection:
    ticker: str
    monthly_krw: float
    years: int
    windows: int                     # 몇 개의 시작 시점을 시험했는지
    total_invested_krw: float
    worst: Scenario | None = None
    median: Scenario | None = None
    best: Scenario | None = None
    median_final_krw: float = 0.0
    median_profit_krw: float = 0.0
    median_return_pct: float = 0.0
    median_annual_pct: float = 0.0
    loss_windows: int = 0            # 원금을 밑돈 경우의 수
    data_from: date | None = None
    data_to: date | None = None
    notes: list[str] = field(default_factory=list)


def _month_key(day: date) -> tuple:
    return (day.year, day.month)


def _monthly_points(series: list) -> list:
    """(날짜, 수정종가) 시계열에서 매달 첫 거래일만 추린다."""
    seen: set = set()
    out = []
    for day, adj in sorted(series):
        if adj is None or adj <= 0:
            continue
        key = _month_key(day)
        if key in seen:
            continue
        seen.add(key)
        out.append((day, float(adj)))
    return out


def common_start(series_map: dict) -> date | None:
    """여러 종목을 비교할 때 공통으로 존재하는 가장 이른 시점.

    이걸 안 맞추면 비교가 거짓말이 된다. QQQ는 1999년부터, SCHD는 2011년부터라
    각자의 전체 이력으로 돌리면 QQQ에만 닷컴버블이 들어가 최악값이 훨씬 나쁘게 나온다.
    상품이 위험해서가 아니라 겪은 시대가 달라서 생긴 차이다.
    """
    starts = []
    for series in series_map.values():
        points = _monthly_points(series)
        if points:
            starts.append(points[0][0])
    return max(starts) if starts else None


def simulate(ticker: str, series: list, monthly_krw: float, years: int,
             step_months: int = 1, since: date | None = None) -> Projection:
    """series: [(date, adj_close), ...]  — 수정종가여야 총수익 기준이 된다.

    since 를 주면 그 시점 이후만 쓴다. 여러 종목을 같은 기간으로 비교할 때 필요하다.
    """
    if monthly_krw <= 0:
        raise ValueError("월 적립액은 0보다 커야 합니다")
    if years <= 0:
        raise ValueError("기간은 1년 이상이어야 합니다")

    points = _monthly_points(series)
    if since:
        points = [p for p in points if p[0] >= since]
    need = years * 12
    result = Projection(ticker=ticker, monthly_krw=monthly_krw, years=years,
                        windows=0, total_invested_krw=monthly_krw * need)
    if len(points) < need + 1:
        have = len(points) / 12
        result.notes.append(
            f"{years}년 시뮬레이션에는 {need + 1}개월치 시세가 필요한데 "
            f"{len(points)}개월치({have:.1f}년)뿐입니다. "
            f"기간을 {max(1, int(have) - 1)}년 이하로 줄이거나 이력을 더 수집하세요.")
        return result

    result.data_from, result.data_to = points[0][0], points[-1][0]

    scenarios: list[Scenario] = []
    for offset in range(0, len(points) - need, step_months):
        window = points[offset:offset + need + 1]
        shares = 0.0
        for _, price in window[:need]:
            shares += monthly_krw / price
        final = shares * window[need][1]
        scenarios.append(Scenario(start=window[0][0], end=window[need][0],
                                  invested=monthly_krw * need, final_value=final))

    if not scenarios:
        result.notes.append("시뮬레이션할 구간이 없습니다.")
        return result

    ordered = sorted(scenarios, key=lambda s: s.final_value)
    mid = ordered[len(ordered) // 2]
    result.windows = len(ordered)
    result.worst, result.median, result.best = ordered[0], mid, ordered[-1]
    result.median_final_krw = round(mid.final_value)
    result.median_profit_krw = round(mid.profit)
    result.median_return_pct = round(mid.return_pct, 1)
    result.median_annual_pct = round(mid.annualized_pct, 2)
    result.loss_windows = sum(1 for s in ordered if s.profit < 0)

    span = (points[-1][0] - points[0][0]).days / 365.25
    result.notes.append(
        f"과거 {span:.0f}년 데이터에서 시작 시점을 {len(ordered)}가지로 바꿔 계산한 결과입니다. "
        "과거 성과가 미래를 보장하지 않습니다.")
    if result.loss_windows:
        result.notes.append(
            f"{len(ordered)}번 중 {result.loss_windows}번은 {years}년을 채우고도 "
            "원금을 밑돌았습니다.")
    if span < years * 2:
        result.notes.append(
            "데이터 기간이 짧아 시험한 시작 시점이 몇 개 없습니다. "
            "특정 시기의 시장 상황에 결과가 크게 좌우됩니다.")
    return result


def compare(projections: list) -> dict:
    """여러 종목을 같은 조건으로 비교한다. 벤치마크가 섞여 있으면 기준으로 삼는다."""
    valid = [p for p in projections if p.windows > 0]
    if not valid:
        return {"items": [], "notes": ["비교할 수 있는 종목이 없습니다."]}
    ranked = sorted(valid, key=lambda p: -p.median_final_krw)
    return {
        "items": ranked,
        "best": ranked[0].ticker,
        "worst": ranked[-1].ticker,
        "spread_krw": round(ranked[0].median_final_krw - ranked[-1].median_final_krw),
    }


def growth_quality(series: list, years: int = 5) -> dict:
    """가격이 꾸준히 올랐는지 평가한다.

    배당만 보고 고르면 주가가 계속 빠지는 종목을 사게 된다. 분배금을 받아도
    원금이 깎이면 손해다. 그래서 '꾸준한 상승'을 별도로 점수화한다.

    보는 것:
      - 연도별 총수익이 플러스인 해의 비율 (꾸준함)
      - 최대 낙폭 (버틸 수 있는지)
      - 전체 기간 연평균 총수익률
    """
    points = _monthly_points(series)
    if len(points) < 24:
        return {"available": False, "reason": "데이터가 2년 미만입니다"}

    window = points[-(years * 12 + 1):] if len(points) > years * 12 else points
    start_val, end_val = window[0][1], window[-1][1]
    span_years = (window[-1][0] - window[0][0]).days / 365.25
    cagr = ((end_val / start_val) ** (1 / span_years) - 1) * 100 if span_years > 0 else 0.0

    # 12개월 단위 구간 수익률
    yearly = []
    for i in range(0, len(window) - 12, 12):
        a, b = window[i][1], window[i + 12][1]
        if a > 0:
            yearly.append((b / a - 1) * 100)
    positive = sum(1 for y in yearly if y > 0)

    peak, mdd = window[0][1], 0.0
    for _, value in window:
        peak = max(peak, value)
        mdd = min(mdd, (value / peak - 1) * 100)

    consistency = (positive / len(yearly)) if yearly else None
    return {
        "available": True,
        "cagr_pct": round(cagr, 2),
        "years": round(span_years, 1),
        "up_years": positive,
        "total_years": len(yearly),
        "consistency": round(consistency, 2) if consistency is not None else None,
        "mdd_pct": round(mdd, 1),
        "volatility_pct": round(statistics.pstdev(yearly), 1) if len(yearly) > 1 else None,
    }
