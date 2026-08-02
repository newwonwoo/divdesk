"""분배금 지속가능성.

기존에는 **최근 1년 증감만** 봤다. 그러면 배당 ETF의 본질을 놓친다.

SCHD가 인기 있는 이유는 10년간 연 11~13%씩 배당이 불어났기 때문이다.
그런데 2023년처럼 한 해 4.9% 성장에 그친 해도 있다. 1년만 보면 그런 해에
"나빠졌다"고 판단하게 된다. 반대로 특별분배가 한 번 끼면 +27% 같은 값이 나와
과대평가된다.

배당 ETF는 장기 복리로 판단해야 한다. 그래서 이렇게 나눈다.

  3년 CAGR      6점   최근 추세. 가장 무겁게 본다
  5년 CAGR      4점   장기 추세. 한두 해 이상치에 둔감하다
  감액 이력      3점   줄인 적이 있는가. 있으면 신뢰가 깎인다
  변동성         2점   들쭉날쭉한가. 생활비로 쓰려면 예측 가능해야 한다

주의: 연도 경계로 자르면 지급 시점이 밀린 해에 회차가 어긋난다.
그래서 '지급 횟수' 기준으로 12개월씩 묶는다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

W_CAGR3, W_CAGR5, W_CUT, W_STABLE = 6, 4, 3, 2
TOTAL = W_CAGR3 + W_CAGR5 + W_CUT + W_STABLE      # 15


@dataclass
class DividendStat:
    available: bool = False
    cagr3: float | None = None        # 3년 연평균 성장률 (0.11 = 11%)
    cagr5: float | None = None
    recent: float | None = None       # 최근 1년 증감
    cuts: int = 0                     # 전년 대비 줄어든 해의 수
    worst_cut: float | None = None    # 가장 크게 줄어든 폭
    volatility: float | None = None   # 연간 성장률의 표준편차
    years: int = 0
    score: float = 0.0                # 0~15
    reason: str = ""


def _yearly_sums(amounts: list, pays_per_year: int) -> list:
    """최근 것부터 pays_per_year 개씩 묶어 연간 합계를 만든다.

    달력 연도로 자르지 않는 이유: 지급일이 밀린 해에 회차가 3회나 5회로 잡혀
    성장률이 통째로 왜곡된다. 실제로 그 문제를 겪었다.
    """
    if pays_per_year <= 0:
        return []
    out = []
    for i in range(0, len(amounts) - pays_per_year + 1, pays_per_year):
        chunk = amounts[i:i + pays_per_year]
        if len(chunk) == pays_per_year:
            out.append(sum(chunk))
    return out          # [최근 1년, 그 전 1년, ...]


def _cagr(newest: float, oldest: float, years: int) -> float | None:
    if oldest <= 0 or newest <= 0 or years <= 0:
        return None
    return (newest / oldest) ** (1 / years) - 1


def compute(amounts_desc: list, pays_per_year: int) -> DividendStat:
    """amounts_desc: 최근 것부터 정렬한 회차별 분배금."""
    stat = DividendStat()
    yearly = _yearly_sums([float(a) for a in amounts_desc], pays_per_year)
    stat.years = len(yearly)
    if len(yearly) < 2:
        stat.reason = f"연간 분배금 {len(yearly)}년치뿐 — 2년 필요"
        return stat

    stat.available = True
    stat.recent = round((yearly[0] - yearly[1]) / yearly[1], 4) if yearly[1] > 0 else None

    if len(yearly) >= 4:
        stat.cagr3 = _cagr(yearly[0], yearly[3], 3)
    if len(yearly) >= 6:
        stat.cagr5 = _cagr(yearly[0], yearly[5], 5)

    # 감액 이력. 한 번이라도 줄였으면 그만큼 신뢰가 깎인다.
    changes = []
    for i in range(len(yearly) - 1):
        if yearly[i + 1] > 0:
            changes.append((yearly[i] - yearly[i + 1]) / yearly[i + 1])
    stat.cuts = sum(1 for c in changes if c < -0.02)
    if changes:
        stat.worst_cut = round(min(changes), 4)
        if len(changes) > 1:
            stat.volatility = round(statistics.pstdev(changes), 4)

    # ── 배점 ────────────────────────────────
    # 3년 CAGR: 0% 이하 0점, 10% 이상 만점. SCHD 수준(11%)이면 만점이다.
    if stat.cagr3 is not None:
        pt3 = W_CAGR3 * max(0.0, min(1.0, stat.cagr3 / 0.10))
    else:
        # 3년치가 없으면 최근 1년으로 대신하되 절반만 인정한다
        pt3 = (W_CAGR3 * max(0.0, min(1.0, stat.recent / 0.10)) * 0.5
               if stat.recent is not None else W_CAGR3 * 0.4)

    if stat.cagr5 is not None:
        pt5 = W_CAGR5 * max(0.0, min(1.0, stat.cagr5 / 0.08))
    else:
        pt5 = W_CAGR5 * 0.5          # 판단 불가는 중립

    # 감액: 한 번도 없으면 만점, 한 번에 1점씩 깎고 큰 감액은 추가 감점
    pt_cut = W_CUT
    pt_cut -= min(W_CUT, stat.cuts * 1.0)
    if stat.worst_cut is not None and stat.worst_cut < -0.15:
        pt_cut -= 1
    pt_cut = max(0.0, pt_cut)

    # 변동성: 성장률이 들쭉날쭉하면 생활비 계획이 어긋난다
    if stat.volatility is not None:
        pt_stable = W_STABLE * max(0.0, min(1.0, (0.20 - stat.volatility) / 0.20))
    else:
        pt_stable = W_STABLE * 0.5

    stat.score = round(pt3 + pt5 + pt_cut + pt_stable, 1)
    return stat


def describe(stat: DividendStat) -> tuple[str, str]:
    """(값, 부연). 화면이 그대로 쓴다."""
    if not stat.available:
        return "이력 부족", stat.reason

    if stat.cagr3 is not None:
        value = f"연 {stat.cagr3 * 100:+.1f}%"
        parts = ["3년 평균 성장"]
    elif stat.recent is not None:
        value = f"{stat.recent * 100:+.1f}%"
        parts = ["최근 1년 (3년치 없음)"]
    else:
        value = "판단 불가"
        parts = []

    if stat.cagr5 is not None:
        parts.append(f"5년 {stat.cagr5 * 100:+.1f}%")
    if stat.cuts:
        parts.append(f"감액 {stat.cuts}회")
        if stat.worst_cut is not None:
            parts.append(f"최대 {stat.worst_cut * 100:.0f}%")
    else:
        parts.append("감액 없음")
    return value, " · ".join(parts)
