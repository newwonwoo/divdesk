"""배당 계산 엔진 — 정방향 / 역방향.

정방향: 이만큼 사면 세후 월배당이 얼마인가
역방향: 월 얼마를 받으려면 얼마를 사야 하는가

주의해서 다룬 지점 두 가지:
 1) "월평균"과 "실제 월입금"은 다르다. 분기배당 종목은 3·6·9·12월에만 들어온다.
    그래서 monthly_avg 와 함께 monthly_breakdown(12칸)을 항상 같이 돌려준다.
 2) 역방향은 한 번에 안 끝난다. 주식은 정수로만 사지므로 내림하면 목표에 미달한다.
    부족분을 다시 배분하는 루프를 돈다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .tax import TaxEngine

# 배분 모드
ALLOC_EQUAL = "equal"        # 균등 금액
ALLOC_YIELD = "yield"        # 배당률 높은 순 가중
ALLOC_CUSTOM = "custom"      # 사용자 지정 비중


@dataclass
class Holding:
    """계산 입력 1건. 수집된 값만 넣는다 — 여기서 추정하지 않는다."""
    ticker: str
    price: float                  # 현재가 (미국: USD, 국내: KRW)
    ttm_dps: float                # 최근 1년 분배금 합계 (지급횟수 기준으로 잘린 값)
    pays_per_year: int
    currency: str = "USD"
    pay_months: list[int] = field(default_factory=list)   # 비면 주기로 추정
    qty: float = 0.0
    is_covered_call: bool = False
    name: str = ""

    @property
    def yield_pct(self) -> float:
        return (self.ttm_dps / self.price * 100) if self.price else 0.0

    def months(self) -> list[int]:
        """실제 입금 월. 데이터가 있으면 그걸 쓰고, 없으면 주기로 추정한다."""
        if self.pay_months:
            return sorted(self.pay_months)
        if self.pays_per_year == 12:
            return list(range(1, 13))
        if self.pays_per_year == 4:
            return [3, 6, 9, 12]
        if self.pays_per_year == 2:
            return [6, 12]
        return [12]


@dataclass
class ForwardResult:
    invested_krw: float
    annual_gross_krw: float
    annual_tax_krw: float
    annual_net_krw: float
    monthly_avg_net_krw: float
    monthly_breakdown: list[float]        # 12칸, 세후 원화
    weighted_yield_pct: float
    per_ticker: list[dict]
    notes: list[str] = field(default_factory=list)


def _to_krw(amount: float, currency: str, fx: float) -> float:
    return amount * fx if currency == "USD" else amount


def forward(holdings: list[Holding], fx: float, mode: str,
            tax: TaxEngine, ytd_income_krw: float = 0.0) -> ForwardResult:
    """보유(또는 매수 예정) 종목으로 세후 배당을 계산한다."""
    if fx <= 0:
        raise ValueError("환율은 0보다 커야 합니다")

    invested = 0.0
    annual_gross = 0.0
    monthly_gross = [0.0] * 12
    rows: list[dict] = []
    warn_cc = False

    for h in holdings:
        if h.qty <= 0:
            continue
        cost = _to_krw(h.price * h.qty, h.currency, fx)
        gross = _to_krw(h.ttm_dps * h.qty, h.currency, fx)
        invested += cost
        annual_gross += gross

        pay_months = h.months()
        if pay_months:
            per_pay = gross / len(pay_months)
            for m in pay_months:
                monthly_gross[m - 1] += per_pay

        warn_cc = warn_cc or h.is_covered_call
        rows.append({
            "ticker": h.ticker, "name": h.name, "qty": h.qty,
            "cost_krw": round(cost), "annual_gross_krw": round(gross),
            "yield_pct": round(h.yield_pct, 2),
            "is_covered_call": h.is_covered_call,
        })

    result = tax.dividend_tax(annual_gross, mode, ytd_income_krw)
    keep = 1 - result.effective_rate
    monthly_net = [round(v * keep) for v in monthly_gross]

    notes = list(result.notes)
    active = [m for m in monthly_net if m > 0]
    if active and len(active) < 12:
        notes.append(f"실제 입금은 12개월 중 {len(active)}개월에만 발생합니다. "
                     "월평균과 이번 달 실입금은 다릅니다.")
    if warn_cc:
        notes.append("커버드콜 종목이 포함돼 있습니다. 분배금 일부는 옵션 프리미엄·"
                     "원금환급일 수 있어 분배금이 곧 수익은 아닙니다.")

    return ForwardResult(
        invested_krw=round(invested),
        annual_gross_krw=round(annual_gross),
        annual_tax_krw=round(result.tax_krw),
        annual_net_krw=round(result.net_krw),
        monthly_avg_net_krw=round(result.net_krw / 12),
        monthly_breakdown=monthly_net,
        weighted_yield_pct=round(annual_gross / invested * 100, 2) if invested else 0.0,
        per_ticker=rows,
        notes=notes,
    )


@dataclass
class ReverseResult:
    target_monthly_krw: float
    required_krw: float
    achieved_monthly_krw: float
    achieved_pct: float
    plan: list[dict]
    forward: ForwardResult
    notes: list[str] = field(default_factory=list)


def _weights(holdings: list[Holding], alloc: str,
             custom: dict | None) -> list[float]:
    n = len(holdings)
    if alloc == ALLOC_CUSTOM:
        if not custom:
            raise ValueError("custom 배분은 비중 딕셔너리가 필요합니다")
        raw = [max(0.0, float(custom.get(h.ticker, 0))) for h in holdings]
    elif alloc == ALLOC_YIELD:
        raw = [max(0.0, h.yield_pct) for h in holdings]
    else:
        raw = [1.0] * n
    total = sum(raw)
    if total <= 0:
        raise ValueError("배분 비중의 합이 0입니다")
    return [v / total for v in raw]


def reverse(target_monthly_krw: float, holdings: list[Holding], fx: float,
            mode: str, tax: TaxEngine, alloc: str = ALLOC_EQUAL,
            custom: dict | None = None, ytd_income_krw: float = 0.0,
            max_rounds: int = 40) -> ReverseResult:
    """목표 월배당(세후)을 맞추는 데 필요한 금액과 종목별 주수를 구한다.

    주식은 소수점으로 못 사니까 내림하면 반드시 목표에 미달한다.
    그래서 '내림 → 부족분 계산 → 가장 효율 좋은 종목 1주 추가'를 반복한다.
    """
    if target_monthly_krw <= 0:
        raise ValueError("목표 월배당은 0보다 커야 합니다")
    live = [h for h in holdings if h.price > 0 and h.ttm_dps > 0]
    if not live:
        raise ValueError("가격·분배금 데이터가 있는 종목이 없습니다")

    keep = 1 - tax.effective_rate(mode)
    if keep <= 0:
        raise ValueError("실효세율이 100%로 계산되었습니다 — tax_param 확인 필요")

    # 1차 추정: 세후 목표 → 세전 필요 연배당 → 가중배당률로 나눠 금액
    need_gross_annual = target_monthly_krw * 12 / keep
    weights = _weights(live, alloc, custom)
    blended = sum(w * (h.ttm_dps / h.price) for w, h in zip(weights, live))
    if blended <= 0:
        raise ValueError("가중 배당률이 0입니다")
    budget = need_gross_annual / blended

    # 2차: 정수 주수로 내림
    for h, w in zip(live, weights):
        unit = _to_krw(h.price, h.currency, fx)
        h.qty = float(int(budget * w / unit)) if unit > 0 else 0.0

    # 3차: 부족분 채우기. '1주 더 살 때 늘어나는 배당 ÷ 비용'이 큰 종목부터.
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        current = forward(live, fx, mode, tax, ytd_income_krw)
        if current.monthly_avg_net_krw >= target_monthly_krw:
            break
        best, best_eff = None, 0.0
        for h in live:
            unit = _to_krw(h.price, h.currency, fx)
            if unit <= 0:
                continue
            eff = _to_krw(h.ttm_dps, h.currency, fx) / unit
            if eff > best_eff:
                best, best_eff = h, eff
        if best is None:
            break
        gap = target_monthly_krw - current.monthly_avg_net_krw
        unit = _to_krw(best.price, best.currency, fx)
        per_share_monthly = _to_krw(best.ttm_dps, best.currency, fx) * keep / 12
        add = max(1, int(gap / per_share_monthly)) if per_share_monthly > 0 else 1
        best.qty += add

    final = forward(live, fx, mode, tax, ytd_income_krw)
    plan = [{
        "ticker": h.ticker, "name": h.name, "qty": int(h.qty),
        "price": h.price, "currency": h.currency,
        "cost_krw": round(_to_krw(h.price * h.qty, h.currency, fx)),
    } for h in live if h.qty > 0]

    notes = list(final.notes)
    if rounds >= max_rounds:
        notes.append("주수 조정이 한도에 걸렸습니다. 목표가 너무 크거나 "
                     "종목 조합이 목표에 맞지 않을 수 있습니다.")
    notes.append("주수는 정수로만 계산했습니다. 실제 체결가·수수료·환전 스프레드는 반영하지 않았습니다.")

    return ReverseResult(
        target_monthly_krw=round(target_monthly_krw),
        required_krw=final.invested_krw,
        achieved_monthly_krw=final.monthly_avg_net_krw,
        achieved_pct=round(final.monthly_avg_net_krw / target_monthly_krw * 100, 1),
        plan=plan, forward=final, notes=notes,
    )
