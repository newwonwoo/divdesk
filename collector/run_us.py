"""미국 ETF 수집기.

흐름:
  1) 우선순위 순으로 어댑터 시도 (야후 → 실패하면 다음)
  2) 배당은 stockanalysis 로 대조. 0.5% 넘게 다른 날짜는 conflict 표시
  3) TTM 배당금은 '기간'이 아니라 '지급횟수'로 자른다 (아래 주석 참고)
  4) 전부 실패한 종목은 조용히 넘기지 않고 실패 목록에 남긴다

실행:
  python -m collector.run_us --dry-run     # DB 없이 로직만
  python -m collector.run_us               # 실제 적재
"""
from __future__ import annotations

import argparse
import sys
import traceback

from .sources.base import ContractError, SourceBlocked, ttm_sum
from .sources.stockanalysis import StockAnalysisAdapter, compare
from .sources.yahoo import YahooAdapter
from .store import Store

# 종목: (티커, 지급주기 횟수, 커버드콜 여부)
# 벤치마크. 매수 후보는 아니지만 비교하려면 같은 데이터가 필요하다.
BENCHMARKS = [("SPY", 4, False), ("VOO", 4, False), ("QQQ", 4, False)]

UNIVERSE = BENCHMARKS + [
    ("SCHD", 4, False), ("VYM", 4, False), ("VIG", 4, False), ("DGRO", 4, False),
    ("DVY", 4, False), ("SDY", 4, False), ("NOBL", 4, False), ("HDV", 4, False),
    ("FDVV", 4, False), ("SCHY", 4, False), ("VYMI", 4, False), ("VNQ", 4, False),
    ("DGRW", 12, False), ("SPHD", 12, False), ("PFF", 12, False), ("DIV", 12, False),
    ("JEPI", 12, True), ("JEPQ", 12, True), ("QYLD", 12, True),
    ("XYLD", 12, True), ("RYLD", 12, True),
]


def collect_one(ticker: str, pays: int, primary, checker, store: Store) -> dict:
    quote = primary.fetch_quote(ticker)
    divs = primary.fetch_dividends(ticker, years=6)

    conflicts: set = set()
    notes: list[str] = []
    try:
        second = checker.fetch_dividends(ticker)
        problems = compare(divs[-pays:], second)
        if problems:
            conflicts = {d.ex_date for d in divs[-pays:]}
            notes.append(f"교차검증 불일치 {len(problems)}건: {problems[0]}")
    except Exception as exc:                                  # noqa: BLE001
        notes.append(f"교차검증 건너뜀({type(exc).__name__})")

    # 200일선·52주 고저에는 일봉이 필요하고, 장기 적립 시뮬레이션에는
    # 10년보다 긴 이력이 필요하다. 야후는 range=max 를 주면 일봉이 아니라
    # 월봉을 돌려주므로, 최근은 일봉(10년) + 과거는 월봉(상장 이후)으로 합친다.
    stats: dict = {}
    try:
        daily = primary.fetch_history(ticker, rng="10y")
        merged = dict()
        try:
            for row in primary.fetch_history(ticker, rng="max"):
                merged[row[0]] = row              # 월봉 먼저
        except Exception:                                     # noqa: BLE001
            notes.append("장기 월봉 수집 실패 — 최근 10년만 저장")
        for row in daily:
            merged[row[0]] = row                  # 겹치면 일봉이 이긴다
        series = sorted(merged.values())
        stats = store.upsert_history(ticker, series, primary.name)
        if stats.get("ma200") is None:
            notes.append(f"거래일 {stats.get('days')}일치뿐 — 200일선 없음(가격 위치 항목 중립 처리)")
    except Exception as exc:                                  # noqa: BLE001
        notes.append(f"시계열 수집 실패({type(exc).__name__}) — 종가만 저장")
        store.upsert_quote(quote)

    store.upsert_dividends(divs, conflicts)
    store.save_raw(primary.name, ticker,
                   {"close": quote.close, "divs": len(divs), **stats})

    ttm, used = ttm_sum(divs, pays)
    if used < pays:
        notes.append(f"분배금 {used}회만 확인됨(기대 {pays}회) → 배당률 참고용")
    return {
        "ticker": ticker,
        "close": quote.close,
        "ttm": ttm,
        "yield_pct": round(ttm / quote.close * 100, 2) if quote.close else None,
        "count": used,
        "last_ex": divs[-1].ex_date if divs else None,
        "conflict": bool(conflicts),
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="DB에 쓰지 않고 로직만 실행")
    parser.add_argument("--only", help="쉼표로 구분한 티커만 처리")
    args = parser.parse_args(argv)

    targets = UNIVERSE
    if args.only:
        want = {t.strip().upper() for t in args.only.split(",")}
        targets = [row for row in UNIVERSE if row[0] in want]

    store = Store(dry_run=args.dry_run)
    primary, checker = YahooAdapter(), StockAnalysisAdapter()

    rows: list[dict] = []
    failed: list[tuple[str, str]] = []

    for ticker, pays, _cc in targets:
        try:
            rows.append(collect_one(ticker, pays, primary, checker, store))
        except (SourceBlocked, ContractError) as exc:
            failed.append((ticker, f"{type(exc).__name__}: {exc}"))
        except Exception as exc:                              # noqa: BLE001
            failed.append((ticker, f"{type(exc).__name__}: {exc}"))
            traceback.print_exc(limit=1)

    try:
        # 환율은 '지금 값'만으로는 부족하다. 스코어의 환율 항목이 3년 밴드 백분위를
        # 쓰기 때문에 시계열을 함께 채운다.
        history = primary.fetch_history("USDKRW=X", rng="5y")
        for row in history:
            store.upsert_fx(row[1], row[0], primary.name)
        rate, day = primary.fetch_usdkrw()
        store.upsert_fx(rate, day, primary.name)
        fx_line = f"USD/KRW {rate:,.2f} ({day}) · 환율 이력 {len(history)}일"
    except Exception as exc:                                  # noqa: BLE001
        fx_line = f"환율 수집 실패: {type(exc).__name__}"

    store.commit()
    store.record_sync("us", not failed, len(rows),
                      f"성공 {len(rows)} 실패 {len(failed)}")

    print(f"{'종목':<6}{'종가':>10}{'TTM배당':>10}{'배당률%':>9}{'횟수':>5}  최근배당락")
    for row in rows:
        flag = " ⚠" if row["conflict"] else ""
        print(f"{row['ticker']:<6}{row['close']:>10.2f}{row['ttm']:>10.3f}"
              f"{row['yield_pct']:>9.2f}{row['count']:>5}  {row['last_ex']}{flag}")
    for row in rows:
        for note in row["notes"]:
            if "건너뜀" not in note:
                print(f"  · {row['ticker']}: {note}")

    print(f"\n{fx_line}")
    print(f"성공 {len(rows)} / 실패 {len(failed)}")
    for ticker, reason in failed:
        print(f"  ✗ {ticker} {reason}")
    print(store.summary())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
