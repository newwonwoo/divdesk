# 품질확인서 — DivDesk 코딩 1~3번

- 작성: 2026-07-30
- 대상: 1. Postgres 스키마 / 2. 소스 어댑터 레이어 / 3. 미국 수집기
- 판정: **적합 (조건부)** — 국내 소스(4·5번)는 미착수, 아래 미충족 항목 참조

## 1. 요구사항 대조

| 요구사항 | 구현 | 근거 |
|---|---|---|
| 매수기록 PostgreSQL 저장 | `purchase` 테이블 (계좌모드 CHECK 제약 포함) | db/schema.sql |
| 세금 계산 근거 외부화 | `tax_param` 테이블 + source_url 컬럼, 6개 파라미터 시딩 | db/schema.sql |
| 인증키 없는 크롤링 소스 | 야후 chart(무인증) + stockanalysis(HTML) | sources/yahoo.py, stockanalysis.py |
| 소스 이중화·불일치 감지 | 우선순위 폴백 + `compare()` 0.5% 허용오차 + `conflict` 컬럼 | run_us.py, schema.sql |
| 추정값으로 덮지 않음 | 전 소스 실패 시 실패목록에 남기고 종목 스킵, `is_estimate` 플래그 분리 | run_us.py |
| 원문 보관 | `raw_snapshot(payload jsonb)` | schema.sql, store.py |
| 차단 대응 | 403/429 시 지수 백오프 후 `SourceBlocked`, 요청 간 1.2~2.0초 | sources/base.py |
| 스키마 변경 조용한 오염 방지 | `check_contract()` 로 필수 키 검사 후 실패 처리 | sources/base.py |

## 2. 검증 절차 (4단계 전부 실행)

| 단계 | 방법 | 결과 |
|---|---|---|
| ① 문법 | 전 .py `ast.parse` | 통과 (0건 실패) |
| ② import | 7개 모듈 실제 import | 통과 |
| ③ 목 실행 | `ttm_sum` 3케이스(정상/빈값/부족), `compare` 3케이스, `check_contract` 예외 | 전부 기대값 일치 |
| ③b E2E | 실 네트워크 dry-run 5종목 | 성공 5 / 실패 0, statements=256 |
| ④ 미정의 변수 | pyflakes 전체 | exit=0, 지적 0건 |

## 3. 검증 중 발견하고 고친 결함 (중요)

**배당률 과대계산 버그.** 초기 실측에서 TTM 분배금을 "최근 370일" 기간으로 잘랐더니
지급일이 며칠 밀린 종목에서 지급 횟수가 1회 더 잡혔다.

| 종목 | 기간(370일) 방식 | 횟수 기준 방식 | 오차 |
|---|---|---|---|
| HDV | 5회 합산 → 배당률 3.03% | 4회 합산 → 2.37% | **+0.66%p 과대** |
| DGRW | 13회 합산 → 1.35% | 12회 → 1.30% | +0.05%p 과대 |

이 앱은 배당률로 매수타점을 판정하므로 0.66%p 과대는 그대로 오판으로 이어진다.
→ `ttm_sum(divs, pays_per_year)` 이 **기간이 아니라 지급횟수로** 절단하도록 수정하고,
`etf_master.pays_per_year` 를 스키마에 명시적으로 뒀다.

## 4. 미충족 / 미검증 항목 (다음 작업으로 넘김)

1. **국내 엔드포인트 전량 미검증.** 클로드 샌드박스 이그레스 정책이 naver.com 을
   `hostname_blocked` 로 차단해 실측 불가. `naver_kr.py` 는 `verified=False` 이며
   호출 시 `ContractError` 를 던져 **잘못된 값이 들어가는 것보다 실패를 선택**하게 했다.
   → EC2에서 `python -m collector.probe_kr` 실행 후 필드명 확정 필요.
2. **국내 분배금 소스 미정.** `fetch_dividends` 는 `NotImplementedError`. (리스트 5번)
3. **DB 실적재 미검증.** Postgres 미설치 환경이라 dry-run 만 확인. `psycopg` 지연 import.
   → EC2에서 `psql -f db/schema.sql` 후 `--dry-run` 없이 1회 실행 필요.
4. **stockanalysis 파서는 느슨한 정규식.** 검증 실패 시 수집을 막지 않도록 설계했으나,
   HTML 구조가 바뀌면 조용히 "교차검증 건너뜀" 이 된다. 건너뜀 비율 모니터링 필요.
5. `dividendhistory.net` 은 실측에서 503 반환 → 후보에서 제외.

## 5. EC2 배포 절차

```bash
sudo apt install -y postgresql python3-pip
sudo -u postgres createuser divdesk -P && sudo -u postgres createdb -O divdesk divdesk
psql "postgresql://divdesk@localhost/divdesk" -f db/schema.sql
pip install requests "psycopg[binary]"
export DIVDESK_DSN="postgresql://divdesk:비번@localhost:5432/divdesk"
python -m collector.probe_kr          # ① 국내 엔드포인트 실측
python -m collector.run_us --dry-run  # ② 미국 로직 확인
python -m collector.run_us            # ③ 실적재
```
