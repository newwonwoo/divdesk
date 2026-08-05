"""시세 테이블 정합성 진단 — EC2 에서 읽기 전용으로 돌린다.

왜 만드나: HANDOFF 3절 2순위 "국내 종목 중복 적재 의심" 은 **의심** 으로만 적혀
있었다(최근 1년 294행 > 연간 거래일 246). 원인이 중복인지, 잘못된 날짜인지,
과거 월봉 잔재인지 코드만 봐서는 가릴 수 없다. 추측으로 고치면 엉뚱한 걸
건드리므로 먼저 잰다.

1·4순위 상태도 같은 자리에서 확인한다 — `open`/`low` 가 실제로 채워졌는지,
`ma200` 이 마지막 행에만 있는지.

**SELECT 만 한다.** 쓰기·삭제는 없다. 무엇을 지울지는 사람이 보고 정한다.

실행:
  DIVDESK_DSN=... python3 -m scripts.diagnose_prices
  DIVDESK_DSN=... python3 -m scripts.diagnose_prices --market KR
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

# 평일인데 이 비율 미만의 종목에만 존재하는 날짜는 '그 종목만 가진 날' 로 본다.
# 같은 시장은 같은 날 쉬므로, 소수 종목에만 있는 평일은 잘못 들어온 날짜다.
LONELY_RATIO = 0.34


def fetch(dsn: str, market: str | None):
    import psycopg

    where = "WHERE m.is_benchmark = false"
    params: tuple = ()
    if market:
        where += " AND m.market = %s"
        params = (market,)

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='etf_price_daily'")
        cols = {c for (c,) in cur.fetchall()}
        oc = "p.open" if "open" in cols else "NULL"
        lc = "p.low" if "low" in cols else "NULL"
        cur.execute(f"""SELECT m.ticker, m.market, p.date, {oc}, {lc}, p.ma200
                        FROM etf_price_daily p JOIN etf_master m USING (ticker)
                        {where} ORDER BY m.ticker, p.date""", params)
        return cols, cur.fetchall()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", help="US 또는 KR. 생략하면 전체")
    args = parser.parse_args(argv)

    dsn = os.environ.get("DIVDESK_DSN")
    if not dsn:
        print("DIVDESK_DSN 이 없습니다.")
        return 2

    cols, rows = fetch(dsn, args.market)
    if not rows:
        print("행이 없습니다.")
        return 1

    if "open" not in cols or "low" not in cols:
        print("⚠ etf_price_daily 에 open/low 컬럼이 없습니다 — "
              "`make migrate` 를 먼저 돌리세요.\n")

    per: dict = defaultdict(list)
    market_of: dict = {}
    for ticker, market, day, open_px, low_px, ma200 in rows:
        per[ticker].append((day, open_px, low_px, ma200))
        market_of[ticker] = market

    # 같은 시장에서 그 날짜를 가진 종목 수 — 소수만 가진 평일을 찾는다
    day_holders: dict = defaultdict(set)
    market_size: dict = defaultdict(set)
    for ticker, market, day, *_ in rows:
        day_holders[(market, day)].add(ticker)
        market_size[market].add(ticker)

    last = max(day for _, _, day, *_ in rows)
    year_ago = last.replace(year=last.year - 1)

    print(f"기준 최신일 {last}   (최근 1년 = {year_ago} 이후)\n")
    header = (f"{'종목':<10}{'시장':<5}{'행':>7}{'최근1년':>8}{'주말':>6}"
              f"{'외톨이':>7}{'시가없음':>9}{'ma200없음':>10}  기간")
    print(header)
    print("-" * len(header))

    flagged: dict = defaultdict(list)
    for ticker in sorted(per):
        series = per[ticker]
        market = market_of[ticker]
        days = [d for d, *_ in series]
        recent = [d for d in days if d >= year_ago]
        weekend = [d for d in days if d.weekday() >= 5]
        lonely = [d for d in days if d.weekday() < 5 and len(market_size[market]) > 2
                  and len(day_holders[(market, d)]) <= max(1, int(
                      len(market_size[market]) * LONELY_RATIO))]
        no_open = sum(1 for _, o, _, _ in series if o is None)
        no_ma = sum(1 for *_, ma in series if ma is None)

        print(f"{ticker:<10}{market:<5}{len(days):>7}{len(recent):>8}"
              f"{len(weekend):>6}{len(lonely):>7}{no_open:>9}{no_ma:>10}"
              f"  {days[0]}~{days[-1]}")

        if weekend:
            flagged["주말 행 (거래소가 열리지 않는 날)"].append(
                f"{ticker}: {len(weekend)}건 예) "
                + ", ".join(str(d) for d in weekend[:4]))
        if lonely:
            flagged["같은 시장 대다수에 없는 평일 (잘못 들어온 날짜 의심)"].append(
                f"{ticker}: {len(lonely)}건 예) "
                + ", ".join(str(d) for d in lonely[:4]))
        if len(recent) > 260:
            flagged["최근 1년 행 수가 거래일(약 246)을 넘음"].append(
                f"{ticker}: {len(recent)}행")
        if no_open == len(days):
            flagged["시가가 한 행도 없음 (배당락 10점이 중립으로 고정)"].append(ticker)
        if no_ma and no_ma > len(days) - 2 and len(days) > 200:
            flagged["ma200 이 사실상 비어 있음 (마지막 행에만 저장된 상태)"].append(
                f"{ticker}: {len(days) - no_ma}행만 있음")

    print()
    if not flagged:
        print("이상 없음.")
        return 0

    print("=" * 62)
    for title, items in flagged.items():
        print(f"\n[{title}]")
        for line in items[:12]:
            print(f"  · {line}")
        if len(items) > 12:
            print(f"  … 외 {len(items) - 12}건")

    print("\n지우기 전에 무엇을 지울지 눈으로 확인하세요. 이 스크립트는 읽기만 합니다.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
