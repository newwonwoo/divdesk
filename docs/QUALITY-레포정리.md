# 품질확인서 — 레포 잔해 정리 (웹 업로드 사고 복구)

작성일 2026-08-03 · 대상 브랜치 `claude/continue-prep-410lee`
선행 상태: `HEAD = 3b89178` (= `origin/main`, 앞뒤 0커밋)

---

## 1. 배경 — 무슨 일이 있었나

`28b37e3` 에서 GitHub 웹 업로드로 파일을 끌어넣으면서 경로가 납작해졌다.
`d0514c8` 로 되돌렸으나 **되돌리기가 전부를 지우지 못해 16개가 남았다.**

남은 잔해의 성질이 문제였다. 단순한 중복 사본이 아니라 **파일명과 내용이 서로
어긋나 있었다.** 웹 업로드가 파일을 원래 이름이 아닌 자리에 배치한 결과다.

| 잔해 파일 | 실제 들어 있던 내용 |
|---|---|
| `main.py` | `web/src/App.jsx` (리액트/JSX) |
| `score.py` | `docs/QUALITY-백테스트.md` (마크다운) |
| `asof.py` | `api/main.py` |
| `App.jsx` | `engine/score.py` (파이썬) |
| `api.jsx` | `web/check.cjs` |
| `check.cjs` | `scripts/verify.py` (파이썬) |
| `divdesk-mockup.html` | `docs/QUALITY-백테스트.md` |
| `QUALITY-백테스트.md` | `web/src/api.jsx` |
| `QUALITY-타점재설계.md` | `web/src/styles.css` |
| `styles.css` | `scripts/verify.py` 의 **옛 버전** |
| `engine/App.jsx` | `engine/score.py` |
| `engine/QUALITY-백테스트.md` | `api/main.py` |
| `engine/check.cjs` | `engine/projection.py` |
| `engine/divdesk-mockup.html` | `docs/QUALITY-백테스트.md` |
| `engine/styles.css` | `scripts/verify.py` |
| `engine/verify.py` | `engine/asof.py` |

---

## 2. 요구사항 대조표

| # | 요구사항 | 결과 | 근거 |
|---|---|---|---|
| 1 | 잔해만 지우고 진짜 소스는 한 줄도 건드리지 않는다 | 충족 | 삭제 전 추적 파일 85개를 전수 md5 해시해 잔해 15개가 **살아남는 정상 파일과 바이트 단위로 동일**함을 확인. 삭제는 `git rm` 만 사용했고 소스 파일 수정은 0건 |
| 2 | 원본이 없는 파일은 지우지 않는다 | 충족 | 유일하게 쌍둥이가 없던 `styles.css` 를 `scripts/verify.py` 와 직접 diff. 차이 17줄 전부가 **현재 버전에만 있는 추가 테스트**(개월 단위 `period_label` 검사 11줄, `simulate` 인자 연→월 변경 6줄). 옛 버전이 확실하고 고유 내용 없음 |
| 3 | `make verify` 4단계 통과 | 충족 | 4단계 전부 통과 (아래 3절) |
| 4 | 프론트 참조 검사 통과 | 충족 | `cd web && node check.cjs` 통과 |
| 5 | look-ahead 차단 테스트 통과 | 충족 | `scripts/test_asof.py` 통과 |
| 6 | 채점 로직·화면 구성 변경 없음 | 충족 | 삭제 16건 + 문서 3건 외 diff 없음. 화면이 안 바뀌었으므로 `docs/divdesk-mockup.html` 갱신 대상 아님(CLAUDE.md 7항) |

---

## 3. 검증 4단계 결과

### 정리 **전** (기준선)

```
=== 1) 문법 (ast.parse) ===
  FAIL main.py: invalid character '─' (U+2500) (<unknown>, line 9)
  FAIL score.py: leading zeros in decimal integer literals are not permitted (line 3)
  2건 실패
검증 실패: 문법 — 커밋하지 말 것
```

### 정리 **후**

| 단계 | 결과 |
|---|---|
| ① 문법 (ast.parse) | 통과 |
| ② import | 통과 |
| ③ 핵심 함수 목 실행 | 통과 |
| ④ pyflakes | 통과 |
| **make verify 종합** | **검증 4단계 전부 통과** (종료코드 0) |
| `web/check.cjs` | 컴포넌트 참조 검사 통과 (종료코드 0) |
| `scripts/test_asof.py` | asof 검증 통과 (종료코드 0) |

---

## 4. 발견한 결함

### 결함 1 · HANDOFF 의 "동작에는 영향 없다" 는 오판이었다 — 수정함

HANDOFF §3 "그 밖" 은 잔해를 두고 *"동작에는 영향 없으나 정리 대상"* 이라고
기록했다. **틀렸다.** 잔해 중 `.py` 확장자를 가진 두 개가 `make verify` 의
1단계 `ROOT.rglob("*.py")` 스캔에 걸려 **커밋 게이트를 통째로 막고 있었다.**

- `main.py` 는 내용이 JSX라 `─` 문자에서 파싱 실패
- `score.py` 는 내용이 마크다운이라 `2026-08-02` 를 8진수 리터럴로 오인해 실패

즉 이 상태에서는 **어떤 코드를 고쳐도 커밋 전 게이트를 통과할 수 없었다.**
잔해 정리는 "나중에 해도 되는 미화 작업"이 아니라 다른 모든 작업의 선행 조건이었다.
HANDOFF 를 사실대로 고쳤다.

### 결함 2 · HANDOFF 1순위 기술이 낡아 있었다 — 수정함

HANDOFF §3 1순위는 *"`db/migrate.py` 에 컬럼 추가를 넣고 재수집하면 풀린다"* 고
적었으나, `db/migrate.py` 30~33행에 `open`·`low` 의 `ADD COLUMN IF NOT EXISTS`
가 **이미 들어 있다.** 코드로 할 일은 이미 끝나 있고 남은 건 EC2 에서
마이그레이션 실행 + 재수집뿐이다. 이대로 두면 다음 세션이 **이미 있는 코드를
다시 짜는** 헛수고를 한다. 사실에 맞게 정정했다.

### 결함 3 · `scripts/test_asof.py` 를 문서대로 실행하면 실패한다 — 미수정

```
$ python3 scripts/test_asof.py
ModuleNotFoundError: No module named 'engine'
```

`sys.path[0]` 이 `scripts/` 로 잡혀 `engine` 을 못 찾는다. `PYTHONPATH=.` 를
붙이면 통과한다. **이번 정리와 무관한 기존 결함**이며, `make verify` 는
`cwd=ROOT` 로 별도 프로세스를 띄우므로 영향받지 않는다. 고치려면 Makefile 에
`test-asof` 타깃을 추가하거나 스크립트 상단에서 루트를 `sys.path` 에 넣으면 된다.
**이번 커밋 범위 밖이라 손대지 않았다.**

---

## 5. 미충족 항목

| 항목 | 사유 |
|---|---|
| ④ pyflakes 를 원래 환경에서 재확인 | 이 컨테이너에 `pyflakes` 가 없어 직접 설치 후 실행했다. EC2 `.venv` 에는 `requirements.txt` 로 이미 들어 있으므로 배포 시 그대로 통과할 것으로 본다 |
| `pywebpush` / `py-vapid` 설치 | 이 컨테이너에서 `http-ece` 휠 빌드가 실패해 설치 불가. `alerts.push` 는 지연 임포트라 검증 ②단계는 영향 없이 통과했다. **환경 제약이며 코드 결함이 아니다** |
| HANDOFF 1·2순위 실작업 | Postgres 접속이 필요한데 이 컨테이너에 DB가 없다. 서버에서 해야 한다 |

---

## 6. 다음 사람이 할 일

정리는 끝났고 커밋 게이트는 열렸다. HANDOFF §3 우선순위가 그대로 남아 있다.

1. **1순위** — EC2 에서 `sync_log` 조회 → 수집이 조용히 실패 중인지 확인 →
   `python -m db.migrate` → 재수집. 풀리면 배당락 회복력 10점이 살아난다.
2. **2순위** — 국내 종목 중복 적재 확인 (1년 294행 > 거래일 약 246).
3. **3순위** — `DIVDESK_TOKEN` 이 비어 API 가 무인증 개방 상태. 보안 항목.

**재발 방지:** 코드 전달은 git 으로만 한다. 이번 사고는 웹 업로드 한 번으로
16개 파일이 이름과 내용이 어긋난 채 남았고, 되돌리기로도 전부 지워지지 않았다.
