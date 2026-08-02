-- DivDesk 스키마 v1  (PostgreSQL 14+)
-- 원칙: 주가·배당률은 수집값만 저장. 세율은 코드가 아니라 tax_param 테이블.

CREATE TABLE IF NOT EXISTS etf_master (
  ticker          text PRIMARY KEY,            -- 미국:SCHD / 국내:458730
  market          text NOT NULL CHECK (market IN ('US','KR')),
  name            text NOT NULL,
  issuer          text,
  strategy        text,                        -- 배당성장/고배당/커버드콜/우선주/리츠
  pay_freq        text CHECK (pay_freq IN ('M','Q','SA','A')),
  pays_per_year   int,                         -- TTM 합산 횟수 기준 (M=12, Q=4)
  expense_ratio   numeric(6,4),
  index_name      text,
  kr_alt_ticker   text,                        -- 절세계좌 대체종목 매핑
  is_covered_call boolean DEFAULT false,       -- '분배금 ≠ 수익' 배지 강제
  is_benchmark    boolean DEFAULT false,       -- 비교 기준. 매수 후보·타점 목록에서 제외
  tags            jsonb DEFAULT '{}'::jsonb,
  updated_at      timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS etf_price_daily (
  ticker text REFERENCES etf_master(ticker),
  date   date,
  close  numeric(18,4) NOT NULL,
  adj_close numeric(18,4),      -- 분배금 재투자 보정. 총수익률 계산용
  nav    numeric(18,4),
  ma200  numeric(18,4),
  high52 numeric(18,4),
  low52  numeric(18,4),
  src    text NOT NULL,
  PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS dividend_history (
  ticker      text REFERENCES etf_master(ticker),
  ex_date     date,
  pay_date    date,
  dps         numeric(18,6) NOT NULL,
  is_estimate boolean DEFAULT false,
  src         text NOT NULL,
  conflict    boolean DEFAULT false,           -- 2개 소스 값 불일치
  PRIMARY KEY (ticker, ex_date)
);

CREATE TABLE IF NOT EXISTS fx_rate (
  date date PRIMARY KEY,
  usdkrw numeric(12,4) NOT NULL,
  src text NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase (
  id bigserial PRIMARY KEY,
  ticker text REFERENCES etf_master(ticker),
  trade_date date NOT NULL,
  qty numeric(18,6) NOT NULL CHECK (qty > 0),
  price numeric(18,4) NOT NULL,
  fx_at_buy numeric(12,4),
  fee numeric(18,4) DEFAULT 0,
  account_mode text NOT NULL CHECK (account_mode IN ('US_TAXABLE','KR_TAXABLE','KR_SHELTER')),
  memo text,
  -- 증권사 API가 주지 않는 과거 보유분. 매수일·환율을 모르므로
  -- 환차익 계산에서 제외한다. 수량과 원가만 유효하다.
  is_opening_balance boolean DEFAULT false,
  created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_purchase_ticker ON purchase(ticker, trade_date);

CREATE TABLE IF NOT EXISTS score_snapshot (
  ticker text REFERENCES etf_master(ticker),
  date date,
  total int NOT NULL,
  yield_pctile numeric(6,2),
  price_pos    numeric(6,2),
  dps_health   numeric(6,2),
  total_ret    numeric(6,2),
  fx_pos       numeric(6,2),
  exdate_pen   numeric(6,2),
  reason text,
  PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS tax_param (
  key text PRIMARY KEY,
  value numeric(14,5) NOT NULL,
  effective_from date NOT NULL,
  source_url text,
  note text
);

-- 원문 보관: 나중에 값이 이상하면 원본과 대조
CREATE TABLE IF NOT EXISTS raw_snapshot (
  id bigserial PRIMARY KEY,
  src text NOT NULL,
  ticker text,
  fetched_at timestamptz DEFAULT now(),
  payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_raw_src_time ON raw_snapshot(src, fetched_at DESC);

CREATE TABLE IF NOT EXISTS income_ledger (
  year int, month int,
  gross_krw numeric(18,0) DEFAULT 0,
  tax_krw   numeric(18,0) DEFAULT 0,
  PRIMARY KEY (year, month)
);

-- 휴장일 테이블은 두지 않는다. 수집된 시세의 '거래가 있었던 날짜'가 곧 거래일이고,
-- 평일 중 빠진 날이 휴장일이다. 별도 표를 관리하면 매년 갱신 누락으로 틀어진다.

-- 동기화 결과 기록. 화면에서 '언제 마지막으로 성공했는지'를 보여주기 위해 남긴다.
-- 조용히 멈춘 채 낡은 숫자를 보는 것이 가장 나쁜 실패 방식이다.
CREATE TABLE IF NOT EXISTS sync_log (
  id bigserial PRIMARY KEY,
  source text NOT NULL,            -- toss | us | kr
  ok boolean NOT NULL,
  added int DEFAULT 0,
  message text,
  ran_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_sync_recent ON sync_log(source, ran_at DESC);

CREATE TABLE IF NOT EXISTS push_subscription (
  id bigserial PRIMARY KEY,
  endpoint text UNIQUE NOT NULL,
  payload jsonb NOT NULL,          -- 브라우저가 준 구독 객체 전체
  user_agent text,
  enabled boolean DEFAULT true,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_log (
  id bigserial PRIMARY KEY,
  ticker text,
  kind text NOT NULL,              -- score | exdate
  message text,
  delivered int DEFAULT 0,
  fired_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_alert_recent ON alert_log(ticker, kind, fired_at DESC);

INSERT INTO tax_param(key,value,effective_from,source_url,note) VALUES
 ('us_withholding',       0.15,     '2026-01-01','https://www.irs.gov','미국 배당 원천징수 15% (한미조세조약)'),
 ('kr_dividend_tax',      0.154,    '2026-01-01','https://taxcalc.co.kr/stocks/dividend.html','소득세 14% + 지방소득세 1.4%'),
 ('kr_capgain_overseas',  0.22,     '2026-01-01','https://taxcalc.co.kr','해외상장 양도세 22%, 분리과세'),
 ('overseas_deduction',   2500000,  '2026-01-01',NULL,'해외 양도차익 연 기본공제'),
 ('fin_income_threshold', 20000000, '2026-01-01',NULL,'금융소득종합과세 기준'),
 ('watchdog_ratio',       0.80,     '2026-01-01',NULL,'기준의 80% 도달 시 경고')
ON CONFLICT (key) DO NOTHING;
