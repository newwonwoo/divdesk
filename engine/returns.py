"""보유 종목 총수익 계산.

배당만 보면 반쪽이다. 실제 손익은 셋의 합이다:
    총수익 = 배당수익 + 시세차익 + 환차익

원화 투자자에게 환차익은 선택이 아니라 필수 항목이다. 1,300원에 사서 1,430원인
지금은 주가가 그대로여도 원화로는 10% 이익이고, 반대면 손실이다.
그래서 달러 손익과 원화 손익을 나눠 보여준다.

세금 처리가 배당과 다르다:
  US_TAXABLE  양도세 22%, 연 250만원 기본공제, 분리과세 (금융소득 합산 안 됨)
  KR_TAXABLE  매매차익도 배당소득으로 15.4%, 금융소득 2,000만원 한도에 합산
  KR_SHELTER  과세이연

**미실현 손익에는 세금이 붙지 않는다.** 팔아야 낸다. 그래서 세전 평가손익과
"지금 전부 판다면" 예상 세금을 나눠 표시한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .tax import KR_SHELTER, US_TAXABLE, TaxEngine


@dataclass
class Lot:
    """매수 1건. 매수기록 한 행에 해당한다."""
    ticker: str
    qty: float
    price: float                  # 매수 단가 (현지 통화)
    fx_at_buy: float | None       # 매수 시점 환율. 국내상장이면 None
    fee: float = 0.0
    currency: str = "USD"
    name: str = ""
    is_opening: bool = False      # 증권사 API 이전의 보유분


@dataclass
class PositionReturn:
    ticker: str
    name: str
    qty: float
    avg_price: float
    current_price: float
    cost_krw: float               # 원화 투자원금 (매수 시점 환율 적용)
    value_krw: float              # 현재 원화 평가액
    price_gain_krw: float         # 순수 시세차익 (환율 고정 가정)
    fx_gain_krw: float            # 환차익 (매수일을 아는 물량에서만)
    dividend_krw: float           # 보유 후 받은 배당 (세전)
    total_gain_krw: float
    return_pct: float
    opening_qty: float = 0.0      # 매수 이력이 없는 보유분
    currency: str = "USD"
    notes: list[str] = field(default_factory=list)


@dataclass
class PortfolioReturn:
    cost_krw: float
    value_krw: float
    price_gain_krw: float
    fx_gain_krw: float
    dividend_gross_krw: float
    dividend_tax_krw: float
    dividend_net_krw: float
    unrealized_gain_krw: float          # 시세 + 환 (세전)
    estimated_capgain_tax_krw: float    # 지금 전부 판다면
    total_return_krw: float             # 배당세후 + 미실현(세전)
    total_return_pct: float
    positions: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _krw(amount: float, currency: str, fx: float) -> float:
    return amount * fx if currency == "USD" else amount


def position_return(lots: list[Lot], current_price: float, fx_now: float,
                    dividends_since: float = 0.0) -> PositionReturn:
    """한 종목의 손익. 여러 번 나눠 샀으면 매수건별 환율을 각각 적용한다.

    평균 환율을 쓰면 안 된다 — 1,300원에 절반, 1,500원에 절반 샀다면
    각 건의 원가가 다르고, 그 차이가 곧 환차익이다.
    """
    if not lots:
        raise ValueError("매수기록이 없습니다")

    ticker = lots[0].ticker
    currency = lots[0].currency
    total_qty = sum(lot.qty for lot in lots)
    if total_qty <= 0:
        raise ValueError(f"{ticker}: 보유 수량이 0입니다")

    cost_krw = 0.0
    cost_local = 0.0
    # 매수일을 아는 물량만 따로 센다. 환차익은 이 부분에서만 계산한다.
    known_qty = 0.0
    known_cost_local = 0.0
    known_cost_krw = 0.0
    opening_qty = 0.0
    notes: list[str] = []

    for lot in lots:
        local = lot.qty * lot.price + lot.fee
        cost_local += local
        if lot.is_opening:
            # 증권사 API 이전 보유분. 언제 샀는지 모르므로 환율을 추정하지 않는다.
            opening_qty += lot.qty
            cost_krw += local * (lot.fx_at_buy or fx_now)
            continue
        rate = 1.0 if currency == "KRW" else (lot.fx_at_buy or fx_now)
        if currency == "USD" and not lot.fx_at_buy:
            notes.append("매수 시점 환율이 없는 건이 있어 현재 환율로 대체했습니다 "
                         "— 환차익이 실제보다 작게 나옵니다")
        cost_krw += local * rate
        known_qty += lot.qty
        known_cost_local += local
        known_cost_krw += local * rate

    avg_price = cost_local / total_qty
    value_local = total_qty * current_price
    value_krw = _krw(value_local, currency, fx_now)

    # 시세차익은 전량 기준, 환차익은 매수일을 아는 물량에서만 낸다.
    # 모르는 물량에 현재 환율을 끼워 넣으면 환차익이 0에 수렴해 실제를 흐린다.
    if currency == "KRW" or known_qty <= 0:
        avg_fx = (cost_krw / cost_local) if cost_local else 1.0
        price_gain_krw = (value_local - cost_local) * avg_fx
        fx_gain_krw = 0.0 if currency == "KRW" else (value_krw - cost_krw) - price_gain_krw
    else:
        known_avg_fx = known_cost_krw / known_cost_local if known_cost_local else fx_now
        # 아는 물량 몫의 평가액·원가로만 환차익을 낸다
        known_value_local = known_qty * current_price
        known_value_krw = known_value_local * fx_now
        known_price_gain = (known_value_local - known_cost_local) * known_avg_fx
        fx_gain_krw = (known_value_krw - known_cost_krw) - known_price_gain
        # 시세차익은 전량 기준 (원가 전체를 알고 있으므로 계산 가능)
        price_gain_krw = (value_krw - cost_krw) - fx_gain_krw

    if opening_qty > 0:
        notes.append(f"이 중 {opening_qty:,.4f}주는 증권사가 매수 이력을 주지 않는 "
                     "과거 보유분입니다. 수량·원가는 반영했지만 매수 시점을 알 수 없어 "
                     "환차익 계산에서는 제외했습니다.")

    total_gain = price_gain_krw + fx_gain_krw + dividends_since
    return PositionReturn(
        ticker=ticker, name=lots[0].name, qty=total_qty,
        avg_price=round(avg_price, 4), current_price=current_price,
        cost_krw=round(cost_krw), value_krw=round(value_krw),
        price_gain_krw=round(price_gain_krw), fx_gain_krw=round(fx_gain_krw),
        opening_qty=round(opening_qty, 6),
        dividend_krw=round(dividends_since), total_gain_krw=round(total_gain),
        return_pct=round(total_gain / cost_krw * 100, 2) if cost_krw else 0.0,
        currency=currency, notes=list(dict.fromkeys(notes)),
    )


def portfolio_return(positions: list, mode: str, tax: TaxEngine,
                     ytd_income_krw: float = 0.0,
                     ytd_capgain_krw: float = 0.0) -> PortfolioReturn:
    """포트폴리오 전체 손익과 세금."""
    cost = sum(p.cost_krw for p in positions)
    value = sum(p.value_krw for p in positions)
    price_gain = sum(p.price_gain_krw for p in positions)
    fx_gain = sum(p.fx_gain_krw for p in positions)
    dividend = sum(p.dividend_krw for p in positions)

    div_tax = tax.dividend_tax(dividend, mode, ytd_income_krw)
    unrealized = price_gain + fx_gain
    cap_tax = tax.capital_gain_tax(max(0.0, unrealized), mode, ytd_capgain_krw)

    total = div_tax.net_krw + unrealized
    notes = list(div_tax.notes)
    notes.append("시세차익·환차익은 아직 팔지 않은 평가손익이라 세금이 붙지 않았습니다. "
                 "아래 예상 세금은 지금 전부 매도한다고 가정한 값입니다.")
    if mode == US_TAXABLE:
        notes += cap_tax.notes
    elif mode == KR_SHELTER:
        notes.append("절세계좌는 매도해도 즉시 과세되지 않고 인출 시점에 정산됩니다.")
    else:
        notes += cap_tax.notes

    if fx_gain and abs(fx_gain) > abs(price_gain) * 0.5:
        direction = "이익" if fx_gain > 0 else "손실"
        notes.append(f"손익의 상당 부분이 환율에서 나왔습니다(환차{direction} "
                     f"{abs(fx_gain):,.0f}원). 종목 자체의 성과와 구분해서 보세요.")

    return PortfolioReturn(
        cost_krw=round(cost), value_krw=round(value),
        price_gain_krw=round(price_gain), fx_gain_krw=round(fx_gain),
        dividend_gross_krw=round(dividend),
        dividend_tax_krw=round(div_tax.tax_krw),
        dividend_net_krw=round(div_tax.net_krw),
        unrealized_gain_krw=round(unrealized),
        estimated_capgain_tax_krw=round(cap_tax.tax_krw),
        total_return_krw=round(total),
        total_return_pct=round(total / cost * 100, 2) if cost else 0.0,
        positions=positions, notes=notes,
    )
