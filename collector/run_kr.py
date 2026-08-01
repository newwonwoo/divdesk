"""국내 ETF 수집기.

네이버 대신 야후를 쓴다. 실측(2026-08-01) 결과 야후가 `종목코드.KS` 형태로
국내 ETF의 원화 시세와 분배금 이력을 모두 준다 — 10/10 종목 확인.
소스가 하나로 통일되면 어댑터·검증 로직을 그대로 재사용할 수 있고,
네이버 비공식 엔드포인트에 의존하지 않아도 된다.

네이버는 폐기하지 않고 2순위 교차검증용으로 남겨 둔다(naver_kr.py).

실행:
  python -m collector.run_kr --dry-run
  python -m collector.run_kr
"""
from __future__ import annotations

import argparse
import statistics
import sys

from .sources.base import ContractError, SourceBlocked, ttm_sum
from .sources.yahoo import YahooAdapter
from .store import Store

# 티커 → 야후 심볼. 국내 ETF는 코스피 상장이라 .KS 를 붙인다.
def symbol(ticker: str) -> str:
    return f"{ticker}.KS"


def infer_pays_per_year(divs: list) -> int | None:
    """지급 간격에서 연 지급 횟수를 도출한다.

    마스터에 손으로 적어둔 주기를 믿지 않는 이유: 실제로 틀려 있었다.
    국내 고배당·리츠 ETF 여럿이 분기로 알려져 있었으나 데이터상 월배당이었고,
    주기를 잘못 잡으면 TTM 합산 구간이 어긋나 배당률이 통째로 틀어진다.
    """
    if len(divs) < 4:
        return None
    recent = sorted(d.ex_date for d in divs)[-13:]
    gaps = [(recent[i + 1] - recent[i]).days for i in range(len(recent) - 1)]
    median = statistics.median(gaps)
    if median <= 0:
        return None
    guess = round(365 / median)
    # 실제 존재하는 주기로만 스냅. 어중간한 값은 판단하지 않는다.
    for candidate in (12, 4, 2, 1):
        if abs(guess - candidate) <= 1:
            return candidate
    return None


def collect_one(ticker: str, adapter: YahooAdapter, store: Store,
                expected_name: str | None = None) -> dict:
    sym = symbol(ticker)
    quote = adapter.fetch_quote(sym)
    divs = adapter.fetch_dividends(sym, years=6)
    for d in divs:                      # 저장은 국내 티커로 (심볼 아님)
        d.ticker = ticker
    quote.ticker = ticker

    notes: list[str] = []
    if quote.currency != "KRW":
        notes.append(f"통화가 {quote.currency}로 조회됨 — 국내 상장이 맞는지 확인 필요")

    stats: dict = {}
    try:
        history = adapter.fetch_history(sym, rng="max")
        stats = store.upsert_history(ticker, history, adapter.name)
        if stats.get("ma200") is None:
            notes.append(f"거래일 {stats.get('days')}일치뿐 — 200일선 없음(가격 위치 항목 중립)")
    except Exception as exc:                                  # noqa: BLE001
        notes.append(f"시계열 수집 실패({type(exc).__name__}) — 종가만 저장")
        store.upsert_quote(quote)

    store.upsert_dividends(divs, None)

    pays = infer_pays_per_year(divs)
    if pays is None:
        notes.append("지급 주기를 판단할 분배금 이력이 부족합니다")
    ttm, used = ttm_sum(divs, pays or 12)

    # 야후가 주는 영문 상품명으로 종목코드가 맞는지 대조한다.
    listed = getattr(adapter, "last_short_name", None)
    store.save_raw(adapter.name, ticker,
                   {"close": quote.close, "divs": len(divs),
                    "pays": pays, "short_name": listed, **stats})

    return {
        "ticker": ticker, "close": quote.close, "ttm": ttm,
        "yield_pct": round(ttm / quote.close * 100, 2) if quote.close else None,
        "pays": pays, "count": used,
        "last_ex": divs[-1].ex_date if divs else None,
        "short_name": listed, "expected": expected_name, "notes": notes,
    }


def targets(store: Store) -> list[tuple[str, str, int | None]]:
    """DB의 국내 종목 마스터를 읽는다. DB가 없으면 시딩 목록으로 대체."""
    if store.dry_run:
        from scripts.seed_master import KR
        return [(row[0], row[1], row[5]) for row in KR]
    conn = store.connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT ticker, name, pays_per_year FROM etf_master
                       WHERE market='KR' ORDER BY ticker""")
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", help="쉼표로 구분한 종목코드")
    args = parser.parse_args(argv)

    store = Store(dry_run=args.dry_run)
    adapter = YahooAdapter(market="KR")

    rows = targets(store)
    if args.only:
        want = {t.strip() for t in args.only.split(",")}
        rows = [r for r in rows if r[0] in want]

    ok: list[dict] = []
    failed: list[tuple[str, str]] = []
    for ticker, name, declared in rows:
        try:
            result = collect_one(ticker, adapter, store, name)
            result["declared_pays"] = declared
            ok.append(result)
        except (SourceBlocked, ContractError) as exc:
            failed.append((ticker, f"{type(exc).__name__}: {exc}"))
        except Exception as exc:                              # noqa: BLE001
            failed.append((ticker, f"{type(exc).__name__}: {exc}"))

    store.commit()

    print(f"{'코드':<8}{'종가':>10}{'TTM분배':>10}{'배당률%':>9}{'주기':>5}  종목명")
    for r in ok:
        print(f"{r['ticker']:<8}{r['close']:>10,.0f}{r['ttm']:>10,.0f}"
              f"{(r['yield_pct'] or 0):>9.2f}{('연%d회' % r['pays']) if r['pays'] else '  ?':>7}"
              f"  {r['expected']}")
        if r["declared_pays"] and r["pays"] and r["declared_pays"] != r["pays"]:
            print(f"    ⚠ 마스터에는 연{r['declared_pays']}회로 적혀 있으나 "
                  f"실제 이력은 연{r['pays']}회입니다 — 마스터를 고치세요")
        for note in r["notes"]:
            print(f"    · {note}")

    print(f"\n성공 {len(ok)} / 실패 {len(failed)}")
    for ticker, reason in failed:
        print(f"  ✗ {ticker} {reason}")
    print(store.summary())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
