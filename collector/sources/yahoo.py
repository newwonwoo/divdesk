"""야후 파이낸스 chart 엔드포인트. 미국 ETF 1순위 소스.

실측(2026-07-30): SCHD 5년 조회 시 분배금 20건, 종가·환율 정상. 21/21 성공.
인증키 없음. events=div 를 붙이면 배당 이벤트가 같이 온다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .base import Adapter, ContractError, Dividend, Quote, check_contract

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"


def _to_date(ts: int):
    return datetime.fromtimestamp(ts, timezone.utc).date()


@dataclass
class YahooAdapter(Adapter):
    name: str = "yahoo"
    market: str = "US"
    priority: int = 10
    last_short_name: str | None = None   # 종목코드가 맞는지 대조용

    def _chart(self, sym: str, rng: str, events: str = "") -> dict:
        url = BASE.format(sym=sym) + f"?range={rng}&interval=1d"
        if events:
            url += f"&events={events}"
        body = self._get(url).json()
        check_contract(body, ["chart"], "yahoo.root")
        chart = body["chart"]
        if chart.get("error"):
            raise ContractError(f"yahoo error: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise ContractError(f"yahoo: result 비어 있음 ({sym})")
        return results[0]

    def fetch_quote(self, ticker: str) -> Quote:
        res = self._chart(ticker, "5d")
        check_contract(res, ["meta"], "yahoo.result")
        meta = res["meta"]
        check_contract(meta, ["regularMarketPrice", "regularMarketTime"], "yahoo.meta")
        self.last_short_name = meta.get("shortName") or meta.get("longName")
        return Quote(
            ticker=ticker,
            close=float(meta["regularMarketPrice"]),
            asof=_to_date(int(meta["regularMarketTime"])),
            src=self.name,
            currency=meta.get("currency", "USD"),
        )

    def fetch_dividends(self, ticker: str, years: int = 6) -> list[Dividend]:
        res = self._chart(ticker, f"{years}y", events="div")
        events = (res.get("events") or {}).get("dividends") or {}
        out: list[Dividend] = []
        for item in events.values():
            if "date" not in item or "amount" not in item:
                raise ContractError("yahoo.dividends: date/amount 키 누락")
            out.append(Dividend(
                ticker=ticker,
                ex_date=_to_date(int(item["date"])),
                dps=float(item["amount"]),
                src=self.name,
            ))
        return sorted(out, key=lambda d: d.ex_date)

    def fetch_history(self, ticker: str, rng: str = "2y") -> list[tuple]:
        """(날짜, 종가, 수정종가) 시계열.

        수정종가(adjclose)는 분배금을 재투자한 것으로 보정한 값이라
        두 시점의 비율이 곧 총수익률이 된다. 종가만으로 계산하면
        분배금 재투자를 무시한 근사치가 되므로 함께 받는다.
        """
        res = self._chart(ticker, rng, events="div")
        check_contract(res, ["timestamp", "indicators"], "yahoo.history")
        stamps = res["timestamp"]
        quotes = res["indicators"]["quote"][0]
        closes = quotes.get("close") or []
        adj_block = (res["indicators"].get("adjclose") or [{}])[0]
        adjs = adj_block.get("adjclose") or []
        out = []
        for idx, (ts, close) in enumerate(zip(stamps, closes)):
            if close is None:
                continue                      # 거래정지일 등. 채워 넣지 않는다.
            adj = adjs[idx] if idx < len(adjs) else None
            out.append((_to_date(int(ts)), float(close),
                        float(adj) if adj is not None else None))
        return out

    def fetch_usdkrw(self) -> tuple[float, "object"]:
        res = self._chart("USDKRW=X", "5d")
        meta = res["meta"]
        check_contract(meta, ["regularMarketPrice", "regularMarketTime"], "yahoo.fx")
        return float(meta["regularMarketPrice"]), _to_date(int(meta["regularMarketTime"]))
