"""배당 캘린더 엔진.

공휴일 테이블을 손으로 채우지 않는다. 이미 수집한 시세의 '거래가 있었던 날짜'가
곧 거래일이고, 평일 중 빠진 날이 휴장일이다. 실측으로 2026년 한국 휴장일
10일(설연휴·삼일절 대체·부처님오신날·지방선거일 등)이 정확히 도출되는 것을 확인했다.
별도 공휴일 데이터를 관리하면 매년 갱신 누락으로 틀리지만, 이 방식은 시세를
수집하는 한 저절로 맞는다.

미래 거래일은 관측 범위를 넘어가므로 주말만 제외하고 추정하며,
그렇게 만든 날짜는 전부 estimated 로 표시한다.

시장별 규칙이 다르다:
  US  ex-date 기준. ex-date 전일까지 매수해야 수령. 지급은 ex + 영업일 며칠 뒤.
  KR  지급기준일 기준. 분배락일 = 지급기준일 직전 영업일, 실제 지급은 익월 초.
      연휴가 끼면 분배락과 지급 사이가 최대 1주까지 벌어진다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

# 배당락 → 지급일 사이 영업일 수. 실제 공시가 없을 때만 쓰는 추정값.
PAY_LAG_BUSINESS_DAYS = {"US": 4, "KR": 12}


@dataclass
class TradingCalendar:
    """관측된 거래일 집합. market 별로 하나씩 만든다."""
    market: str
    days: list = field(default_factory=list)      # 정렬된 date 목록
    _set: set = field(default_factory=set, repr=False)

    @classmethod
    def from_dates(cls, market: str, dates: list) -> "TradingCalendar":
        clean = sorted({d for d in dates if d})
        return cls(market=market, days=clean, _set=set(clean))

    @property
    def last_observed(self):
        return self.days[-1] if self.days else None

    def is_trading_day(self, day: date) -> bool:
        """관측 범위 안이면 실제 거래 여부, 밖이면 주말만 제외한 추정."""
        if self.days and self.days[0] <= day <= self.days[-1]:
            return day in self._set
        return day.weekday() < 5

    def is_estimated(self, day: date) -> bool:
        return not self.days or day > self.days[-1]

    def add_business_days(self, start: date, n: int) -> date:
        """거래일 기준으로 n일 뒤. 휴장일은 건너뛴다."""
        day, moved = start, 0
        guard = 0
        while moved < n and guard < 400:
            day += timedelta(days=1)
            guard += 1
            if self.is_trading_day(day):
                moved += 1
        return day

    def prev_business_day(self, day: date) -> date:
        cur, guard = day - timedelta(days=1), 0
        while guard < 30 and not self.is_trading_day(cur):
            cur -= timedelta(days=1)
            guard += 1
        return cur

    def holidays_in(self, year: int) -> list:
        """관측 범위 안에서 평일인데 거래가 없던 날 = 휴장일."""
        if not self.days:
            return []
        out, day = [], max(self.days[0], date(year, 1, 1))
        end = min(self.days[-1], date(year, 12, 31))
        while day <= end:
            if day.weekday() < 5 and day not in self._set:
                out.append(day)
            day += timedelta(days=1)
        return out


@dataclass
class PredictedPayout:
    ticker: str
    ex_date: date
    pay_date: date
    dps: float
    confirmed: bool               # 실제 공시된 분배금인지
    ex_estimated: bool            # 배당락일이 추정인지
    pay_estimated: bool           # 지급일이 추정인지
    basis: str                    # 추정 근거 한 줄


def _median_interval(dates: list) -> float | None:
    if len(dates) < 3:
        return None
    recent = sorted(dates)[-13:]
    gaps = [(recent[i + 1] - recent[i]).days for i in range(len(recent) - 1)]
    return statistics.median(gaps) if gaps else None


def _trend_dps(amounts: list) -> float:
    """다음 분배금 추정. 최근 값들의 평균에 추세를 살짝 반영한다.

    커버드콜은 분배금 변동이 크므로 추세를 과하게 밀지 않는다 —
    최근 4회 평균을 기준으로 두고 앞뒤 6개월 평균의 차이만 절반 반영.
    """
    if not amounts:
        return 0.0
    recent = amounts[-4:]
    base = sum(recent) / len(recent)
    if len(amounts) >= 8:
        older = amounts[-8:-4]
        drift = (base - sum(older) / len(older)) * 0.5
        return max(0.0, base + drift)
    return base


def _add_months(anchor: date, months: int, day_of_month: int) -> date:
    """달력 월 단위로 이동. 말일이 없는 달은 그 달의 마지막 날로 맞춘다."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    last_day = (date(year + (month // 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day_of_month, last_day))


def _month_step(interval_days: float) -> int | None:
    """지급 간격을 달 수로 환산. 월/분기/반기/연만 인정한다."""
    for months, days in ((1, 30.4), (3, 91.3), (6, 182.6), (12, 365.0)):
        if abs(interval_days - days) <= days * 0.15:
            return months
    return None


def _trading_day_in_month(target: date, calendar: TradingCalendar) -> date:
    """휴장일이면 **같은 달 안에서** 가장 가까운 거래일로 옮긴다.

    달을 넘겨 버리면 어떤 달은 지급 0건, 어떤 달은 2건이 되어 일지가 틀어진다.
    앞으로 당기는 걸 우선하되, 그러면 이전 달로 넘어가는 경우(월초 지급)만
    뒤로 미룬다.
    """
    if calendar.is_trading_day(target):
        return target
    back = calendar.prev_business_day(target)
    if back.month == target.month and back.year == target.year:
        return back
    forward = calendar.add_business_days(target - timedelta(days=1), 1)
    return forward


def predict_schedule(ticker: str, market: str, history: list,
                     calendar: TradingCalendar, months: int = 12,
                     today: date | None = None) -> list[PredictedPayout]:
    """과거 배당 이력에서 앞으로 months 개월의 지급 일정을 만든다.

    history: [(ex_date, dps, pay_date|None), ...]  ex_date 오름차순
    """
    today = today or date.today()
    horizon = today + timedelta(days=int(months * 30.5))
    out: list[PredictedPayout] = []

    # 이미 공시된 미래 배당은 그대로 확정 처리
    for ex_date, dps, pay_date in history:
        if ex_date > today:
            resolved = pay_date or calendar.add_business_days(
                ex_date, PAY_LAG_BUSINESS_DAYS.get(market, 5))
            out.append(PredictedPayout(
                ticker, ex_date, resolved, float(dps), True, False,
                pay_date is None, "공시된 배당락일"))

    past = [(d, float(a)) for d, a, _ in history if d <= today]
    if not past:
        return out

    interval = _median_interval([d for d, _ in past])
    if interval is None:
        return out

    amounts = [a for _, a in past]
    estimate = round(_trend_dps(amounts), 6)
    anchor = max([p.ex_date for p in out] + [past[-1][0]])

    # 월배당을 30일 간격으로 더하면 1년에 약 5일씩 앞당겨져, 결국 한 달에
    # 두 번 잡히는 가짜 일정이 생긴다. 달력 월 단위로 옮겨야 실제와 맞는다.
    step_months = _month_step(interval)
    day_of_month = anchor.day
    basis = (f"과거 {len(past)}회 이력, "
             + (f"{step_months}개월 주기" if step_months else f"평균 간격 {interval:.0f}일")
             + ", 최근 4회 평균 기준 추정")

    cursor = anchor
    # 지급일 커서. 확정 공시분이 있으면 그 마지막 지급일에서 이어받는다.
    # 이어받지 않으면 확정분과 추정분의 이음매에서 한 달에 두 번 잡힌다.
    confirmed_pays = sorted(p.pay_date for p in out)
    pay_cursor = confirmed_pays[-1] if confirmed_pays else None
    guard = 0
    while guard < 40:
        guard += 1
        cursor = (_add_months(cursor, step_months, day_of_month) if step_months
                  else cursor + timedelta(days=round(interval)))
        if cursor > horizon:
            break
        # 배당락일이 휴장일이면 직전 거래일로 당긴다
        ex_date = cursor if calendar.is_trading_day(cursor) else calendar.prev_business_day(cursor)

        if step_months and pay_cursor is not None:
            # 지급일도 달력 월 단위로 옮긴다. 영업일 가산만 쓰면 2월처럼 짧은 달에서
            # 지급이 다음 달로 넘어가 어떤 달은 0건, 어떤 달은 2건이 된다.
            pay_cursor = _trading_day_in_month(
                _add_months(pay_cursor, step_months, pay_cursor.day), calendar)
            # 지급일이 배당락일보다 앞설 수는 없다. 월 단위로 옮기다 보면
            # 배당락이 뒤로 밀린 달에 역전이 생길 수 있어 최소 1영업일 뒤로 민다.
            if pay_cursor <= ex_date:
                pay_cursor = calendar.add_business_days(ex_date, 1)
            pay_date = pay_cursor
        else:
            pay_date = calendar.add_business_days(
                ex_date, PAY_LAG_BUSINESS_DAYS.get(market, 5))
            pay_cursor = pay_date

        out.append(PredictedPayout(
            ticker, ex_date, pay_date, estimate, False,
            calendar.is_estimated(ex_date), True, basis))

    return sorted(out, key=lambda p: p.ex_date)


def next_ex_date(ticker: str, market: str, history: list,
                 calendar: TradingCalendar, today: date | None = None):
    """다음 배당락일과 그것이 확정인지 추정인지.

    스코어의 배당락 항목이 이 값을 쓴다. 추정이면 화면에서 그렇게 표시해야 한다.
    """
    today = today or date.today()
    upcoming = [p for p in predict_schedule(ticker, market, history, calendar, 6, today)
                if p.ex_date > today]
    if not upcoming:
        return None, None, None
    first = upcoming[0]
    return first.ex_date, (first.ex_date - today).days, first.confirmed


def monthly_ledger(payouts: list, qty_map: dict, keep_rate: float,
                   fx: float, currency_map: dict,
                   today: date | None = None) -> list[dict]:
    """배당예상일지 — 앞으로 12개월 월별 입금 예정.

    지급일(pay_date) 기준으로 모은다. 배당락일이 아니라 실제 돈이 들어오는 날이다.
    """
    today = today or date.today()
    buckets: dict = {}
    for p in payouts:
        qty = qty_map.get(p.ticker, 0)
        if qty <= 0 or p.pay_date < today:
            continue
        rate = fx if currency_map.get(p.ticker, "USD") == "USD" else 1.0
        gross = p.dps * qty * rate
        key = (p.pay_date.year, p.pay_date.month)
        slot = buckets.setdefault(key, {
            "year": key[0], "month": key[1],
            "gross_krw": 0.0, "net_krw": 0.0, "items": [],
            "all_confirmed": True,
        })
        slot["gross_krw"] += gross
        slot["net_krw"] += gross * keep_rate
        slot["items"].append({
            "ticker": p.ticker, "pay_date": p.pay_date.isoformat(),
            "ex_date": p.ex_date.isoformat(),
            "net_krw": round(gross * keep_rate),
            "confirmed": p.confirmed, "basis": p.basis,
        })
        if not p.confirmed:
            slot["all_confirmed"] = False

    rows = sorted(buckets.values(), key=lambda r: (r["year"], r["month"]))
    for row in rows:
        row["gross_krw"] = round(row["gross_krw"])
        row["net_krw"] = round(row["net_krw"])
        row["items"].sort(key=lambda i: i["pay_date"])
    return rows[:12]
