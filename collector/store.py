"""DB 저장 계층.

dry_run=True 면 Postgres에 붙지 않고 실행할 SQL만 요약해 보여준다.
DB 없는 환경에서 수집 로직만 검증할 때 쓴다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class Store:
    dsn: str = field(default_factory=lambda: os.environ.get(
        "DIVDESK_DSN", "postgresql://divdesk@localhost:5432/divdesk"))
    dry_run: bool = False
    _conn: object | None = field(default=None, repr=False)
    counts: dict = field(default_factory=dict)

    def connect(self):
        if self.dry_run:
            return None
        if self._conn is None:
            import psycopg                                   # 지연 import
            self._conn = psycopg.connect(self.dsn)
        return self._conn

    def _bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._bump("statements")
        if self.dry_run:
            return
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute(sql, params)

    def commit(self) -> None:
        if not self.dry_run and self._conn is not None:
            self._conn.commit()

    # --- upsert 들 ---
    def upsert_quote(self, quote) -> None:
        self.execute(
            """INSERT INTO etf_price_daily (ticker,date,close,nav,src)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (ticker,date) DO UPDATE
                 SET close=EXCLUDED.close, nav=EXCLUDED.nav, src=EXCLUDED.src""",
            (quote.ticker, quote.asof, quote.close, quote.nav, quote.src))
        self._bump("quotes")

    def upsert_history(self, ticker: str, series: list, src: str) -> dict:
        """일별 종가를 넣고, 마지막 날짜 기준 200일선·52주 고저를 계산해 함께 저장한다.

        계산을 SQL이 아니라 여기서 하는 이유: 표본이 모자랄 때 '억지로 만든 값'을
        넣지 않고 None 으로 두기 위해서다. 200일치가 없으면 200일선은 없는 게 맞다.
        """
        if not series:
            return {}
        series = sorted(series)
        # (날짜, 종가) 또는 (날짜, 종가, 수정종가) 둘 다 받는다
        series = [(row[0], row[1], row[2] if len(row) > 2 else None) for row in series]
        # 과거 월봉이 섞여 있을 수 있으므로, 지표는 '연속된 일봉 구간'에서만 낸다.
        # 직전 관측과 7일 넘게 벌어진 지점 이후를 일봉으로 본다.
        daily_start = 0
        for i in range(len(series) - 1, 0, -1):
            if (series[i][0] - series[i - 1][0]).days > 7:
                daily_start = i
                break
        daily = [c for _, c, _ in series[daily_start:]]
        ma200 = round(sum(daily[-200:]) / 200, 4) if len(daily) >= 200 else None
        window = daily[-252:] if len(daily) >= 252 else None
        high52 = round(max(window), 4) if window else None
        low52 = round(min(window), 4) if window else None

        for day, close, adj in series:
            last = day == series[-1][0]
            self.execute(
                """INSERT INTO etf_price_daily
                     (ticker,date,close,adj_close,ma200,high52,low52,src)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (ticker,date) DO UPDATE
                     SET close=EXCLUDED.close, adj_close=EXCLUDED.adj_close,
                         ma200=EXCLUDED.ma200,
                         high52=EXCLUDED.high52, low52=EXCLUDED.low52""",
                (ticker, day, close, adj,
                 ma200 if last else None,
                 high52 if last else None,
                 low52 if last else None, src))
        self._bump("prices", len(series))
        return {"ma200": ma200, "high52": high52, "low52": low52,
                "days": len(series)}

    def upsert_dividends(self, divs: list, conflict_dates: set | None = None) -> None:
        bad = conflict_dates or set()
        for d in divs:
            self.execute(
                """INSERT INTO dividend_history
                     (ticker,ex_date,pay_date,dps,is_estimate,src,conflict)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (ticker,ex_date) DO UPDATE
                     SET dps=EXCLUDED.dps, src=EXCLUDED.src,
                         conflict=EXCLUDED.conflict""",
                (d.ticker, d.ex_date, d.pay_date, d.dps,
                 d.is_estimate, d.src, d.ex_date in bad))
        self._bump("dividends", len(divs))

    def upsert_fx(self, rate: float, day, src: str) -> None:
        self.execute(
            """INSERT INTO fx_rate (date,usdkrw,src) VALUES (%s,%s,%s)
               ON CONFLICT (date) DO UPDATE SET usdkrw=EXCLUDED.usdkrw""",
            (day, rate, src))
        self._bump("fx")

    def save_raw(self, src: str, ticker: str | None, payload: dict) -> None:
        self.execute(
            "INSERT INTO raw_snapshot (src,ticker,payload) VALUES (%s,%s,%s)",
            (src, ticker, json.dumps(payload, default=str)))
        self._bump("raw")

    def summary(self) -> str:
        mode = "DRY-RUN(DB 미접속)" if self.dry_run else self.dsn
        parts = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
        return f"[{mode}] {parts or '변경 없음'}"
