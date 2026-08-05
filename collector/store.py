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
        """일별 시세를 넣고, 마지막 날짜 기준 200일선·52주 고저를 계산해 함께 저장한다.

        계산을 SQL이 아니라 여기서 하는 이유: 표본이 모자랄 때 '억지로 만든 값'을
        넣지 않고 None 으로 두기 위해서다. 200일치가 없으면 200일선은 없는 게 맞다.
        """
        if not series:
            return {}

        # 소스마다 튜플 길이가 다르다(일봉 5개, 월봉 3개). 5개로 맞춘다.
        # 길이를 가정하면 "not enough values to unpack" 으로 수집 전체가 죽는다.
        def pad(row):
            row = tuple(row)
            return row + (None,) * (5 - len(row)) if len(row) < 5 else row[:5]

        series = sorted(pad(row) for row in series)

        # 주말 행은 어느 거래소에도 존재할 수 없다. 들어오면 200일선·52주 창이
        # 그만큼 밀리고, `engine/calendar.py` 가 거래일을 **수집된 날짜에서**
        # 도출하므로 휴장일 판정까지 함께 틀어진다.
        # 공휴일 표는 만들지 않지만(매년 갱신 누락으로 조용히 틀어진다) 주말은
        # 표가 필요 없는 구조적 사실이라 여기서 막는다. 조용히 버리지 않고
        # 개수를 돌려줘 수집 로그에 남긴다.
        weekend = [row for row in series if row[0].weekday() >= 5]
        if weekend:
            series = [row for row in series if row[0].weekday() < 5]
        if not series:
            return {"days": 0, "weekend_dropped": len(weekend)}

        # 과거 월봉이 섞여 있을 수 있으므로, 지표는 '연속된 일봉 구간'에서만 낸다.
        # 직전 관측과 7일 넘게 벌어진 지점 이후를 일봉으로 본다.
        daily_start = 0
        for i in range(len(series) - 1, 0, -1):
            if (series[i][0] - series[i - 1][0]).days > 7:
                daily_start = i
                break
        daily_rows = series[daily_start:]
        daily = [row[1] for row in daily_rows]

        # 200일선을 마지막 날짜에만 저장하면 추세(기울기)를 낼 수 없다.
        # 실제로 그 때문에 200일선 기울기가 항상 비어 있었다. 매일 계산해 넣는다.
        indicators = {}
        for i in range(len(daily)):
            if i >= 199:
                ma = round(sum(daily[i - 199:i + 1]) / 200, 4)
            else:
                ma = None
            if i >= 251:
                window = daily[i - 251:i + 1]
                hi, lo = round(max(window), 4), round(min(window), 4)
            else:
                hi = lo = None
            indicators[daily_rows[i][0]] = (ma, hi, lo)

        ma200 = indicators.get(series[-1][0], (None, None, None))[0]
        high52 = indicators.get(series[-1][0], (None, None, None))[1]
        low52 = indicators.get(series[-1][0], (None, None, None))[2]

        for day, close, adj, open_px, low_px in series:
            ind = indicators.get(day, (None, None, None))
            self.execute(
                """INSERT INTO etf_price_daily
                     (ticker,date,close,open,low,adj_close,ma200,high52,low52,src)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (ticker,date) DO UPDATE
                     SET close=EXCLUDED.close,
                         open=COALESCE(EXCLUDED.open, etf_price_daily.open),
                         low=COALESCE(EXCLUDED.low, etf_price_daily.low),
                         adj_close=EXCLUDED.adj_close, ma200=EXCLUDED.ma200,
                         high52=EXCLUDED.high52, low52=EXCLUDED.low52""",
                (ticker, day, close, open_px, low_px, adj,
                 ind[0], ind[1], ind[2], src))
        self._bump("prices", len(series))
        return {"ma200": ma200, "high52": high52, "low52": low52,
                "days": len(series), "weekend_dropped": len(weekend),
                "with_open": sum(1 for row in series if row[3] is not None)}

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

    def record_sync(self, source: str, ok: bool, added: int, message: str = "") -> None:
        """동기화 결과를 남긴다.

        조용히 멈춘 채 낡은 숫자를 보여주는 것이 가장 나쁜 실패 방식이라,
        성공·실패 모두 기록해 화면에서 알 수 있게 한다.
        기록 자체가 실패해도 수집을 망치지 않는다.
        """
        if self.dry_run:
            return
        try:
            conn = self.connect()
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO sync_log (source, ok, added, message)
                               VALUES (%s,%s,%s,%s)""",
                            (source, ok, added, (message or "")[:500]))
            conn.commit()
        except Exception:                                     # noqa: BLE001
            pass

    def summary(self) -> str:
        mode = "DRY-RUN(DB 미접속)" if self.dry_run else self.dsn
        parts = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
        return f"[{mode}] {parts or '변경 없음'}"
