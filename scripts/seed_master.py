#!/usr/bin/env python3
"""etf_master 시딩.

여기 들어가는 건 '성격 분류'뿐이다 — 이름·전략·지급주기·커버드콜 여부.
주가·배당률·분배금은 절대 넣지 않는다. 그건 수집기가 채운다.

국내 종목의 추종지수·운용사는 확인됐다(index_verified). 총보수도 확인 완료(FunETF 조회).
2026-08-01 야후 .KS 조회로 10/10 실재 확인. 지급주기는 분배금 이력에서 도출한 값이다.

실행: python3 scripts/seed_master.py
"""
from __future__ import annotations

import json
import os
import sys

# (ticker, market, name, issuer, strategy, pay_freq, pays_per_year,
#  is_covered_call, kr_alt_ticker, tags)
US = [
    ("SCHD", "Schwab US Dividend Equity", "Schwab", "배당성장", "Q", 4, False, "458730",
     {"index": "Dow Jones U.S. Dividend 100", "role": "코어"}),
    ("VYM", "Vanguard High Dividend Yield", "Vanguard", "고배당", "Q", 4, False, None,
     {"role": "코어", "note": "시총가중 광범위"}),
    ("VIG", "Vanguard Dividend Appreciation", "Vanguard", "배당성장", "Q", 4, False, None,
     {"note": "10년+ 연속 증배"}),
    ("DGRO", "iShares Core Dividend Growth", "BlackRock", "배당성장", "Q", 4, False, None, {}),
    ("DVY", "iShares Select Dividend", "BlackRock", "고배당", "Q", 4, False, None,
     {"note": "중형 편중"}),
    ("SDY", "SPDR S&P Dividend", "State Street", "배당성장", "Q", 4, False, None,
     {"note": "20년+ 연속 증배"}),
    ("NOBL", "ProShares S&P500 Dividend Aristocrats", "ProShares", "배당성장", "Q", 4, False, None,
     {"note": "25년+ 연속 증배, 방어적"}),
    ("HDV", "iShares Core High Dividend", "BlackRock", "고배당", "Q", 4, False, None,
     {"note": "재무건전성 스크리닝 75종목"}),
    ("FDVV", "Fidelity High Dividend", "Fidelity", "고배당", "Q", 4, False, None,
     {"note": "고배당+성장 혼합"}),
    ("SCHY", "Schwab International Dividend Equity", "Schwab", "배당성장", "Q", 4, False, None,
     {"note": "SCHD의 미국 외 선진국 버전"}),
    ("VYMI", "Vanguard International High Dividend Yield", "Vanguard", "고배당", "Q", 4, False, None,
     {"note": "미국 외, 환분산"}),
    ("VNQ", "Vanguard Real Estate", "Vanguard", "리츠", "Q", 4, False, None,
     {"note": "배당 성격이 주식형과 다름"}),
    ("DGRW", "WisdomTree US Quality Dividend Growth", "WisdomTree", "배당성장", "M", 12, False, None,
     {"note": "퀄리티 배당성장인데 월지급"}),
    ("SPHD", "Invesco S&P500 High Dividend Low Volatility", "Invesco", "고배당", "M", 12, False, None,
     {"note": "고배당+저변동 50종목"}),
    ("PFF", "iShares Preferred & Income Securities", "BlackRock", "우선주", "M", 12, False, None,
     {"note": "금리 민감"}),
    ("DIV", "Global X SuperDividend US", "Global X", "고배당", "M", 12, False, None,
     {"note": "초고배당 50종목"}),
    ("JEPI", "JPMorgan Equity Premium Income", "JPMorgan", "커버드콜", "M", 12, True, None,
     {"note": "S&P500 + ELN"}),
    ("JEPQ", "JPMorgan Nasdaq Equity Premium Income", "JPMorgan", "커버드콜", "M", 12, True, None,
     {"note": "나스닥100 + ELN"}),
    ("QYLD", "Global X Nasdaq 100 Covered Call", "Global X", "커버드콜", "M", 12, True, None,
     {"note": "100% 커버드콜, 상승 제한"}),
    ("XYLD", "Global X S&P500 Covered Call", "Global X", "커버드콜", "M", 12, True, None, {}),
    ("RYLD", "Global X Russell 2000 Covered Call", "Global X", "커버드콜", "M", 12, True, None,
     {"note": "소형주 커버드콜"}),
]

# 국내: 종목코드·명칭은 운용사 공시로 검증 전 '후보'
KR = [
    # 아래 지수·운용사는 2026-08-01 k-etf 조회로 확인. 총보수는 미확인(운용사 공시 필요).
    ("458730", "TIGER 미국배당다우존스", "미래에셋", "배당성장", "M", 12, False,
     {"index": "Dow Jones U.S. Dividend 100 PR", "index_verified": True, "yahoo": "458730.KS", "aum_eok": 40930, "listed": "2023-06-20"}),
    ("446720", "SOL 미국배당다우존스", "신한", "배당성장", "M", 12, False,
     {"index": "Dow Jones U.S. Dividend 100 PR", "index_verified": True, "yahoo": "446720.KS", "aum_eok": 10132, "listed": "2022-11-15"}),
    ("402970", "ACE 미국배당다우존스", "한국투자", "배당성장", "M", 12, False,
     {"index": "Dow Jones U.S. Dividend 100 PR", "index_verified": True, "yahoo": "402970.KS", "aum_eok": 9350, "listed": "2021-10-21",
      "note": "야후 등록명은 S&P 계열로 나오나 실제 추종지수는 다우존스 — 옛 KINDEX 명칭 잔재"}),
    ("489250", "KODEX 미국배당다우존스", "삼성", "배당성장", "M", 12, False,
     {"index": "Dow Jones U.S. Dividend 100 PR", "index_verified": True, "yahoo": "489250.KS", "aum_eok": 5675, "listed": "2024-08-13"}),
    ("458760", "TIGER 미국배당+7%프리미엄다우존스", "미래에셋", "커버드콜", "M", 12, True,
     {"index": "Dow Jones U.S. Dividend 100 7% Premium", "index_verified": True,
      "yahoo": "458760.KS", "aum_eok": 7061, "listed": "2023-06-20"}),
    ("441640", "KODEX 미국배당프리미엄액티브", "삼성", "커버드콜", "M", 12, True,
     {"index": "S&P 500", "index_verified": True, "yahoo": "441640.KS", "aum_eok": 16333, "listed": "2022-09-27",
      "note": "이름과 달리 다우존스 배당지수가 아니라 S&P500 기반 커버드콜"}),
    ("161510", "PLUS 고배당주", "한화", "고배당", "M", 12, False,
     {"index": "FnGuide High Dividend Stocks", "index_verified": True, "yahoo": "161510.KS", "aum_eok": 23007, "listed": "2012-08-29",
      "note": "국내주식 고배당. 실측상 월배당"}),
    ("279530", "KODEX 고배당", "삼성", "고배당", "M", 12, False,
     {"index": "FnGuide High Dividend Plus", "index_verified": True, "yahoo": "279530.KS", "aum_eok": 3120, "listed": "2017-10-17",
      "note": "국내주식 고배당. 실측상 월배당"}),
    ("329200", "TIGER 리츠부동산인프라", "미래에셋", "리츠", "M", 12, False,
     {"index": "FnGuide REITs Real Estate Infrastructure", "index_verified": True,
      "yahoo": "329200.KS", "aum_eok": 15017, "listed": "2019-07-19", "note": "국내 리츠. 실측상 월배당"}),
    ("476850", "KoAct 배당성장액티브", "삼성액티브", "배당성장", "Q", 4, False,
     {"index": "KOSPI", "index_verified": True, "yahoo": "476850.KS", "aum_eok": 966, "listed": "2024-02-27",
      "note": "국내주식 액티브. 당초 RISE 미국배당100으로 잘못 등록했던 코드"}),
]

# 미국 총보수(연, %)·순자산(십억달러). 2026-08-01 stockanalysis.com 조회.
BENCHMARKS = [
    ("SPY", "SPDR S&P 500 ETF Trust", "State Street", "벤치마크", "Q", 4,
     {"note": "시장 기준. 유닛투자신탁 구조라 배당 재투자가 안 돼 총수익은 VOO보다 미세하게 뒤진다"}),
    ("VOO", "Vanguard S&P 500 ETF", "Vanguard", "벤치마크", "Q", 4,
     {"note": "S&P500 총수익 비교용. SPY보다 보수가 낮고 배당 드래그가 없다"}),
    ("QQQ", "Invesco QQQ Trust", "Invesco", "벤치마크", "Q", 4,
     {"note": "나스닥100. JEPQ·QYLD의 기초자산이라 커버드콜 성과 비교에 필요"}),
]

BENCH_FEES = {"SPY": 0.09, "VOO": 0.03, "QQQ": 0.20}

US_FEES = {'SCHD': 0.06, 'VYM': 0.04, 'VIG': 0.04, 'DGRO': 0.08, 'DVY': 0.38, 'SDY': 0.35, 'NOBL': 0.35, 'HDV': 0.08, 'FDVV': 0.15, 'SCHY': 0.08, 'VYMI': 0.07, 'VNQ': 0.13, 'DGRW': 0.28, 'SPHD': 0.3, 'PFF': 0.45, 'DIV': 0.45, 'JEPI': 0.35, 'JEPQ': 0.35, 'QYLD': 0.6, 'XYLD': 0.6, 'RYLD': 0.6}
US_AUM = {'SCHD': 103.72, 'VYM': 81.51, 'VIG': 111.71, 'DGRO': 42.86, 'DVY': 23.59, 'SDY': 23.53, 'NOBL': 11.7, 'HDV': 14.83, 'FDVV': 10.17, 'SCHY': 2.5, 'VYMI': 21.07, 'VNQ': 39.51, 'DGRW': 16.61, 'SPHD': 4.04, 'PFF': 13.18, 'DIV': 0.787, 'JEPI': 45.34, 'JEPQ': 38.86, 'QYLD': 8.03, 'XYLD': 3.21, 'RYLD': 1.36}

# 국내 총보수(연, %). 2026-08-01 FunETF(금융투자협회·코스콤 제공) 조회.
KR_FEES = {'458730': 0.01, '446720': 0.01, '402970': 0.01, '489250': 0.0099, '458760': 0.39, '441640': 0.19, '161510': 0.23, '279530': 0.3, '329200': 0.08, '476850': 0.5}


SQL = """INSERT INTO etf_master
 (ticker,market,name,issuer,strategy,pay_freq,pays_per_year,is_covered_call,
  kr_alt_ticker,tags,expense_ratio,is_benchmark)
 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
 ON CONFLICT (ticker) DO UPDATE SET
   name=EXCLUDED.name, issuer=EXCLUDED.issuer, strategy=EXCLUDED.strategy,
   pay_freq=EXCLUDED.pay_freq, pays_per_year=EXCLUDED.pays_per_year,
   is_covered_call=EXCLUDED.is_covered_call, kr_alt_ticker=EXCLUDED.kr_alt_ticker,
   tags=EXCLUDED.tags, expense_ratio=EXCLUDED.expense_ratio,
   is_benchmark=EXCLUDED.is_benchmark, updated_at=now()"""


def rows() -> list[tuple]:
    out = []
    for tk, name, issuer, strat, freq, pays, tags in BENCHMARKS:
        out.append((tk, "US", name, issuer, strat, freq, pays, False, None,
                    json.dumps(tags), BENCH_FEES.get(tk), True))
    for tk, name, issuer, strat, freq, pays, cc, alt, tags in US:
        enriched = dict(tags)
        if tk in US_AUM:
            enriched["aum_busd"] = US_AUM[tk]
        out.append((tk, "US", name, issuer, strat, freq, pays, cc, alt,
                    json.dumps(enriched), US_FEES.get(tk), False))
    for tk, name, issuer, strat, freq, pays, cc, tags in KR:
        out.append((tk, "KR", name, issuer, strat, freq, pays, cc, None,
                    json.dumps(tags), KR_FEES.get(tk), False))
    return out


def main(dsn: str | None = None) -> int:
    import psycopg
    dsn = dsn or os.environ.get("DIVDESK_DSN")
    if not dsn:
        print("DIVDESK_DSN 이 설정되지 않았습니다"); return 1
    data = rows()
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(SQL, data)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT market, count(*) FROM etf_master GROUP BY market ORDER BY 1")
            for market, cnt in cur.fetchall():
                print(f"  {market}: {cnt}종목")
    print(f"시딩 완료 {len(data)}건")
    print("국내 지수·운용사·총보수 확인 완료(2026-08-01 기준). 미국 종목 보수도 반영.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
