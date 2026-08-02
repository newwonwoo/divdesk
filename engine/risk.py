"""위험조정 수익.

총수익 절대값만 보면 저변동성 상품이 부당하게 낮게 나온다.
JEPI는 변동성이 SPY의 절반인데 수익만 보면 감점된다.

세 지표를 함께 쓴다. 각자 잡는 위험이 다르다.
  Sharpe  전체 변동성 대비 효율. 다만 **상승 변동성까지 위험으로 친다.**
          커버드콜은 옵션으로 상승을 잘라 팔아 상승 변동성이 구조적으로 낮은데,
          Sharpe 는 그걸 "안정적" 이라고 칭찬한다. 그래서 비중을 낮게 둔다.
  Sortino 하락 변동성만 본다. 평상시 손실 위험.
  Calmar  최대낙폭 대비 수익. 최악의 손실 깊이.

    위험조정 = min(Sortino, Calmar) × 0.7 + Sharpe × 0.3

**최솟값을 쓰는 것이 핵심이다.** 평균이면 한 지표가 나빠도 다른 게 덮어준다.
실측에서 JEPQ 는 Sortino 상위권인데 Calmar 하위권이었다 —
"평상시엔 안정적인데 한 번 크게 빠지는" 커버드콜 특성이다.
평균으로는 그게 가려지고, 최솟값으로는 드러난다.

기간은 3년을 쓴다. 1년은 상승장이면 전 종목이 만점에 붙어 변별이 사라진다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

RISK_FREE = 0.04            # 무위험수익률. 국고채·단기 미국채 수준
TRADING_DAYS = 252
MIN_POINTS = 200            # 이보다 짧으면 판단하지 않는다

# 실측 분포를 보고 잡은 배점 구간. 0점과 만점에 몰리지 않는 범위다.
SHARPE_RANGE = (0.3, 1.1)
SORTINO_RANGE = (0.5, 1.5)
CALMAR_RANGE = (0.6, 1.7)


@dataclass
class RiskStat:
    available: bool = False
    years: float = 0.0
    cagr: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    calmar: float | None = None
    mdd: float | None = None          # 최대낙폭 (-0.15 = -15%)
    score: float = 0.0                # 0~10
    capture: float | None = None      # 기초자산 대비 상승참여율 (0.64 = 64%)
    reason: str = ""


def _scale(value: float | None, low: float, high: float) -> float:
    if value is None:
        return 5.0                    # 판단 불가는 중립
    return max(0.0, min(10.0, (value - low) / (high - low) * 10))


def compute(prices: list, benchmark_cagr: float | None = None) -> RiskStat:
    """prices: 수정종가 시계열(오래된 것부터). 분배금 재투자가 반영된 값이어야 한다."""
    clean = [float(p) for p in prices if p is not None and float(p) > 0]
    stat = RiskStat()
    if len(clean) < MIN_POINTS:
        stat.reason = f"거래일 {len(clean)}일치뿐 — {MIN_POINTS}일 필요"
        return stat

    years = len(clean) / TRADING_DAYS
    stat.years = round(years, 1)
    stat.cagr = round((clean[-1] / clean[0]) ** (1 / years) - 1, 4)

    daily = [clean[i] / clean[i - 1] - 1 for i in range(1, len(clean))]
    vol = statistics.pstdev(daily) * (TRADING_DAYS ** 0.5)

    # 하락 변동성: 음수 수익률만으로 계산한다. 상승은 위험이 아니다.
    negatives = [d for d in daily if d < 0]
    downside = ((sum(d * d for d in negatives) / len(daily)) ** 0.5
                * (TRADING_DAYS ** 0.5)) if negatives else None

    peak, mdd = clean[0], 0.0
    for value in clean:
        peak = max(peak, value)
        mdd = min(mdd, value / peak - 1)
    stat.mdd = round(mdd, 4)

    excess = stat.cagr - RISK_FREE
    if vol > 0:
        stat.sharpe = round(excess / vol, 3)
    if downside and downside > 0:
        stat.sortino = round(excess / downside, 3)
    if mdd < 0:
        stat.calmar = round(stat.cagr / abs(mdd), 3)

    sharpe_pt = _scale(stat.sharpe, *SHARPE_RANGE)
    sortino_pt = _scale(stat.sortino, *SORTINO_RANGE)
    calmar_pt = _scale(stat.calmar, *CALMAR_RANGE)

    # 어느 하나라도 나쁘면 낮게 나와야 한다. 위험은 가장 나쁜 얼굴로 판단한다.
    stat.score = round(min(sortino_pt, calmar_pt) * 0.7 + sharpe_pt * 0.3, 1)
    stat.available = True

    if benchmark_cagr and benchmark_cagr > 0 and stat.cagr is not None:
        stat.capture = round(stat.cagr / benchmark_cagr, 3)

    return stat


def describe(stat: RiskStat, dividend_yield: float | None = None) -> tuple[str, str]:
    """(값, 부연). 화면이 그대로 쓴다."""
    if not stat.available:
        return "데이터 부족", stat.reason

    value = f"{stat.cagr * 100:+.1f}%"
    parts = [f"{stat.years:g}년 연평균"]
    if stat.mdd is not None:
        parts.append(f"최대낙폭 {stat.mdd * 100:.1f}%")
    if stat.sortino is not None:
        parts.append(f"Sortino {stat.sortino:.2f}")
    if stat.capture is not None:
        parts.append(f"기초자산 대비 {stat.capture * 100:.0f}%")
    if dividend_yield is not None and stat.cagr is not None:
        if stat.cagr < dividend_yield / 100:
            parts.append("분배금이 원금을 깎는 중")
    return value, " · ".join(parts)
