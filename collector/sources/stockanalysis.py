"""stockanalysis.com — 미국 ETF 배당 교차검증용 2순위 소스.

역할이 야후와 다르다. 여기서 값을 '가져오는' 게 아니라 야후 값이 맞는지 '대조'한다.
그래서 파싱이 실패해도 수집 전체를 실패시키지 않고 None을 돌려준다.
(HTML 구조는 언제든 바뀔 수 있고, 검증용이라 없어도 앱은 돌아가야 한다)

실측(2026-07-30): /etf/schd/dividend/ 200 OK, 약 90KB HTML.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .base import Adapter, Dividend, SourceBlocked

URL = "https://stockanalysis.com/etf/{sym}/dividend/"

# 표의 한 행: 2026-06-24 ... 0.278  형태를 느슨하게 잡는다.
ROW = re.compile(
    r"(\d{4}-\d{2}-\d{2})\D{0,80}?\$?\s*(\d+\.\d{2,6})",
    re.S,
)


@dataclass
class StockAnalysisAdapter(Adapter):
    name: str = "stockanalysis"
    market: str = "US"
    priority: int = 50
    min_interval: float = 2.0          # 사람 눈으로 보는 페이지다. 더 천천히.

    def fetch_dividends(self, ticker: str, years: int = 6) -> list[Dividend]:
        try:
            html = self._get(URL.format(sym=ticker.lower()),
                             headers={"Accept": "text/html"}).text
        except SourceBlocked:
            return []
        out: list[Dividend] = []
        seen: set = set()
        for raw_date, raw_amt in ROW.findall(html):
            try:
                ex = datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                continue
            if ex in seen:
                continue
            amount = float(raw_amt)
            if not (0 < amount < 100):       # 주당 분배금 상식 범위
                continue
            seen.add(ex)
            out.append(Dividend(ticker=ticker, ex_date=ex, dps=amount, src=self.name))
        return sorted(out, key=lambda d: d.ex_date)


def compare(primary: list[Dividend], secondary: list[Dividend],
            tol: float = 0.005) -> list[str]:
    """같은 ex_date의 값이 tol(0.5%) 넘게 다른 건만 골라 사유 문자열로 돌려준다."""
    if not secondary:
        return []
    ref = {d.ex_date: d.dps for d in secondary}
    problems: list[str] = []
    for d in primary:
        other = ref.get(d.ex_date)
        if other is None or other == 0:
            continue
        gap = abs(d.dps - other) / other
        if gap > tol:
            problems.append(f"{d.ex_date} {d.dps} vs {other} ({gap:.1%} 차이)")
    return problems
