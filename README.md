# DivDesk — 배당 ETF 매수검토기

얼마를 사면 세후 월배당이 얼마인지, 목표 월배당을 받으려면 얼마가 필요한지,
그리고 지금이 살 타점인지 점수로 판단하는 개인용 도구.

- 문서: `CLAUDE.md`(작업 규칙) → `HANDOFF.md`(지금 할 일) → `docs/`(설계·품질확인서·목업)
- 스택: Python/FastAPI + PostgreSQL (EC2) / React·Vite·Vercel / 수집은 무인증 크롤링
- 진행: 1~3번 완료. 다음은 국내 엔드포인트 실측(`make probe`)

```bash
make install     # 의존성
make db          # 스키마 적용 (DIVDESK_DSN 필요)
make verify      # 검증 4단계 — 커밋 전 필수
make probe       # 국내 엔드포인트 실측
make collect     # 미국 수집기 실적재
```

개인 학습·의사결정 참고용. 투자 판단의 책임은 사용자에게 있고,
수집 데이터는 지연·오류가 있을 수 있다.
