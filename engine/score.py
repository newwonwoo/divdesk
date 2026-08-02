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

W_YIELD, W_PRICE, W_DPS, W_RET, W_FX, W_EX = 30, 20, 15, 15, 10, 10
# W_RET 은 '위험조정 수익' 이다. 총수익 절대값만 보면 저변동성 상품이 부당하게
# 낮게 나온다(JEPI 는 변동성이 SPY 의 절반인데 수익만 보면 감점).
# 분배금 20 → 15 로 줄이고 그 5점을 여기로 옮겼다. 1년 증가율 하나에
# 20점을 걸면 특별분배·기저효과에 과민해진다.
# W_EX 는 '배당락 회복력'이다. 배당락일에 배당금보다 덜 떨어지는 종목이 좋다.
# 남은 일수는 매수 타이밍일 뿐 종목의 질이 아니라서 점수에서 뺐다.

GRADE_BUY_HARD = 85
GRADE_BUY = 70
GRADE_HOLD = 55

# 상품 품질이 이 아래면 종합점수와 무관하게 제외한다.
# 나쁜 상품이 싸 보인다고 사는 것을 막기 위한 하한선이다.
#
# 위험조정 수익 도입으로 점수 분포가 내려가 60 은 과반을 걸러낸다.
# 실측 분포(QYLD 29, JEPI 30 vs SCHD 52, VYM 65)를 보면 50 이
# "명백히 부실" 과 "평범" 을 가르는 지점이다.
QUALITY_FLOOR = 50


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
    dps_cut_history: bool = False          # 과거 감액·중단 이력 (구버전 호환)
    dps_score: float | None = None         # 분배금 지속가능성 0~15 (engine.dividend)
    dps_label: str = ""
    dps_sub: str = ""
    total_return_1y_pct: float | None = None
    risk_score: float | None = None        # 위험조정 수익 0~10 (engine.risk)
    risk_label: str = ""
    risk_sub: str = ""
    fx_history: list[float] = field(default_factory=list)      # USD/KRW 3년
    fx_now: float | None = None
    days_to_ex: int | None = None          # 다음 배당락까지 일수 (참고 표시용)
    # 배당락일 하락폭 ÷ 배당금. 1.0 이면 배당금만큼만 떨어진 것.
    # 1.0 을 크게 넘으면 배당 노린 매물이 몰려 추가로 밀리는 종목이다.
    exdrop_ratio: float | None = None
    exdrop_samples: int = 0
    exdrop_recovery: float | None = None   # 전날 종가 회복까지 거래일 (중앙값)
    exdrop_unrecovered: int = 0            # 한도 안에 회복 못 한 횟수
    exdrop_gap: float | None = None        # 장중 저가→종가 되돌림 %
    change_20d: float | None = None        # 최근 20거래일 변동률 (0.12 = +12%)
    ma200_slope: float | None = None       # 200일선 기울기 (최근 60일 변화율)
    drawdown: float | None = None          # 52주 고점 대비 낙폭 (-0.08 = -8%)
    is_covered_call: bool = False
    is_krw_listed: bool = False            # 원화 상장 여부 (구버전 호환)
    # 상장 통화가 아니라 **기초자산 통화**를 본다.
    # TIGER 미국배당다우존스는 원화 상장이지만 기초자산이 미국이라
    # 환율에 그대로 노출된다. 상장 통화로 판단하면 이걸 놓친다.
    fx_exposed: bool | None = None         # 환율 노출 여부
    fx_hedged: bool = False                # 환헤지 상품인가
    fx_exposed: bool = True                # 기초자산이 해외라 환율에 노출되는가


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
    quality: int = 0        # 상품 품질 0~100
    timing: int = 0         # 매수 타점 0~100
    excluded: bool = False  # 품질 하한 미달
    confidence: int = 100   # 데이터 신뢰도 0~100
    confidence: int = 100   # 데이터 신뢰도 0~100. 중립 처리한 항목이 많을수록 낮다
    # [(라벨, 값, 부연, 획득점수, 만점)] — 화면이 표로 그리고 합계를 검산할 수 있다
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
    warnings: list[str] = []
    missing: list[str] = []

    # ① 배당률 (30) — 절대 수준 18 + 이력 대비 위치 12
    #
    # 예전에는 자기 이력 대비 위치만 봤다. 그러면 배당률 0.44% 인 QQQ 가
    # 28.5/30 을 받는다 — 배당 ETF 앱에서 말이 안 된다.
    # 그리고 배당률이 높다는 것과 지금 싸다는 것은 다른 얘기다.
    # 배당이 늘어도 배당률은 오르기 때문이다.
    cur_yield = (inp.ttm_dps / inp.price * 100) if inp.price else 0.0

    # ①-A 절대 수준 (18) — 배당 ETF 로서 쓸 만한 배당률인가.
    # 3.5% 를 정점으로 삼는다. 그 이상은 고배당 함정 위험이 커진다.
    if cur_yield <= 0:
        level_pt = 0.0
        level_note = "배당 없음"
    elif cur_yield < 3.5:
        level_pt = 18 * (cur_yield / 3.5)
        level_note = f"배당 ETF 기준 {'낮음' if cur_yield < 2 else '보통'}"
    elif cur_yield <= 6.0:
        level_pt = 18.0
        level_note = "적정 구간"
    else:
        # 8% 넘으면 원금 잠식·배당 함정 위험. 12% 에서 절반까지 깎는다.
        level_pt = 18 * max(0.4, 1 - (cur_yield - 6.0) / 12)
        level_note = "고배당 — 지속 가능한지 확인 필요"

    # ①-B 이력 대비 위치 (12) — 자기 과거와 비교해 지금 싼가
    pct = _pctile(cur_yield, inp.yield_history)
    band = ""
    if pct is None:
        pos_pt = 12 * 0.5
        missing.append("배당률 이력 부족 — 중립 처리")
    else:
        pos_pt = 12 * pct
        top = 1 - pct
        # 배당률이 높은 이유는 둘이다 — 배당이 늘었거나, 주가가 빠졌거나.
        # 주가가 고점인데 "싸다" 고 하면 앞뒤가 안 맞으므로 둘 다 확인한다.
        grew = (inp.dps_ttm_prev is not None and inp.dps_ttm_prev > 0
                and inp.ttm_dps > inp.dps_ttm_prev * 1.02)
        near_high = inp.drawdown is not None and inp.drawdown > -0.03
        if pct >= 0.7 and grew and near_high:
            band = f"이력 상위 {top:.0%} — 배당이 늘어서 (주가는 고점)"
        elif pct >= 0.7 and grew:
            band = f"이력 상위 {top:.0%} — 배당이 늘어서"
        elif pct >= 0.7 and near_high:
            band = f"이력 상위 {top:.0%} — 주가는 고점인데 배당률이 높음"
        elif pct >= 0.7:
            band = f"이력 상위 {top:.0%} — 주가가 빠져서"
        elif pct <= 0.3:
            band = f"이력 하위 {pct:.0%} — 평소보다 비싼 편"
        else:
            band = "이력 평균 수준"

    yield_pt = level_pt + pos_pt

    # ② 가격 위치 (20) — 추세 8 + 고점 대비 낙폭 6 + 단기 과열 6
    #
    # 예전에는 "주가가 높으면 감점" 이었다. 그건 오르는 종목을 계속 깎고
    # 떨어지는 종목에 가점을 주는 구조라 논리적으로 틀렸다. 하락 추세 종목이
    # 만점을 받았다. 실제로 SCHD 가 저항선을 돌파하고 시장을 앞지르는 중에
    # 3.1/20 을 받았다.
    #
    # 재야 할 것은 "지금 사면 손해 볼 가능성" 이지 "숫자가 큰가" 가 아니다.
    #   추세    오르는 종목인가. 방향을 본다
    #   낙폭    최근 고점에서 얼마나 빠졌나. 조정이 곧 기회다
    #   과열    한 달 새 급등했는가. 이것만 감점한다
    # 52주 밴드 위치는 뺐다. 장기 상승 종목은 항상 상단에 있고,
    # 그건 좋은 종목이라는 뜻이지 나쁘다는 뜻이 아니다.
    price_pt, price_bits = 0.0, []

    if inp.ma200_slope is not None:
        # 60일간 200일선이 얼마나 올랐나. +3% 이상이면 만점, -3% 이하면 0점
        price_pt += 8 * max(0.0, min(1.0, (inp.ma200_slope + 0.03) / 0.06))
        trend = ("상승 추세" if inp.ma200_slope > 0.01
                 else "하락 추세" if inp.ma200_slope < -0.01 else "횡보")
        price_bits.append(f"200일선 {inp.ma200_slope:+.1%} ({trend})")
        if inp.ma200_slope < -0.02:
            warnings.append("200일선이 꺾여 하락 추세입니다 — 싸 보여도 더 빠질 수 있습니다")
    else:
        price_pt += 4
        missing.append("200일선 추세 없음")

    if inp.drawdown is not None:
        # 고점 대비 -10% 이상 빠졌으면 만점, 고점이면 0점.
        # 조정 없이 계속 오르는 종목을 벌하지는 않는다(최소 2점 보장).
        price_pt += 2 + 4 * max(0.0, min(1.0, -inp.drawdown / 0.10))
        price_bits.append(f"고점 대비 {inp.drawdown:+.1%}")
    else:
        price_pt += 3
        missing.append("고점 대비 낙폭 없음")

    if inp.change_20d is not None:
        # 20거래일 변동률. -5% 이하 만점, +10% 이상 0점.
        price_pt += 6 * max(0.0, min(1.0, (0.10 - inp.change_20d) / 0.15))
        price_bits.append(f"최근 1개월 {inp.change_20d:+.1%}")
        if inp.change_20d > 0.10:
            warnings.append(
                f"최근 한 달에 {inp.change_20d:+.1%} 올랐습니다 — 단기 과열 구간입니다")
    else:
        price_pt += 3
        missing.append("최근 1개월 변동률 없음")

    # ③ 분배금 지속가능성 (15) — 최근 1년이 아니라 장기 성장을 본다.
    # 배당 ETF의 본질은 배당이 꾸준히 불어나는 것이다. 1년만 보면
    # 특별분배 한 번에 과대평가되고, 성장이 잠시 주춤한 해에 과소평가된다.
    growth = 0.0
    if inp.dps_ttm_prev and inp.dps_ttm_prev > 0:
        growth = (inp.ttm_dps - inp.dps_ttm_prev) / inp.dps_ttm_prev

    if inp.dps_score is not None:
        dps_pt = inp.dps_score
        if inp.dps_sub and "감액" in inp.dps_sub and "감액 없음" not in inp.dps_sub:
            warnings.append(f"분배금을 줄인 이력이 있습니다 ({inp.dps_sub})")
    elif inp.dps_ttm_prev and inp.dps_ttm_prev > 0:
        # 장기 이력이 없을 때만 예전 방식으로 물러선다
        dps_pt = W_DPS * max(0.0, min(1.0, 0.5 + growth * 5))
        if growth < -0.10:
            warnings.append(f"분배금이 1년 새 {growth:.1%} 줄었습니다")
    else:
        dps_pt = W_DPS * 0.5
        missing.append("분배금 이력 없음 — 중립 처리")
    if inp.dps_cut_history:
        dps_pt *= 0.7
        warnings.append("과거 분배금 감액·중단 이력이 있습니다")

    # ④ 위험조정 수익 (15) — 절대 수익이 아니라 위험 대비 수익을 본다.
    # 저변동성 상품이 수익만으로 감점되던 문제를 없앤다.
    if inp.risk_score is not None:
        ret_pt = W_RET * (inp.risk_score / 10)
        if inp.total_return_1y_pct is not None and inp.total_return_1y_pct < cur_yield - 2:
            warnings.append(
                f"1년 총수익 {inp.total_return_1y_pct:.1f}%가 분배율 {cur_yield:.1f}%보다 "
                "낮습니다 — 분배금이 원금을 깎고 있을 수 있습니다")
    elif inp.total_return_1y_pct is None:
        ret_pt = W_RET * 0.5
        missing.append("위험조정 수익 없음 — 중립 처리")
    else:
        # 위험 지표를 못 구했을 때만 예전 방식으로 물러선다
        diff = inp.total_return_1y_pct - cur_yield
        ret_pt = W_RET * max(0.0, min(1.0, 0.5 + diff / 20))
        if diff < -2:
            warnings.append(
                f"1년 총수익 {inp.total_return_1y_pct:.1f}%가 분배율 {cur_yield:.1f}%보다 "
                "낮습니다 — 분배금이 원금을 깎고 있을 수 있습니다")

    # ⑤ 환율 위치 (10) — 원화 상장이어도 기초자산이 해외면 환율에 노출된다.
    #
    # 예전에는 원화 상장이면 무조건 만점이었다. 틀렸다.
    # TIGER 미국배당다우존스는 원화로 사지만 기초자산이 미국 주식이라,
    # 원화가 약해지면 ETF 가격이 오른다. 원화 상장이라 없는 건 환전 수수료뿐이다.
    # ⑤ 환율 위치 (10) — 지금 환율이 비싼 구간인가.
    #
    # 예전에는 "원화 상장이면 만점" 이었다. 명백한 오류다. 국내에 원화로
    # 상장된 해외 ETF 도 환헤지를 하지 않으면 기초자산의 달러 가치와
    # 원·달러 환율에 그대로 노출된다. 상장 통화가 아니라 기초자산 통화를 본다.
    fx_label, fx_sub = "미상", ""
    exposed = inp.fx_exposed if inp.fx_exposed is not None else (not inp.is_krw_listed)

    if inp.fx_hedged:
        fx_pt = W_FX * 0.8              # 헤지비용·추적오차가 있어 만점은 아니다
        fx_label, fx_sub = "환헤지", "환율 변동 영향 작음 (헤지비용 발생)"
    elif not exposed:
        fx_pt = W_FX
        fx_label, fx_sub = "해당 없음", "국내 기초자산 — 환율 무관"
    else:
        fx_now = inp.fx_now
        fx_pct = _pctile(fx_now, inp.fx_history) if fx_now else None
        if fx_pct is None:
            fx_pt = W_FX * 0.5
            fx_label = "이력 부족"
            missing.append("환율 이력 부족 — 중립 처리")
        else:
            fx_pt = W_FX * (1 - fx_pct)
            fx_label = f"{fx_now:,.0f}원"
            fx_sub = f"3년 밴드 {fx_pct:.0%}"
            if inp.is_krw_listed:
                fx_sub += " · 원화 상장이지만 기초자산이 해외라 환율에 노출"
            if fx_pct >= 0.7:
                fx_sub += " · 비싼 구간"
                reasons.append(f"환율 {fx_now:,.0f}원 — 3년 밴드 {fx_pct:.0%} (비싼 구간)")

    # ⑥ 배당락 회복력 (10) — 배당락일에 배당금보다 덜 떨어질수록 좋다.
    # 남은 일수로 점수를 매기면 "기다리면 점수가 오르는" 이상한 지표가 된다.
    ex_sub = ""
    if inp.exdrop_ratio is None or inp.exdrop_samples < 3:
        ex_pt = W_EX * 0.5
        ex_label = "표본 부족"
        missing.append("배당락 하락폭 표본 부족 — 중립 처리")
    else:
        ratio = inp.exdrop_ratio
        # 실측 분포가 0.6~1.5배에 몰린다(SCHD 1.05, HDV 0.62, QQQ 1.45).
        # 0.5 이하 만점 / 1.5 이상 0점으로 잡아야 종목 간 변별이 생긴다.
        ex_pt = W_EX * max(0.0, min(1.0, (1.5 - ratio) / 1.0))
        ex_label = f"{ratio:.2f}배"
        if ratio < 0.8:
            ex_sub = "배당금보다 덜 떨어짐"
        elif ratio <= 1.2:
            ex_sub = "배당금만큼 떨어짐"
        else:
            ex_sub = "배당금보다 더 떨어짐"
            warnings.append(
                f"배당락일에 배당금의 {ratio:.1f}배만큼 떨어집니다 — "
                "배당을 노린 매물이 몰려 받은 배당 이상으로 주가가 밀립니다")
        if inp.exdrop_recovery is not None:
            ex_sub += f" · 회복 {inp.exdrop_recovery:g}일"
        if inp.exdrop_unrecovered:
            ex_sub += f" · 미회복 {inp.exdrop_unrecovered}회"
        if inp.exdrop_gap is not None and inp.exdrop_gap > 0.1:
            ex_sub += f" · 장중 {inp.exdrop_gap:+.1f}% 되돌림"
            warnings.append(
                f"배당락일에 배당금의 {ratio:.1f}배만큼 떨어집니다 — "
                "배당을 노린 매물이 몰려 받은 배당 이상으로 주가가 밀립니다")
        reasons.append(f"배당락 낙폭 {ratio:.2f}배 ({ex_sub})")
    if inp.days_to_ex is not None:
        ex_sub += f" · 다음 배당락 {inp.days_to_ex}일 뒤"
    ex_sub = ex_sub.lstrip(" ·")

    # 항목별 (라벨, 값, 부연, 획득점수, 만점).
    # 점수가 다 나온 뒤 한 번에 조립한다. 계산 중간에 담으면
    # 아직 값이 없는 변수를 참조하게 된다.
    facts = [
        ("배당률 수준", f"{cur_yield:.2f}%", level_note, round(level_pt, 1), 18),
        ("배당률 위치", f"{pct * 100:.0f}%" if pct is not None else "이력 부족",
         band or "판단 근거 부족", round(pos_pt, 1), 12),
        ("가격 위치",
         price_bits[0] if price_bits else "데이터 없음",
         " · ".join(price_bits[1:]) if len(price_bits) > 1 else "",
         round(price_pt, 1), W_PRICE),
        ("분배금 성장",
         inp.dps_label or (f"{growth:+.1%}" if inp.dps_ttm_prev else "이력 부족"),
         inp.dps_sub or "직전 1년 대비", round(dps_pt, 1), W_DPS),
        ("위험조정 수익",
         inp.risk_label or (f"{inp.total_return_1y_pct:+.1f}%"
                            if inp.total_return_1y_pct is not None else "데이터 없음"),
         inp.risk_sub or (f"1년 총수익 · 분배율 {cur_yield:.1f}%"
                          if inp.total_return_1y_pct is not None else ""),
         round(ret_pt, 1), W_RET),
        ("환율", fx_label, fx_sub, round(fx_pt, 1), W_FX),
        ("배당락 낙폭", ex_label, ex_sub, round(ex_pt, 1), W_EX),
    ]

    # ── 상품 품질과 매수 타점을 나눈다 ─────────────────────
    # "무엇을 살 것인가" 와 "언제 살 것인가" 는 다른 질문이다.
    # 하나로 합치면 좋은 상품이 비쌀 때도 높은 점수가 나와 판단이 흐려진다.
    #
    # 배당률은 오른 원인에 따라 갈린다. 배당이 늘어서 오른 몫은 상품 품질이고,
    # 주가가 빠져서 오른 몫은 매수 타점이다. 이걸 안 나누면 배당 성장 종목을
    # "지금 싸다" 고 잘못 읽는다.
    if inp.dps_ttm_prev and inp.dps_ttm_prev > 0:
        # 분배금이 10% 늘었으면 배당률 상승을 전부 성장으로 본다
        growth_share = max(0.0, min(1.0, growth / 0.10)) if growth > 0 else 0.0
    else:
        growth_share = 0.5      # 판단 근거가 없으면 절반씩

    # 배당률 절대 수준(18)은 상품 속성이라 전부 품질이다.
    # 이력 대비 위치(12)만 원인에 따라 나눈다.
    yield_q = level_pt + pos_pt * growth_share
    yield_t = pos_pt * (1 - growth_share)
    q_max = W_DPS + W_RET + W_EX + 18 + 12 * growth_share
    t_max = W_PRICE + W_FX + 12 * (1 - growth_share)

    quality = round((dps_pt + ret_pt + ex_pt + yield_q) / q_max * 100) if q_max else 0
    timing = round((price_pt + fx_pt + yield_t) / t_max * 100) if t_max else 0
    quality = max(0, min(100, quality))
    timing = max(0, min(100, timing))

    # 품질 6 : 타점 4. 나쁜 상품을 싸다는 이유로 사면 안 되므로 품질에 더 둔다.
    total = round(quality * 0.6 + timing * 0.4)
    total = max(0, min(100, total))

    # 품질 하한. 이 아래면 아무리 싸도 사지 않는다.
    excluded = quality < QUALITY_FLOOR

    # 데이터 신뢰도. 비어 있는 항목은 절반 점수를 자동으로 받는데,
    # 그걸 알리지 않으면 사용자는 그 숫자를 실제 분석 결과로 오해한다.
    # 항목이 6개이므로 하나 빌 때마다 신뢰도가 크게 떨어진다.
    confidence = max(0, 100 - len(missing) * 16)

    if confidence < 50:
        grade = "판단보류"
        warnings.insert(0, f"데이터 {len(missing)}개 항목이 비어 있어 점수를 "
                           "신뢰하기 어렵습니다 — 수집 상태를 확인하세요")
    elif excluded:
        grade = "제외"
        warnings.insert(0, f"상품 품질 {quality}점으로 기준({QUALITY_FLOOR}점) 미달입니다 — "
                           "가격이 싸도 매수 대상이 아닙니다")
    elif total >= GRADE_BUY_HARD:
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

    # 데이터가 없어 중립(50%)으로 처리한 항목이 많으면 점수를 믿기 어렵다.
    # 그 사실을 점수와 함께 드러내야 한다. 숨기면 빈 데이터가 평균 점수로 둔갑한다.
    TOTAL_ITEMS = 8
    confidence = max(0, round((1 - len(missing) / TOTAL_ITEMS) * 100))
    if len(missing) >= 3:
        warnings.append(
            f"데이터 {len(missing)}개 항목이 비어 중립 처리했습니다 "
            f"(신뢰도 {confidence}%) — 점수를 그대로 믿기 어렵습니다: "
            + ", ".join(m.split(" —")[0] for m in missing[:4]))

    return ScoreResult(
        ticker=inp.ticker, total=total, grade=grade,
        quality=quality, timing=timing, excluded=excluded,
        confidence=confidence, facts=facts,
        yield_pctile=round(yield_pt, 1), price_pos=round(price_pt, 1),
        dps_health=round(dps_pt, 1), total_ret=round(ret_pt, 1),
        fx_pos=round(fx_pt, 1), exdate_pen=round(ex_pt, 1),
        reason=" · ".join(reasons), warnings=warnings, missing=missing,
    )
