"""소스 어댑터 공통 규격.

왜 이 파일이 있나:
네이버·야후 같은 비공식 엔드포인트는 예고 없이 응답 모양이 바뀐다.
바뀐 걸 모르고 지나가면 '조용히 틀린 숫자'가 DB에 쌓이는 게 최악이다.
그래서 모든 어댑터는 같은 모양(Quote / Dividend)으로만 값을 돌려주고,
돌려주기 전에 스스로 검증(check_contract)을 통과해야 한다. 실패하면 예외를 던진다.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import date

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class SourceBlocked(Exception):
    """403/429 등 차단. 즉시 중단하고 다음 소스로 넘긴다."""


class ContractError(Exception):
    """응답 스키마가 기대와 다름. 값을 쓰지 않고 실패시킨다."""


@dataclass
class Quote:
    ticker: str
    close: float
    asof: date
    src: str
    nav: float | None = None
    currency: str = "USD"


@dataclass
class Dividend:
    ticker: str
    ex_date: date
    dps: float
    src: str
    pay_date: date | None = None
    is_estimate: bool = False


@dataclass
class Adapter:
    """모든 어댑터의 부모. priority 낮은 숫자가 먼저 시도된다."""

    name: str = "base"
    market: str = "US"
    priority: int = 100
    min_interval: float = 1.2          # 요청 간 최소 간격(초)
    _last_call: float = field(default=0.0, repr=False)

    # --- 예절: 간격 두기 ---
    def _throttle(self) -> None:
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _get(self, url: str, *, headers: dict | None = None, timeout: int = 15):
        self._throttle()
        hdr = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9"}
        if headers:
            hdr.update(headers)
        for attempt in range(3):
            resp = requests.get(url, headers=hdr, timeout=timeout)
            if resp.status_code in (403, 429):
                # 차단은 재시도로 뚫으려 하면 더 크게 막힌다. 백오프 후 포기.
                time.sleep((2 ** attempt) + random.random())
                if attempt == 2:
                    raise SourceBlocked(f"{self.name} {resp.status_code} {url}")
                continue
            if resp.status_code >= 500:
                time.sleep(1 + attempt)
                continue
            resp.raise_for_status()
            return resp
        raise SourceBlocked(f"{self.name} 반복 실패 {url}")

    # --- 하위 클래스가 구현 ---
    def fetch_quote(self, ticker: str) -> Quote:
        raise NotImplementedError

    def fetch_dividends(self, ticker: str, years: int = 6) -> list[Dividend]:
        raise NotImplementedError


def check_contract(payload: dict, required: list[str], where: str) -> None:
    """응답에 반드시 있어야 할 키가 사라졌는지 확인."""
    missing = [k for k in required if k not in payload]
    if missing:
        raise ContractError(f"{where}: 키 누락 {missing} (엔드포인트 스키마 변경 의심)")


def ttm_sum(divs: list[Dividend], pays_per_year: int) -> tuple[float, int]:
    """최근 N회 분배금 합계.

    날짜 창(예: 최근 370일)으로 자르면 지급일이 며칠 밀린 해에 5회/13회가 잡혀
    배당률이 부풀려진다. 그래서 '기간'이 아니라 '횟수'로 자른다.
    """
    if not divs or pays_per_year <= 0:
        return 0.0, 0
    recent = sorted(divs, key=lambda d: d.ex_date)[-pays_per_year:]
    return round(sum(d.dps for d in recent), 6), len(recent)
