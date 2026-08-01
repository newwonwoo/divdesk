"""기초 잔고 보정.

증권사 Open API 는 주문 이력을 무한정 주지 않는다. 실측(2026-08-01) 결과
토스는 약 2024-10 이후만 제공했고, 그 이전에 산 물량은 주문 조회에 없다.
그래서 주문내역만으로 계산하면 보유수량이 실제보다 적고 평단이 왜곡된다.

이 스크립트는 잔고와 주문 합계의 차이를 '기초 잔고' 한 건으로 채운다.

  차이 수량 = 실제 잔고 - 주문에서 집계한 수량
  차이 원가 = (실제 평단 × 실제 잔고) - 주문 원가 합계
  → 기초 단가 = 차이 원가 ÷ 차이 수량

이렇게 하면 수량·평단·총원가가 증권사와 일치한다.
**매수일과 환율은 채우지 않는다.** 모르는 값을 지어내면 환차익이 오염된다.
`is_opening_balance=true` 로 표시해 환차익 계산에서 제외한다.

실행:
    python -m collector.opening_balance --dry-run
    python -m collector.opening_balance
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from .store import Store
from .sync_toss import (TossError, _conn, _credentials, fetch_holdings,
                        get_token, known_tickers, account_mode)

TOLERANCE = 0.0001          # 이 미만 차이는 반올림 오차로 본다


def booked(store: Store) -> dict:
    """이미 저장된 매수기록의 종목별 수량·원가(현지통화)."""
    conn = _conn(store)
    with conn.cursor() as cur:
        cur.execute("""SELECT ticker, SUM(qty), SUM(qty * price + COALESCE(fee, 0))
                       FROM purchase GROUP BY ticker""")
        return {t: (float(q), float(c)) for t, q, c in cur.fetchall()}


def existing_opening(store: Store) -> set:
    conn = _conn(store)
    with conn.cursor() as cur:
        cur.execute("SELECT ticker FROM purchase WHERE is_opening_balance")
        return {row[0] for row in cur.fetchall()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", default="2024-10-03",
                        help="기초 잔고로 기록할 날짜 (주문 조회 가능 범위 직전)")
    args = parser.parse_args(argv)

    try:
        cid, secret, account = _credentials()
        token = get_token(cid, secret)
        holdings = fetch_holdings(token, account)
    except TossError as exc:
        print(f"토스 연동 실패: {exc}")
        return 1

    store = Store(dry_run=args.dry_run)
    try:
        universe = known_tickers(store)
        recorded = booked(store)
        already = existing_opening(store)
    except Exception as exc:                                  # noqa: BLE001
        print(f"DB 연결 실패: {type(exc).__name__}: {exc}")
        return 1

    as_of = date.fromisoformat(args.date)
    added, matched, skipped = [], [], []

    for item in holdings:
        ticker = item.get("symbol")
        market = universe.get(ticker)
        if market is None:
            continue                       # ETF 아닌 종목
        if ticker in already:
            skipped.append(ticker)
            continue

        actual_qty = float(item.get("quantity") or 0)
        actual_avg = float(item.get("averagePurchasePrice") or 0)
        have_qty, have_cost = recorded.get(ticker, (0.0, 0.0))

        gap_qty = actual_qty - have_qty
        if gap_qty <= TOLERANCE:
            matched.append((ticker, actual_qty, have_qty))
            continue

        gap_cost = actual_avg * actual_qty - have_cost
        if gap_cost <= 0:
            print(f"  ⚠ {ticker}: 수량은 모자란데 원가는 초과합니다 "
                  f"(수량 {gap_qty:+.4f}, 원가 {gap_cost:+.2f}). 확인이 필요합니다.")
            continue
        gap_price = gap_cost / gap_qty

        store.execute(
            """INSERT INTO purchase
                 (ticker, trade_date, qty, price, fx_at_buy, fee,
                  account_mode, memo, is_opening_balance)
               VALUES (%s,%s,%s,%s,NULL,0,%s,%s,true)""",
            (ticker, as_of, gap_qty, gap_price, account_mode(market),
             "opening:증권사 매수이력 없음"))
        added.append((ticker, gap_qty, gap_price, actual_qty, actual_avg))

    if not args.dry_run:
        store.commit()

    print(f"보유 {len(holdings)}종 중 추적 대상 확인\n")
    for ticker, qty, price, total_qty, total_avg in added:
        print(f"  + {ticker:<8} 기초 {qty:>10,.4f}주 @ {price:>8,.2f} "
              f"→ 합계 {total_qty:,.4f}주 평단 {total_avg:,.4f}")
    for ticker, actual, have in matched:
        print(f"  = {ticker:<8} 이미 일치 ({actual:,.4f}주)")
    if skipped:
        print(f"  · 기초 잔고가 이미 있는 종목 {len(skipped)}종 건너뜀: {', '.join(skipped)}")
    if not added and not matched:
        print("  추적 중인 ETF 보유분이 없습니다.")
    if added:
        print("\n기초 잔고는 매수일·환율을 모르므로 환차익 계산에서 제외됩니다.")
    if args.dry_run:
        print("(dry-run — 저장하지 않았습니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
