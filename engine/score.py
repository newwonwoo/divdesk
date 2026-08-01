"""매수타점 스코어 엔진 (0~100).

설계 의도: "배당률이 높으면 좋다"가 아니라 "이 종목의 과거 자기 배당률 대비
지금이 싼가"를 본다. 그래서 절대 배당률이 아니라 5년 밴드 내 백분위를 쓴다.
QYLD 같은 초고배당이 낮은 점수를 받는 게 정상이다.

배점: 배당률 백분위 30 / 가격 위치 20 / 분배금 건강도 20
      / 총수익 정합성 10 / 환율 위치 10 / 배당락 타이밍 10
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

W_YIELD, W_PRICE, W_DPS, W_RET, W_FX, W_EX = 30, 20, 20, 10, 10, 10

GRADE_BUY_HARD = 85
GRADE_BUY = 70
GRADE_HOLD = 55


@dataclass
class ScoreInput:
    ticker: str
    price: float
    ttm_dps: float
    yield_history: list[float] = field(default_factory=list)   # 과거 배당률(%) 시계열
    ma200: float | None = None
    high52: float | None = None
    low52: float | None = None
    dps_ttm_prev: float | None = None      # 직전 1년 분배금 합계
    dps_cut_history: bool = False          # 과거 감액·중단 이력
    total_return_1y_pct: float | None = None
    fx_history: list[float] = field(default_factory=list)      # USD/KRW 3년
    fx_now: float | None = None
    days_to_ex: int | None = None          # 다음 배당락까지 일수
    is_covered_call: bool = False
    is_krw_listed: bool = False


@dataclass
class ScoreResult:
    ticker: str
    total: int
    grade: str
    yield_pctile: float
    price_pos: float
    dps_health: float
    total_ret: float
    fx_pos: float
    exdate_pen: float
    reason: str
    # [(라벨, 값, 부연)] — 화면이 한 덩어리 문장 대신 표로 그린다
    facts: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _pctile(value: float, series: list[float]) -> float | None:
    """series 안에서 value가 상위 몇 %인지 (0~1, 1=가장 높음)."""
    clean = [v for v in series if v is not None]
    if len(clean) < 8:          # 표본이 너무 적으면 판단하지 않는다
        return None
    below = sum(1 for v in clean if v < value)
    return below / len(clean)


def score(inp: ScoreInput, today: date | None = None) -> ScoreResult:
    today = today or date.today()
    reasons: list[str] = []
    facts: list = []
    warnings: list[str] = []
    missing: list[str] = []

    # ① 배당률 백분위 (30) — 자기 과거 대비 지금 배당률이 높으면 싸다는 뜻
    cur_yield = (inp.ttm_dps / inp.price * 100) if inp.price else 0.0
    pct = _pctile(cur_yield, inp.yield_history)
    if pct is None:
        yield_pt = W_YIELD * 0.5
        missing.append("배당률 이력 부족 — 중립 처리")
    else:
        yield_pt = W_YIELD * pct
        if pct >= 0.7:
            band = f"자기 이력 상단 {pct:.0%} 지점 (평소보다 싸다)"
        elif pct <= 0.3:
            band = f"자기 이력 하단 {pct:.0%} 지점 (평소보다 비싸다)"
        else:
            band = f"자기 이력 중간 {pct:.0%} 지점"
        reasons.append(f"배당률 {cur_yield:.2f}% — {band}")
        facts.append(("배당률", f"{cur_yield:.2f}%", band))

    # ② 가격 위치 (20) — 200일선 아래 + 52주 하단이면 가점
    price_pt, price_bits = 0.0, []
    if inp.ma200 and inp.ma200 > 0:
        gap = (inp.price - inp.ma200) / inp.ma200
        price_pt += W_PRICE * 0.5 * max(0.0, min(1.0, 0.5 - gap * 5))
        price_bits.append(f"200일선 {gap:+.1%}")
    else:
        price_pt += W_PRICE * 0.25
        missing.append("200일선 없음")
    if inp.high52 and inp.low52 and inp.high52 > inp.low52:
        pos = (inp.price - inp.low52) / (inp.high52 - inp.low52)
        price_pt += W_PRICE * 0.5 * (1 - max(0.0, min(1.0, pos)))
        price_bits.append(f"52주 밴드 {pos:.0%} 위치")
    else:
        price_pt += W_PRICE * 0.25
        missing.append("52주 고저 없음")
    if price_bits:
        reasons.append(" · ".join(price_bits))
        facts.append(("가격 위치", price_bits[0], price_bits[1] if len(price_bits) > 1 else ""))

    # ③ 분배금 건강도 (20) — 늘고 있으면 가점, 줄면 감점, 감액 이력은 별도 감점
    if inp.dps_ttm_prev and inp.dps_ttm_prev > 0:
        growth = (inp.ttm_dps - inp.dps_ttm_prev) / inp.dps_ttm_prev
        dps_pt = W_DPS * max(0.0, min(1.0, 0.5 + growth * 5))
        reasons.append(f"분배금 12개월 {growth:+.1%}")
        facts.append(("분배금", f"{growth:+.1%}", "최근 12개월"))
        if growth < -0.10:
            warnings.append(f"분배금이 1년 새 {growth:.1%} 줄었습니다")
    else:
        dps_pt = W_DPS * 0.5
        missing.append("직전 연도 분배금 없음 — 중립 처리")
    if inp.dps_cut_history:
        dps_pt *= 0.7
        warnings.append("과거 분배금 감액·중단 이력이 있습니다")

    # ④ 총수익 정합성 (10) — 분배금이 원금을 깎아먹고 있지 않은지
    if inp.total_return_1y_pct is None:
        ret_pt = W_RET * 0.5
        missing.append("1년 총수익률 없음 — 중립 처리")
    else:
        facts.append(("1년 총수익", f"{inp.total_return_1y_pct:+.1f}%",
                      f"분배율 {cur_yield:.1f}%"))
        diff = inp.total_return_1y_pct - cur_yield
        ret_pt = W_RET * max(0.0, min(1.0, 0.5 + diff / 20))
        if diff < -2:
            warnings.append(
                f"1년 총수익 {inp.total_return_1y_pct:.1f}%가 분배율 {cur_yield:.1f}%보다 "
                "낮습니다 — 분배금이 원금을 깎고 있을 수 있습니다")

    # ⑤ 환율 위치 (10) — 원화 투자자 관점. 환율이 높을 때 사면 불리
    if inp.is_krw_listed:
        fx_pt = W_FX                      # 국내상장 원화매수는 환 시점 리스크가 작다
        reasons.append("원화 상장 — 환율 시점 부담 없음")
        facts.append(("환율", "해당 없음", "원화 상장"))
    else:
        fx_now = inp.fx_now
        fx_pct = _pctile(fx_now, inp.fx_history) if fx_now else None
        if fx_pct is None:
            fx_pt = W_FX * 0.5
            missing.append("환율 이력 부족 — 중립 처리")
        else:
            fx_pt = W_FX * (1 - fx_pct)
            reasons.append(f"환율 {fx_now:,.0f}원 — 3년 밴드 {fx_pct:.0%} 지점"
                           + (" (비싼 구간)" if fx_pct >= 0.7 else ""))
            facts.append(("환율", f"{fx_now:,.0f}원",
                          f"3년 밴드 {fx_pct:.0%}" + (" · 비싼 구간" if fx_pct >= 0.7 else "")))
            if fx_pct > 0.8:
                warnings.append("환율이 3년 상단권입니다 — 환차손 위험을 감안하세요")

    # ⑥ 배당락 타이밍 (10) — 배당락 직전 매수는 가격에 배당이 이미 붙어 있다
    if inp.days_to_ex is None:
        ex_pt = W_EX * 0.5
        missing.append("다음 배당락일 미상 — 중립 처리")
    elif inp.days_to_ex <= 3:
        ex_pt = W_EX * 0.2
        reasons.append(f"배당락 D-{inp.days_to_ex} — 지금 사면 고점 매수가 됩니다")
        facts.append(("배당락", f"D-{inp.days_to_ex}", "임박 — 지금 사면 고점"))
    elif inp.days_to_ex <= 10:
        ex_pt = W_EX * 0.5
        reasons.append(f"배당락 D-{inp.days_to_ex}")
        facts.append(("배당락", f"D-{inp.days_to_ex}", ""))
    else:
        ex_pt = W_EX
        reasons.append(f"배당락까지 {inp.days_to_ex}일 여유")
        facts.append(("배당락", f"{inp.days_to_ex}일 뒤", "여유 있음"))

    total = round(yield_pt + price_pt + dps_pt + ret_pt + fx_pt + ex_pt)
    total = max(0, min(100, total))

    if total >= GRADE_BUY_HARD:
        grade = "적극매수"
    elif total >= GRADE_BUY:
        grade = "매수"
    elif total >= GRADE_HOLD:
        grade = "분할·관망"
    else:
        grade = "보류"

    # 커버드콜은 점수와 무관하게 배지를 강제로 붙인다
    if inp.is_covered_call:
        warnings.insert(0, "분배금 ≠ 수익 — 옵션 프리미엄과 원금환급이 섞여 있어 "
                           "총수익 기준으로 판단해야 합니다")

    if len(missing) >= 3:
        warnings.append(f"데이터 {len(missing)}개 항목이 비어 중립 처리했습니다 — 점수 신뢰도가 낮습니다")

    return ScoreResult(
        ticker=inp.ticker, total=total, grade=grade, facts=facts,
        yield_pctile=round(yield_pt, 1), price_pos=round(price_pt, 1),
        dps_health=round(dps_pt, 1), total_ret=round(ret_pt, 1),
        fx_pos=round(fx_pt, 1), exdate_pen=round(ex_pt, 1),
        reason=" · ".join(reasons), warnings=warnings, missing=missing,
    )
