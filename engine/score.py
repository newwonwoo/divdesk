"""매수타점 스코어 엔진 (0~100).

설계 의도: "배당률이 높으면 좋다"가 아니라 "이 종목의 과거 자기 배당률 대비
지금이 싼가"를 본다. 그래서 절대 배당률이 아니라 5년 밴드 내 백분위를 쓴다.
QYLD 같은 초고배당이 낮은 점수를 받는 게 정상이다.

두 축으로 나눈다.
  품질 = 안정성      이 상품이 꾸준한가 (분배금 성장·위험조정 수익·배당락 회복력)
  타점 = 얼마나 싼가  지금 싸게 사는가 (고점 대비 낙폭·환율·주가하락분 배당률)

배점: 배당률 30(수준 18 + 위치 12) / 가격 위치 20 / 분배금 15
      / 위험조정 수익 15 / 환율 10 / 배당락 회복력 10
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

W_YIELD, W_PRICE, W_DPS, W_RET, W_FX, W_EX = 30, 20, 15, 15, 10, 10

# 종합 = 품질 × 0.75 + 타점 × 0.25.
#
# 예전에는 6:4 였다. 백테스트에서 타점 축이 검증에 실패해 비중을 낮췄다.
# 가격 위치는 이후 수익과 상관이 -0.05 로 사실상 무관했고, 분해해 보니
# 신호가 전부 2020년 급락·회복이라는 사건 하나에서 나왔다(2022년 이후 ≈ 0).
# 환율은 이력이 2021-08 부터라 검증 자체가 불가능했다.
# 검증되지 않은 축에 40% 를 걸 수 없어 25% 로 낮춘다. 0 으로 두지 않는 이유는
# "지금이 살 때인가" 가 이 앱의 두 질문 중 하나이기 때문이다.
W_QUALITY, W_TIMING = 0.75, 0.25
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
    # 지금 낙폭이 이 종목 과거 낙폭 분포에서 어느 위치인가 (1.0 = 역대 최악).
    # 절대 기준(-10%)만 쓰면 종목별 변동성 차이가 점수 차이로 둔갑한다 —
    # DIV 의 관측 최대낙폭은 -54%, 국내 신규 상장은 -14% 다.
    dd_pctile: float | None = None
    is_covered_call: bool = False
    is_krw_listed: bool = False            # 원화 상장 여부 (구버전 호환)
    # 상장 통화가 아니라 **기초자산 통화**를 본다.
    # TIGER 미국배당다우존스는 원화 상장이지만 기초자산이 미국이라
    # 환율에 그대로 노출된다. 상장 통화로 판단하면 이걸 놓친다.
    #
    # 예전에는 이 필드가 두 번 선언돼 있었다(`bool | None = None` 과
    # `bool = True`). 파이썬은 뒤엣것만 남기므로 실제 기본값은 True 였고,
    # 앞 선언을 전제로 쓴 `is not None` 분기는 도달할 수 없었다.
    # 기본값(True)은 그대로 두고 선언만 하나로 합친다 — None 을 명시적으로
    # 넘기면 상장 통화로 되짚는 분기가 다시 살아난다.
    fx_exposed: bool | None = True         # 기초자산이 해외라 환율에 노출되는가
    fx_hedged: bool = False                # 환헤지 상품인가


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

    # ② 가격 위치 (20) — "얼마나 싸게 사는가" 하나만 본다.
    #
    # 예전에는 추세 8 + 낙폭 6 + 과열 6 이었다. 백테스트로 분해해 보니
    # 세 요소의 방향이 서로 달랐다(2017~2026, 관측 2,372):
    #   200일선 기울기  23/23 종목에서 음(-). 어느 기간에서도 양(+)인 적 없음
    #   고점 낙폭       유일하게 방향 일관 (28/29 종목, +0.31)
    #   20일 과열       U자 비단조 — 선형 배점으로 담을 수 없다
    # 추세추종(기울기)과 역추세(낙폭)를 한 점수에 섞어 서로를 상쇄시켰고,
    # 부호가 틀린 쪽 가중치가 더 컸다(8 vs 6). 그래서 합계 상관이 -0.05,
    # 즉 예측력이 없었다. 신호가 없어서가 아니라 반대로 겹쳐 놓아서였다.
    #
    # 기울기는 **제거하되 뒤집지 않는다.** 최근 기간 상관이 0 이라 반대편에
    # 걸 근거가 없고, 뒤집으면 배당 삭감처럼 구조적으로 무너지는 종목에
    # 최고점을 주게 된다. 경고는 남겨 원래 의도(하락 추세 주의)를 지킨다.
    #
    # 골든크로스(MA50/200)도 검증했으나 넣지 않았다. 상태·이격은 기울기와
    # 같은 신호였고(이격 0/23 으로 수치까지 같다), 싼 구간에서 골든크로스가
    # 있는 쪽이 오히려 -3.6%p 낮았다 — 반등을 확인하고 사면 이미 늦는다.
    # '전환 직후' 만 부호가 반대가 아니었지만 상관 -0.002 로 아무것도 아니었다.
    price_pt, price_bits = 0.0, []

    if inp.drawdown is not None:
        # 절대 기준과 자기 이력 기준을 **둘 다** 만족해야 높은 점수를 준다.
        #
        # 절대 기준만 보면 -10% 상한에 자주 포화된다(짧은 이력 관측의 33%가
        # 만점). -10% 든 -30% 든 전부 1.0 이라 그 구간에서 변별이 사라진다.
        # 자기 이력만 보면 아직 위기를 겪지 않은 종목이 평범한 조정에 만점을
        # 받는다. 둘 중 낮은 쪽을 쓰면 서로의 실패를 막는다.
        abs_pos = max(0.0, min(1.0, -inp.drawdown / 0.10))
        if inp.dd_pctile is None:
            pos = abs_pos
            hist_note = "자기 이력 부족 — 절대 기준만 적용"
        else:
            pos = min(abs_pos, max(0.0, min(1.0, inp.dd_pctile)))
            # 사람이 읽는 표기는 '순위' 로 한다. '상위 15%' 같은 백분율은
            # 방향을 헷갈리게 한다(85% 가 심한 건지 평범한 건지 즉시 안 읽힌다).
            # dd_pctile 은 '과거 중 지금보다 덜 빠진 비율' 이므로
            # 순위 = (1 - dd_pctile) × 100. 1위가 역대 최악이다.
            rank = max(1, round((1 - inp.dd_pctile) * 100))
            hist_note = f"과거 낙폭 100건 중 {rank}번째로 큼"
        price_pt = W_PRICE * pos
        price_bits.append(f"고점 대비 {inp.drawdown:+.1%}")
        price_bits.append(hist_note)
    else:
        price_pt = W_PRICE * 0.5
        price_bits.append("데이터 없음")
        missing.append("고점 대비 낙폭 없음")

    # 아래 둘은 점수에 넣지 않는다. 검증에서 방향이 반대이거나(기울기)
    # 비단조였다(20일 과열). 다만 사용자가 알아야 할 사실이므로 경고로는 남긴다.
    if inp.ma200_slope is not None:
        trend = ("상승 추세" if inp.ma200_slope > 0.01
                 else "하락 추세" if inp.ma200_slope < -0.01 else "횡보")
        price_bits.append(f"200일선 {inp.ma200_slope:+.1%} ({trend}·점수 미반영)")
        if inp.ma200_slope < -0.02:
            warnings.append("200일선이 꺾여 하락 추세입니다 — 싸 보여도 더 빠질 수 있습니다")

    if inp.change_20d is not None:
        price_bits.append(f"최근 1개월 {inp.change_20d:+.1%} (점수 미반영)")
        if inp.change_20d > 0.10:
            warnings.append(
                f"최근 한 달에 {inp.change_20d:+.1%} 올랐습니다 — 단기 과열 구간입니다")

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
        # 장중 되돌림은 부연에만 적는다. 여기에 경고를 달면 안 된다 —
        # 낙폭 배수가 0.65배(=배당금보다 덜 떨어진 좋은 종목)여도 되돌림만
        # 있으면 "배당 이상으로 밀린다" 는 반대 뜻 경고가 붙었다.
        # 그 경고는 위 ratio > 1.2 분기 하나만 담당한다.
        if inp.exdrop_gap is not None and inp.exdrop_gap > 0.1:
            ex_sub += f" · 장중 {inp.exdrop_gap:+.1f}% 되돌림"
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

    # 품질 75 : 타점 25. 나쁜 상품을 싸다는 이유로 사면 안 되고,
    # 백테스트에서 타점 축이 검증에 실패해 비중을 더 낮췄다(위 W_QUALITY 주석).
    total = round(quality * W_QUALITY + timing * W_TIMING)
    total = max(0, min(100, total))

    # 품질 하한. 이 아래면 아무리 싸도 사지 않는다.
    excluded = quality < QUALITY_FLOOR

    # 데이터 신뢰도. 비어 있는 항목은 절반 점수를 자동으로 받는데,
    # 그걸 알리지 않으면 사용자는 그 숫자를 실제 분석 결과로 오해한다.
    #
    # 중립 처리될 수 있는 항목 수. 200일선 추세·20일 변동을 점수에서 빼면서
    # 8 → 6 으로 줄었다(배당률 이력 / 낙폭 / 분배금 / 위험조정 / 환율 / 배당락).
    #
    # 예전에는 여기서 `100 - len(missing)*16` 으로 한 번, 아래에서
    # `(1 - len(missing)/6)*100` 으로 또 한 번 계산했다. 등급 판정은 앞의 값을,
    # 화면 표시는 뒤의 값을 써서 둘이 어긋났다(결측 3개면 52 vs 50).
    # 결론이 갈리는 구간이 없어 증상은 없었지만 정본을 하나로 둔다.
    TOTAL_ITEMS = 6
    confidence = max(0, round((1 - len(missing) / TOTAL_ITEMS) * 100))

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
