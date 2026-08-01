flowchart TB

  subgraph MOBILE["📱 모바일 (조정승)"]
    CC["Claude 앱<br/>Remote Control<br/>개발·운영 지시"]
    APP["DivDesk PWA<br/>계산·타점·매수기록"]
  end

  subgraph VERCEL["▲ Vercel"]
    FE["React + Vite<br/>Dashboard / Calculator<br/>Screener / Ledger<br/>공통 ⓘ 바텀시트"]
  end

  subgraph EC2["🖥 EC2 서울 43.201.133.119"]
    CLAUDE["Claude Code<br/>tmux 세션<br/>CLAUDE.md 규칙 적용"]
    API["FastAPI<br/>조회 · 계산 · CRUD"]
    ENG["계산 엔진 3<br/>① 금액→월배당<br/>② 목표배당→필요금액<br/>③ 타점 스코어 0~100"]
    CRON["cron 일 1회<br/>수집 배치"]
    ADP["소스 어댑터 레이어<br/>우선순위 폴백<br/>check_contract<br/>403·429 즉시 중단"]
    DB[("PostgreSQL<br/>etf_master · price_daily<br/>dividend_history · purchase<br/>score_snapshot · tax_param<br/>raw_snapshot · income_ledger")]
  end

  subgraph SRC["🌐 수집 소스 (인증키 0개)"]
    Y["Yahoo chart API<br/>✅ 검증 21/21<br/>미국 가격·배당·USDKRW"]
    SA["stockanalysis.com<br/>✅ 200 OK<br/>미국 배당 교차검증"]
    NV["네이버 증권 JSON<br/>⚠️ 미검증<br/>국내 시세·NAV"]
    KRX["data.krx.co.kr<br/>⚠️ OTP 2단계<br/>국내 공식 폴백"]
    SB["SEIBro · 운용사 공시<br/>⚠️ 국내 분배금"]
  end

  CC -.->|"아웃바운드 HTTPS<br/>인바운드 포트 없음"| CLAUDE
  APP --> FE
  FE -->|"REST"| API
  API --> ENG
  ENG --> DB
  API --> DB
  CLAUDE --> API
  CLAUDE --> CRON

  CRON --> ADP
  ADP --> Y
  ADP --> SA
  ADP --> NV
  ADP --> KRX
  ADP --> SB
  ADP -->|"정규화 + 원문 보관"| DB

  ADP -.->|"전 소스 실패 시<br/>'데이터 없음' 노출<br/>추정값으로 덮지 않음"| FE
  DB -.->|"tax_param 조회<br/>세율은 코드에 없음"| ENG

  classDef ok fill:#DDE6E4,stroke:#0E6F63,color:#0F1E3D
  classDef warn fill:#FBF0EA,stroke:#A63A18,color:#0F1E3D
  classDef core fill:#FFFFFF,stroke:#0F1E3D,color:#0F1E3D
  classDef store fill:#E9EDF2,stroke:#4A5872,color:#0F1E3D

  class Y,SA ok
  class NV,KRX,SB warn
  class CLAUDE,API,ENG,CRON,ADP,FE core
  class DB store
