"""매수 추천 알람.

규칙은 단순하다:
  1) 점수가 임계값(기본 85) 이상으로 **올라선 날**에만 보낸다.
     매일 85점이라고 매일 보내면 알림이 소음이 되고, 소음이 되면 끄게 된다.
     그래서 "어제는 미만이었는데 오늘 넘었다"는 전이(transition)만 잡는다.
  2) 같은 종목은 쿨다운(기본 14일) 안에 다시 보내지 않는다.
  3) 배당락 D-3 알림은 보유 종목에 한해 따로 보낸다.

실행: python -m alerts.run_alerts [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from collector.store import Store
from engine.score import GRADE_BUY, GRADE_BUY_HARD, GRADE_HOLD
from . import push

DEFAULT_THRESHOLD = 85
COOLDOWN_DAYS = 14


def grade_label(total: int) -> str:
    """임계값을 낮춰 돌릴 수도 있으므로 점수에 맞는 등급을 붙인다."""
    if total >= GRADE_BUY_HARD:
        return "적극매수"
    if total >= GRADE_BUY:
        return "매수"
    return "관망" if total >= GRADE_HOLD else "보류"


def trim(reason: str, limit: int = 110) -> str:
    """알림 본문은 짧아야 한다. 다만 단어 중간에서 자르면 읽히지 않으므로
    구분자(·) 단위로 끊는다."""
    head = reason.split("⚠")[0].strip()
    if len(head) <= limit:
        return head
    parts, out = head.split(" · "), []
    for part in parts:
        if len(" · ".join(out + [part])) > limit:
            break
        out.append(part)
    return " · ".join(out) if out else head[:limit].rstrip()


def fetch(store: Store, sql: str, params: tuple = ()) -> list[dict]:
    conn = store.connect()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def crossed_up(store: Store, threshold: int) -> list[dict]:
    """오늘 임계값을 넘어섰고, 직전 산출일에는 미만이던 종목."""
    return fetch(store, """
        WITH ranked AS (
          SELECT ticker, date, total,
                 LAG(total) OVER (PARTITION BY ticker ORDER BY date) AS prev
          FROM score_snapshot
        )
        SELECT r.ticker, r.total, r.prev, m.name, m.is_covered_call,
               s.reason
        FROM ranked r
        JOIN etf_master m USING (ticker)
        JOIN score_snapshot s ON s.ticker = r.ticker AND s.date = r.date
        WHERE r.date = CURRENT_DATE
          AND r.total >= %s
          AND (r.prev IS NULL OR r.prev < %s)
        ORDER BY r.total DESC""", (threshold, threshold))


def recently_alerted(store: Store, days: int) -> set:
    rows = fetch(store, """SELECT DISTINCT ticker FROM alert_log
                           WHERE fired_at > CURRENT_DATE - %s::int
                             AND kind='score'""", (days,))
    return {r["ticker"] for r in rows}


def subscriptions(store: Store) -> list[dict]:
    return fetch(store, "SELECT id, payload FROM push_subscription WHERE enabled")


def record(store: Store, ticker: str, kind: str, message: str,
           delivered: int, dry: bool) -> None:
    if dry:
        return
    store.execute("""INSERT INTO alert_log (ticker, kind, message, delivered)
                     VALUES (%s,%s,%s,%s)""", (ticker, kind, message, delivered))


def drop_subscription(store: Store, sub_id: int) -> None:
    store.execute("UPDATE push_subscription SET enabled=false WHERE id=%s", (sub_id,))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="판정만 하고 보내지 않음")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument("--cooldown", type=int, default=COOLDOWN_DAYS)
    args = parser.parse_args(argv)

    store = Store()
    try:
        store.connect()
    except Exception as exc:                                  # noqa: BLE001
        print(f"DB 연결 실패: {type(exc).__name__}")
        return 1

    candidates = crossed_up(store, args.threshold)
    skip = recently_alerted(store, args.cooldown)
    targets = [c for c in candidates if c["ticker"] not in skip]

    print(f"{date.today()} 임계 {args.threshold}점 상향 돌파 {len(candidates)}건 "
          f"/ 쿨다운 제외 후 {len(targets)}건")

    if not targets:
        print("보낼 알림이 없습니다.")
        return 0

    subs = subscriptions(store) if not args.dry_run else []
    if not args.dry_run and not subs:
        print("등록된 푸시 구독이 없습니다. 앱에서 알림을 먼저 허용하세요.")

    for item in targets:
        warn = " · 분배금 ≠ 수익" if item["is_covered_call"] else ""
        title = f"{item['ticker']} {grade_label(item['total'])} {item['total']}점"
        body = trim(item["reason"] or "") + warn
        print(f"  → {title}\n     {body}")

        delivered = 0
        for sub in subs:
            ok, why = push.send(sub["payload"], title, body,
                                url=f"/?ticker={item['ticker']}",
                                tag=f"score-{item['ticker']}")
            if ok:
                delivered += 1
            elif why == "expired":
                drop_subscription(store, sub["id"])
                print(f"     · 만료된 구독 {sub['id']} 비활성화")
            else:
                print(f"     · 발송 실패: {why}")
        record(store, item["ticker"], "score", title, delivered, args.dry_run)

    if not args.dry_run:
        store.commit()
    print("완료" + (" (dry-run — 실제 발송 없음)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
