"""세금 엔진.

핵심 원칙: 세율 숫자를 이 파일에 쓰지 않는다. 전부 tax_param 테이블에서 읽는다.
세법이 바뀌면 SQL 한 줄로 끝나야 하기 때문이다.
(2026년 배당소득 분리과세 개정 논의가 진행 중이라 실제로 바뀔 가능성이 있다)

계좌 3모드:
  US_TAXABLE  일반계좌 + 미국상장 → 현지 15% 원천징수. 한국 14%보다 높아 통상 추가납부 없음
  KR_TAXABLE  일반계좌 + 국내상장 → 15.4% 원천징수 (매매차익도 배당소득으로 과세)
  KR_SHELTER  절세계좌(ISA/연금/IRP) → 분배금 즉시 과세 없음. 국내상장만 편입 가능
"""
from __future__ import annotations

from dataclasses import dataclass, field

US_TAXABLE = "US_TAXABLE"
KR_TAXABLE = "KR_TAXABLE"
KR_SHELTER = "KR_SHELTER"
MODES = (US_TAXABLE, KR_TAXABLE, KR_SHELTER)

# DB를 못 읽는 상황(테스트 등)에서만 쓰는 최후 기본값.
# 운영에서는 반드시 tax_param 을 로드해서 덮어쓴다.
FALLBACK = {
    "us_withholding": 0.15,
    "kr_dividend_tax": 0.154,
    "kr_capgain_overseas": 0.22,
    "overseas_deduction": 2_500_000,
    "fin_income_threshold": 20_000_000,
    "watchdog_ratio": 0.80,
}


@dataclass
class TaxResult:
    gross_krw: float          # 세전 배당 (원)
    tax_krw: float            # 세금
    net_krw: float            # 세후 수령액
    effective_rate: float     # 실효세율
    mode: str
    notes: list[str] = field(default_factory=list)


@dataclass
class TaxEngine:
    params: dict = field(default_factory=lambda: dict(FALLBACK))
    loaded_from_db: bool = False

    @classmethod
    def from_store(cls, store) -> "TaxEngine":
        """tax_param 테이블에서 세율을 읽어온다. 실패하면 FALLBACK + 경고."""
        engine = cls()
        if getattr(store, "dry_run", False):
            return engine
        try:
            conn = store.connect()
            with conn.cursor() as cur:
                cur.execute("SELECT key, value FROM tax_param")
                rows = cur.fetchall()
            if rows:
                engine.params.update({k: float(v) for k, v in rows})
                engine.loaded_from_db = True
        except Exception:                                     # noqa: BLE001
            pass
        return engine

    def _p(self, key: str) -> float:
        return float(self.params.get(key, FALLBACK[key]))

    # ---- 분배금 세금 ----
    def dividend_tax(self, gross_krw: float, mode: str,
                     ytd_financial_income_krw: float = 0.0) -> TaxResult:
        """배당(분배금)에 붙는 세금.

        gross_krw                  이번에 받는 세전 배당 (원)
        ytd_financial_income_krw   올해 이미 받은 금융소득 누적 (종합과세 판정용)
        """
        if mode not in MODES:
            raise ValueError(f"알 수 없는 계좌모드: {mode}")
        if gross_krw < 0:
            raise ValueError("세전 배당은 음수일 수 없습니다")

        notes: list[str] = []
        if not self.loaded_from_db:
            notes.append("세율을 DB에서 읽지 못해 기본값 사용 — tax_param 확인 필요")

        if mode == KR_SHELTER:
            notes.append("절세계좌는 분배금 즉시 과세 없음(과세이연). "
                         "연금 수령 시 3.3~5.5% 또는 ISA 비과세·9.9% 분리과세.")
            notes.append("절세계좌에는 국내상장 ETF만 편입 가능합니다.")
            return TaxResult(gross_krw, 0.0, gross_krw, 0.0, mode, notes)

        if mode == US_TAXABLE:
            rate = self._p("us_withholding")
            notes.append("미국 현지에서 15% 원천징수. 한국 배당소득세율(14%)보다 높아 "
                         "통상 추가 납부는 없습니다.")
            notes.append("지방소득세 1.4%분은 외국납부세액공제 처리에 따라 달라질 수 있습니다.")
        else:  # KR_TAXABLE
            rate = self._p("kr_dividend_tax")
            notes.append("국내 상장분은 15.4%(소득세 14% + 지방소득세 1.4%) 원천징수.")
            notes.append("국내 상장 해외ETF는 매매차익도 배당소득으로 과세됩니다.")

        tax = gross_krw * rate
        total_income = ytd_financial_income_krw + gross_krw
        threshold = self._p("fin_income_threshold")
        if total_income > threshold:
            notes.append(
                f"연 금융소득 누적 {total_income:,.0f}원이 종합과세 기준 "
                f"{threshold:,.0f}원을 넘습니다. 초과분은 다른 소득과 합산해 "
                "누진세율(6.6~49.5%)이 적용되므로 실제 부담은 위 계산보다 커질 수 있습니다.")
        elif total_income > threshold * self._p("watchdog_ratio"):
            notes.append(
                f"연 금융소득 누적 {total_income:,.0f}원 — 종합과세 기준의 "
                f"{total_income / threshold:.0%}에 도달했습니다.")

        return TaxResult(gross_krw, tax, gross_krw - tax,
                         tax / gross_krw if gross_krw else 0.0, mode, notes)

    def effective_rate(self, mode: str) -> float:
        """역산에 쓰는 단순 실효세율 (종합과세 전 구간)."""
        if mode == KR_SHELTER:
            return 0.0
        return self._p("us_withholding") if mode == US_TAXABLE else self._p("kr_dividend_tax")

    # ---- 매매차익 ----
    def capital_gain_tax(self, gain_krw: float, mode: str,
                         ytd_gain_krw: float = 0.0) -> TaxResult:
        notes: list[str] = []
        if mode == KR_SHELTER:
            notes.append("절세계좌는 매매차익도 과세이연됩니다.")
            return TaxResult(gain_krw, 0.0, gain_krw, 0.0, mode, notes)

        if mode == US_TAXABLE:
            deduction = self._p("overseas_deduction")
            remaining = max(0.0, deduction - ytd_gain_krw)
            taxable = max(0.0, gain_krw - remaining)
            tax = taxable * self._p("kr_capgain_overseas")
            notes.append(f"해외상장 양도소득세 22%, 연 기본공제 {deduction:,.0f}원 "
                         f"(올해 남은 공제 {remaining:,.0f}원). 분리과세라 종합과세에 합산되지 않습니다.")
        else:  # KR_TAXABLE
            tax = max(0.0, gain_krw) * self._p("kr_dividend_tax")
            notes.append("국내 상장 해외ETF의 매매차익은 배당소득으로 15.4% 과세되며, "
                         "금융소득 2,000만원 한도에 합산됩니다.")
            notes.append("2025년부터 외국납부세액 선환급 방식이 폐지되어 실효세율이 이전보다 높습니다.")

        return TaxResult(gain_krw, tax, gain_krw - tax,
                         tax / gain_krw if gain_krw else 0.0, mode, notes)
