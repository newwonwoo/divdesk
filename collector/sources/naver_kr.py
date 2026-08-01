"""국내 ETF 소스 (네이버 증권 비공식 JSON).

역할 변경(2026-08-01): 야후가 `종목코드.KS` 로 국내 ETF 시세·분배금을 모두 제공하는 것이
실측으로 확인되어, 국내 1순위 소스는 야후(run_kr.py)가 되었다.
이 파일은 선택적 2순위 교차검증용으로만 남는다. 없어도 앱은 돈다.

⚠️ 이 파일의 엔드포인트는 여전히 '미검증'이다.
클로드 샌드박스에서는 naver.com 이 이그레스 정책으로 막혀(hostname_blocked) 실측을 못 했다.
EC2에서 `python -m collector.probe_kr` 를 먼저 돌려 어떤 후보가 200을 주는지 확인하고,
살아있는 후보만 CANDIDATES에 남긴 뒤 파서 필드명을 확정한다.

확정 전까지 run_us.py 만 운영에 쓰고, 국내 종목은 '데이터 없음'으로 노출한다.
(추정값으로 채우지 않는다 — 이 앱의 원칙)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .base import Adapter, ContractError, Dividend, Quote, check_contract

# probe로 살아있는 것만 남길 후보 목록
CANDIDATES = {
    "etf_list": "https://finance.naver.com/api/sise/etfItemList.nhn"
                "?etfType=0&targetColumn=market_sum&sortOrder=desc",
    "basic": "https://m.stock.naver.com/api/stock/{code}/basic",
    "integration": "https://m.stock.naver.com/api/stock/{code}/integration",
    "price": "https://m.stock.naver.com/api/stock/{code}/price?pageSize=10&page=1",
    "chart_day": "https://fchart.stock.naver.com/siseJson.nhn?symbol={code}"
                 "&requestType=1&startTime={start}&endTime={end}&timeframe=day",
}

HDR = {"Referer": "https://finance.naver.com/"}


def _num(value) -> float:
    """'11,905' / '11905.0' / 11905 → float"""
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace(",", "").strip())


@dataclass
class NaverKrAdapter(Adapter):
    name: str = "naver_kr"
    market: str = "KR"
    priority: int = 60          # 야후(10)보다 뒤. 교차검증 전용
    min_interval: float = 1.5
    verified: bool = field(default=False)   # probe 통과 후 True 로 바꾼다

    def fetch_quote(self, ticker: str) -> Quote:
        if not self.verified:
            raise ContractError("naver_kr 미검증. probe_kr 먼저 실행해 필드명을 확정하세요.")
        body = self._get(CANDIDATES["basic"].format(code=ticker), headers=HDR).json()
        check_contract(body, ["closePrice", "localTradedAt"], "naver.basic")
        return Quote(
            ticker=ticker,
            close=_num(body["closePrice"]),
            asof=datetime.strptime(body["localTradedAt"][:10], "%Y-%m-%d").date(),
            nav=_num(body["nav"]) if body.get("nav") else None,
            src=self.name,
            currency="KRW",
        )

    def fetch_dividends(self, ticker: str, years: int = 6) -> list[Dividend]:
        """국내 분배금은 네이버 JSON에 안정적으로 없을 가능성이 높다.
        probe 결과에 따라 SEIBro / 운용사 공시 어댑터로 대체한다."""
        raise NotImplementedError("국내 분배금 소스는 probe_kr 결과로 확정 예정 (리스트 5번)")


def kr_pay_dates(base_day: int, holidays: set) -> None:
    """국내 배당 캘린더 규칙 자리표시.

    미국과 규칙이 완전히 다르다:
      지급기준일(월말형 또는 월중 15일형) → 분배락일 = 지급기준일 직전 영업일
      → 실제 지급은 익월 초 영업일. 연휴가 끼면 공백이 최대 1주까지 벌어진다.
    그래서 holiday_kr 테이블이 채워지기 전에는 계산하지 않는다. (2차 과제)
    """
    raise NotImplementedError("holiday_kr 적재 후 구현 (2차)")
