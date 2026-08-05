"""스키마 마이그레이션.

왜 필요한가: `schema.sql` 은 `CREATE TABLE IF NOT EXISTS` 라서, 이미 있는 테이블에
컬럼을 추가하지 못한다. 그래서 기능을 추가할 때마다 사람이 `ALTER TABLE` 을
따로 실행해야 했고, 그걸 잊으면 서버가 500 을 뱉었다. 실제로 여러 번 그랬다.

이 파일은 **서버가 켜질 때 스스로 스키마를 맞춘다.** 새 컬럼이 필요하면
아래 MIGRATIONS 에 한 줄만 추가하면 되고, 배포할 때 사람이 할 일은 없다.

원칙:
- 전부 `IF NOT EXISTS` 로 쓴다. 몇 번을 돌려도 안전해야 한다.
- 컬럼 추가와 인덱스 생성만 한다. 삭제·타입 변경은 하지 않는다.
  데이터가 사라지는 작업을 자동으로 돌리면 안 된다.
- 실패해도 서버는 뜬다. 마이그레이션 하나 때문에 전체가 죽으면 더 나쁘다.
"""
from __future__ import annotations

import logging

log = logging.getLogger("divdesk.migrate")

# 순서대로 실행된다. 새 컬럼은 맨 아래에 추가한다.
MIGRATIONS: list[tuple[str, str]] = [
    ("etf_master.is_benchmark",
     "ALTER TABLE etf_master ADD COLUMN IF NOT EXISTS is_benchmark boolean DEFAULT false"),
    ("etf_master.expense_ratio",
     "ALTER TABLE etf_master ADD COLUMN IF NOT EXISTS expense_ratio numeric(6,4)"),
    ("etf_price_daily.adj_close",
     "ALTER TABLE etf_price_daily ADD COLUMN IF NOT EXISTS adj_close numeric(18,4)"),
    ("etf_price_daily.open",
     "ALTER TABLE etf_price_daily ADD COLUMN IF NOT EXISTS open numeric(18,4)"),
    ("etf_price_daily.low",
     "ALTER TABLE etf_price_daily ADD COLUMN IF NOT EXISTS low numeric(18,4)"),
    ("purchase.is_opening_balance",
     "ALTER TABLE purchase ADD COLUMN IF NOT EXISTS is_opening_balance boolean DEFAULT false"),
    ("score_snapshot.facts",
     "ALTER TABLE score_snapshot ADD COLUMN IF NOT EXISTS facts jsonb"),
    ("sync_log",
     """CREATE TABLE IF NOT EXISTS sync_log (
          id bigserial PRIMARY KEY,
          source text NOT NULL,
          ok boolean NOT NULL,
          added int DEFAULT 0,
          message text,
          ran_at timestamptz DEFAULT now()
        )"""),
    ("sync_log.index",
     "CREATE INDEX IF NOT EXISTS ix_sync_recent ON sync_log(source, ran_at DESC)"),
    ("push_subscription",
     """CREATE TABLE IF NOT EXISTS push_subscription (
          id bigserial PRIMARY KEY,
          endpoint text UNIQUE NOT NULL,
          payload jsonb NOT NULL,
          user_agent text,
          enabled boolean DEFAULT true,
          created_at timestamptz DEFAULT now()
        )"""),
    # 컬럼을 나중에 추가하면 기존 행은 기본값으로 남는다. 마이그레이션이
    # 컬럼은 만들어도 값은 못 채운다. 실제로 is_benchmark 가 전부 false 로
    # 남아 벤치마크가 매수 후보 목록에 섞여 나왔다.
    ("benchmark.backfill",
     """UPDATE etf_master SET is_benchmark = true
        WHERE ticker IN ('SPY','VOO','QQQ','069500') AND is_benchmark = false"""),
    ("alert_log",
     """CREATE TABLE IF NOT EXISTS alert_log (
          id bigserial PRIMARY KEY,
          ticker text,
          kind text NOT NULL,
          message text,
          delivered int DEFAULT 0,
          fired_at timestamptz DEFAULT now()
        )"""),
]


def run(conn) -> dict:
    """마이그레이션을 전부 시도하고 결과를 돌려준다.

    개별 실패는 삼키고 계속 간다. 하나가 막혀서 서버가 안 뜨는 것보다,
    뜬 다음에 그 기능만 오류를 내는 편이 고치기 쉽다.
    """
    applied, failed = [], []
    for name, sql in MIGRATIONS:
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            applied.append(name)
        except Exception as exc:                              # noqa: BLE001
            conn.rollback()
            failed.append((name, f"{type(exc).__name__}: {exc}"))
            log.warning("마이그레이션 실패 %s: %s", name, exc)

    if failed:
        log.warning("스키마 %d건 적용, %d건 실패", len(applied), len(failed))
    else:
        log.info("스키마 %d건 확인 완료", len(applied))
    return {"applied": len(applied), "failed": failed}


def main(argv: list[str] | None = None) -> int:
    """`python -m db.migrate` 진입점.

    서버가 뜰 때 `api.main` 이 같은 `run()` 을 부르므로 평소엔 사람이 할 일이
    없다. 그런데 배포 문서(HANDOFF 3절)는 이 명령을 직접 돌리라고 안내하고
    있었고, **진입점이 없어 아무 일도 하지 않고 조용히 성공한 것처럼 끝났다.**
    돌렸다고 믿고 재수집까지 했다가 컬럼이 없어 실패하는 게 최악이라 만든다.
    """
    import os

    import psycopg                                            # 지연 import

    dsn = os.environ.get("DIVDESK_DSN",
                         "postgresql://divdesk@localhost:5432/divdesk")
    with psycopg.connect(dsn) as conn:
        result = run(conn)

    print(f"스키마 {result['applied']}건 적용 / 실패 {len(result['failed'])}건")
    for name, reason in result["failed"]:
        print(f"  ✗ {name}: {reason}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
