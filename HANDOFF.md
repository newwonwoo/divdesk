# HANDOFF — Claude Code 첫 세션에서 읽을 문서

작성 2026-07-30 / 이관 전 위치: claude.ai 채팅 세션
먼저 `CLAUDE.md` 를 읽어라. 이 문서는 "지금 당장 뭘 할지"만 담는다.

---

## 0. 이관 직후 30분

```bash
# ① 코드 올리기 (EC2에서)
mkdir -p ~/divdesk && cd ~/divdesk        # tar 풀거나 git clone
git init && git add -A && git commit -m "init: 스키마·어댑터·미국수집기"

# ② 의존성
python3 -m venv .venv && source .venv/bin/activate
make install

# ③ Postgres
sudo apt install -y postgresql
sudo -u postgres createuser divdesk -P
sudo -u postgres createdb -O divdesk divdesk
cp .env.example .env && chmod 600 .env     # DSN 채우기
set -a && source .env && set +a
make db

# ④ 검증 게이트가 도는지 확인
make verify                                # 4단계 전부 통과해야 함

# ⑤ 미국 수집 실적재
make collect
```

`make collect` 가 21종목 성공을 찍으면 이관 완료다.

---

## 1. 첫 실제 작업

MVP 코딩은 전부 끝났다. 남은 건 배포와 2차 과제다.
`make probe` 는 이제 필수가 아니다 — 국내 수집이 야후 `.KS` 로 해결되어
네이버 엔드포인트에 의존하지 않는다.

배포 후 첫 확인:
```bash
make collect     # 미국 21 + 국내 10
make serve &     # API
make score       # 스코어 산출
curl -s localhost:8000/scores | head
```

---

## 2. 남은 코딩 리스트

```
[x]  전 항목 완료 (16/16)
[x]  1. Postgres 스키마 + tax_param 시딩
[x]  2. 소스 어댑터 레이어 + 계약검증 + raw_snapshot
[x]  3. 수집기 A 미국 — 야후 + stockanalysis 교차검증
[x]  4. 수집기 B 국내 — 야후 .KS 경유
[x]  5. 국내 분배금 + 지급주기 데이터 도출
[ ]  6. FastAPI 골격 + 조회 API
[ ]  7. 세금 엔진 3모드 + 단위테스트
[ ]  8. 정방향 계산 API (금액 → 세후 월배당)
[ ]  9. 역방향 계산 API (목표배당 → 필요금액·정수 주수 루프)
[x] 10. 스코어 엔진 배치 + 근거문장 생성
[x] 11. React 골격 — docs/divdesk-mockup.html 컴포넌트화
[x] 12. 계산기 화면 연동
[x] 13. 타점 화면 연동 + 커버드콜 배지
[x] 14. 매수기록 CRUD
[x] 15. 금융소득 워치독
[x] 16. 12개월 입금 스트립 (확정/추정 구분)
```
2차: 배당예상일지 캘린더 / `holiday_kr` 적재 / 웹푸시 SW+VAPID / 알람 규칙 UI

---

## 3. 이미 밟은 함정 (다시 밟지 마라)

| 함정 | 사실 |
|---|---|
| TTM 배당금을 "최근 370일"로 자름 | 지급일이 밀리면 1회 더 잡혀 배당률 과대. HDV 3.03%→2.37%. **횟수로 자를 것** |
| `dividendhistory.net` 을 교차검증 소스로 | 503 반환. 후보에서 제외했다 |
| 남이 Vercel에 올린 공개 API 직접 호출 | 수명·레이트리밋·검증 불가. 수집 로직만 참고하고 직접 긁는다 |
| 분배금 지급주기를 사람이 안다고 가정 | **3회 반복된 결함.** 기간절단 과대계산, 국내 3종 분기→월 오등록. 이제 `infer_pays_per_year()` 로 이력에서 도출 |
| 종목코드를 이름으로 추정 | 476850을 RISE 미국배당100으로 등록했으나 실제는 KoAct 배당성장액티브. 야후 등록명으로 반드시 대조 |
| 국내 배당 캘린더를 미국 규칙으로 계산 | 국내는 지급기준일(월말/월중15일) 기준이고 분배락과 지급일 사이 공백이 연휴 때 최대 1주. `holiday_kr` 없이는 계산 금지 |
| 커버드콜 고배당을 좋은 점수로 처리 | 분배금에 옵션 프리미엄·원금환급이 섞여 총수익이 마이너스일 수 있다. 배지 강제 |

---

## 4. 세금 모델 요약 (7번 작업용)

| 모드 | 분배금 | 매매차익 | 비고 |
|---|---|---|---|
| `US_TAXABLE` 일반계좌·미국상장 | 현지 15% 원천징수. 한국 14%보다 높아 통상 추가납부 없음 | 양도세 22%, 연 250만 공제, 분리과세 | 지방세 1.4%분은 외국납부세액공제 처리에 따라 달라짐 → 실효 15%로 계산하고 화면에 주석 |
| `KR_TAXABLE` 일반계좌·국내상장 | 15.4% 원천징수 | **매매차익도 배당소득으로 15.4%** | 2025년부터 외국납부세액 선환급 폐지 → 실효세율 상승 반영 |
| `KR_SHELTER` 절세계좌 | 즉시 과세 없음(과세이연) | 동일 | 국내상장만 편입 가능 → `kr_alt_ticker` 로 대체종목 제시 |

공통: 연 금융소득 2,000만원 초과 시 종합과세(누진). 워치독은 80% 도달 시 경고.
**세율 상수는 전부 `tax_param` 테이블에서 읽는다. 코드에 숫자를 쓰지 마라.**
2026년 배당소득 분리과세 개정 논의가 진행 중이므로 값 교체가 SQL 한 줄로 끝나야 한다.

---

## 5. 데이터 소스 현황

| 소스 | 용도 | 상태 (2026-07-30 실측) |
|---|---|---|
| `query1.finance.yahoo.com/v8/finance/chart/{sym}?events=div` | 미국 가격·배당·USDKRW | **검증 OK, 21/21 성공, 무인증** |
| `stockanalysis.com/etf/{sym}/dividend/` | 미국 배당 교차검증 | 200 OK, 느슨한 정규식 파싱 |
| `query1.finance.yahoo.com/.../{코드}.KS` | **국내 시세·분배금** | **검증 OK, 10/10 성공, 원화** |
| `finance.naver.com/api/...` | 국내 교차검증(선택) | 미검증, priority 60으로 격하 |
| `data.krx.co.kr` | — | 403, 제외 |
| `dividendhistory.net` | — | 503, 제외 |
