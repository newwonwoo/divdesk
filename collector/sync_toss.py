"""토스증권 Open API 연동 — 매수 이력 자동 동기화.

손으로 매수기록을 입력하지 않아도 되게 한다. 체결된 주문을 그대로 가져오므로
수량·단가·수수료가 실제와 어긋날 일이 없다.

인증: OAuth 2.0 Client Credentials. `client_id`/`client_secret` 으로 토큰을 받고
      계좌 관련 호출에는 `X-Tossinvest-Account` 헤더가 추가로 필요하다.
서버: https://openapi.tossinvest.com

**비밀키는 코드에 넣지 않는다.** .env 에서만 읽는다:
    TOSS_CLIENT_ID / TOSS_CLIENT_SECRET / TOSS_ACCOUNT

TOSS_ACCOUNT 은 **계좌번호가 아니라 accountSeq** 다(보통 1).
`GET /api/v1/accounts` 응답의 accountSeq 값을 넣는다. 계좌번호를 넣으면
account-not-found 가 난다.

호출 한도: 주문 조회는 초당 5회. 429 를 받으면 Retry-After 만큼 기다린다.

동기화 규칙:
  - 체결(filledQuantity > 0)된 **매수** 주문만 가져온다. 매도는 별도 처리 대상이라
    이번 범위에 없다.
  - 이미 저장된 주문은 건너뛴다. `purchase.memo` 에 orderId 를 넣어 판별한다.
  - 매수 시점 환율은 토스에서 받지 않고 **DB의 fx_rate 에서 그날 값을 찾아** 채운다.
    이미 매일 수집하고 있으므로 새로 받을 이유가 없다.
  - 우리가 다루지 않는 종목(etf_master 에 없는 것)은 건너뛰고 목록으로 알린다.

실행:
    python -m collector.sync_toss --dry-run
    python -m collector.sync_toss --from 2025-01-01
"""
from __future__ import annotations

import argparse
import os
import time
import sys
from datetime import date, datetime

import requests

from .store import Store

BASE = "https://openapi.tossinvest.com"
TOKEN_URL = f"{BASE}/oauth2/token"
ORDERS_URL = f"{BASE}/api/v1/orders"
HOLDINGS_URL = f"{BASE}/api/v1/holdings"


class TossError(Exception):
    """토스 API 호출 실패. 조용히 넘기지 않는다."""


def _credentials() -> tuple[str, str, str]:
    cid = os.environ.get("TOSS_CLIENT_ID")
    secret = os.environ.get("TOSS_CLIENT_SECRET")
    # 계좌번호가 아니라 accountSeq 다. GET /api/v1/accounts 응답의 accountSeq 값.
    account = os.environ.get("TOSS_ACCOUNT")
    missing = [name for name, value in
               (("TOSS_CLIENT_ID", cid), ("TOSS_CLIENT_SECRET", secret),
                ("TOSS_ACCOUNT", account)) if not value]
    if missing:
        raise TossError(f".env 에 {', '.join(missing)} 가 없습니다")
    return cid, secret, account


def get_token(client_id: str, client_secret: str) -> str:
    """AUTH 그룹은 초당 5회 제한. 한 번만 받아 쓰므로 여유롭다."""
    resp = requests.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                         auth=(client_id, client_secret), timeout=20)
    if resp.status_code == 429:
        time.sleep(float(resp.headers.get("Retry-After", 2)) + 0.5)
        resp = requests.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                             auth=(client_id, client_secret), timeout=20)
    if resp.status_code == 403:
        raise TossError(
            "허용 IP가 아닙니다. 토스 개발자센터 > 설정 > Open API > 허용 IP 관리에 "
            "이 서버 IP를 등록하세요. (확인: curl -s https://checkip.amazonaws.com)")
    if resp.status_code != 200:
        raise TossError(f"토큰 발급 실패 {resp.status_code}: {resp.text[:200]}")
    token = resp.json().get("access_token")
    if not token:
        raise TossError("응답에 access_token 이 없습니다")
    return token


def _get(url: str, headers: dict, params: dict | None = None,
         min_interval: float = 0.35, max_retry: int = 5):
    """토스 호출 래퍼. 한도를 지키고, 429면 서버가 알려준 만큼 기다린다.

    주문 조회(ORDER_HISTORY)는 초당 5회 제한이다. 페이지를 연속으로 당기면
    금방 걸리므로 호출 사이에 간격을 두고, 429가 오면 Retry-After 를 따른다.
    """
    for attempt in range(max_retry):
        time.sleep(min_interval)
        resp = requests.get(url, headers=headers, params=params, timeout=25)
        if resp.status_code != 429:
            return resp
        wait = resp.headers.get("Retry-After") or resp.headers.get("X-RateLimit-Reset")
        try:
            delay = float(wait)
        except (TypeError, ValueError):
            delay = 2.0 * (attempt + 1)
        print(f"  호출 한도 도달 — {delay:.0f}초 대기 후 재시도")
        time.sleep(delay + 0.5)
    raise TossError("호출 한도를 계속 초과합니다. 잠시 후 다시 실행하세요.")


def fetch_filled_orders(token: str, account: str, since: date | None = None) -> list[dict]:
    """체결 완료된 주문 전량. 페이지네이션을 끝까지 따라간다."""
    headers = {"Authorization": f"Bearer {token}",
               "X-Tossinvest-Account": str(account)}
    params = {"status": "CLOSED", "limit": 100}
    if since:
        params["from"] = since.isoformat()

    out: list[dict] = []
    cursor = None
    for _ in range(50):                      # 안전장치
        if cursor:
            params["cursor"] = cursor
        resp = _get(ORDERS_URL, headers, params)
        if resp.status_code != 200:
            raise TossError(f"주문 조회 실패 {resp.status_code}: {resp.text[:200]}")
        result = resp.json().get("result", {})
        out += result.get("orders", [])
        if not result.get("hasNext"):
            break
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return out


def fetch_holdings(token: str, account: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}",
               "X-Tossinvest-Account": str(account)}
    resp = _get(HOLDINGS_URL, headers)
    if resp.status_code != 200:
        raise TossError(f"보유 조회 실패 {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("result", {}).get("items", [])


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trade_date(order: dict) -> date | None:
    stamp = (order.get("execution") or {}).get("filledAt") or order.get("orderedAt")
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp).date()
    except ValueError:
        return None


def to_purchase(order: dict) -> dict | None:
    """주문 한 건을 매수기록 형태로 바꾼다. 조건에 안 맞으면 None."""
    if order.get("side") != "BUY":
        return None
    execution = order.get("execution") or {}
    qty = _num(execution.get("filledQuantity"))
    if qty <= 0:
        return None
    price = _num(execution.get("averageFilledPrice"))
    if price <= 0:
        return None
    trade_day = _trade_date(order)
    if not trade_day:
        return None
    return {
        "order_id": order.get("orderId"),
        "ticker": order.get("symbol"),
        "trade_date": trade_day,
        "qty": qty,
        "price": price,
        "fee": _num(execution.get("commission")),
        "currency": order.get("currency", "KRW"),
    }


def _conn(store: Store):
    """dry-run 이어도 읽기는 해야 한다.

    Store.dry_run 은 '쓰지 않는다'는 뜻이지 '읽지 않는다'가 아니다.
    종목 목록과 중복 판별은 조회해야 하므로 별도 연결을 쓴다.
    """
    if store._conn is None:
        import psycopg
        store._conn = psycopg.connect(store.dsn)
    return store._conn


def fx_on(store: Store, day: date) -> float | None:
    """그날의 원달러 환율. 휴장이면 직전 영업일 값을 쓴다.

    토스에서 환율을 받지 않는 이유: 이미 매일 수집하고 있고,
    두 소스를 섞으면 값이 어긋났을 때 어느 쪽이 맞는지 알 수 없어진다.
    """
    conn = _conn(store)
    with conn.cursor() as cur:
        cur.execute("""SELECT usdkrw FROM fx_rate
                       WHERE date <= %s ORDER BY date DESC LIMIT 1""", (day,))
        row = cur.fetchone()
    return float(row[0]) if row else None


def known_tickers(store: Store) -> dict:
    conn = _conn(store)
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, market FROM etf_master")
        return {t: m for t, m in cur.fetchall()}


def existing_order_ids(store: Store) -> set:
    conn = _conn(store)
    with conn.cursor() as cur:
        cur.execute("SELECT memo FROM purchase WHERE memo LIKE 'toss:%'")
        return {row[0].split("toss:", 1)[1] for row in cur.fetchall() if row[0]}


def account_mode(market: str) -> str:
    """토스 일반계좌 기준. 절세계좌는 별도 계좌번호라 따로 동기화해야 한다."""
    return "US_TAXABLE" if market == "US" else "KR_TAXABLE"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 보기만")
    parser.add_argument("--from", dest="since", help="조회 시작일 YYYY-MM-DD")
    args = parser.parse_args(argv)

    since = None
    if args.since:
        since = date.fromisoformat(args.since)

    try:
        cid, secret, account = _credentials()
        token = get_token(cid, secret)
        orders = fetch_filled_orders(token, account, since)
    except TossError as exc:
        print(f"토스 연동 실패: {exc}")
        return 1

    store = Store(dry_run=args.dry_run)
    try:
        universe = known_tickers(store)
        already = existing_order_ids(store)
    except Exception as exc:                                  # noqa: BLE001
        print(f"DB 연결 실패: {type(exc).__name__}: {exc}")
        return 1

    added, skipped_dup, unknown, invalid = [], 0, [], 0
    for order in orders:
        item = to_purchase(order)
        if not item:
            invalid += 1
            continue
        if item["order_id"] in already:
            skipped_dup += 1
            continue
        market = universe.get(item["ticker"])
        if market is None:
            unknown.append(item["ticker"])
            continue

        rate = fx_on(store, item["trade_date"]) if item["currency"] == "USD" else None
        store.execute(
            """INSERT INTO purchase
                 (ticker, trade_date, qty, price, fx_at_buy, fee, account_mode, memo)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (item["ticker"], item["trade_date"], item["qty"], item["price"],
             rate, item["fee"], account_mode(market),
             f"toss:{item['order_id']}"))
        item["fx"] = rate
        added.append(item)

    if not args.dry_run:
        store.commit()

    print(f"체결 주문 {len(orders)}건 조회 → 신규 매수 {len(added)}건 반영")
    for item in added:
        fx = f" @{item['fx']:,.0f}원" if item.get("fx") else ""
        print(f"  {item['trade_date']} {item['ticker']:<8} "
              f"{item['qty']:>10,.4f}주 x {item['price']:>10,.2f}{item['currency']}{fx}")
    if skipped_dup:
        print(f"  이미 반영된 주문 {skipped_dup}건 건너뜀")
    if invalid:
        print(f"  매수 아님·미체결 {invalid}건 제외")
    if unknown:
        uniq = sorted(set(unknown))
        print(f"  이 앱이 다루지 않는 종목 {len(uniq)}종 제외: {', '.join(uniq[:10])}")
        print("    ETF만 추적합니다. 필요하면 etf_master 에 추가하세요.")
    if args.dry_run:
        print("(dry-run — 저장하지 않았습니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
