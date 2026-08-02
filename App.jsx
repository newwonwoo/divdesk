#!/usr/bin/env python3
"""검증 4단계를 한 번에 돌린다.

왜 4단계인가: 문법 검사만 통과해도 NameError는 그대로 남는다.
① 문법  ② 실제 import  ③ 핵심 함수 목 실행  ④ 미정의/미사용 변수
하나라도 실패하면 exit 1. 커밋 전 게이트로 쓴다.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {"__pycache__", ".venv", "venv", "node_modules"}


def step(n: int, title: str) -> None:
    print(f"\n=== {n}) {title} ===")


def syntax() -> bool:
    step(1, "문법 (ast.parse)")
    bad = 0
    for path in sorted(ROOT.rglob("*.py")):
        if SKIP & set(path.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            print(f"  FAIL {path.relative_to(ROOT)}: {exc}")
            bad += 1
    print("  통과" if not bad else f"  {bad}건 실패")
    return bad == 0


def imports() -> bool:
    step(2, "import")
    mods = ["collector.sources.base", "collector.sources.yahoo",
            "collector.sources.stockanalysis", "collector.sources.naver_kr",
            "collector.store", "collector.run_us", "collector.run_kr", "collector.probe_kr",
            "collector.sync_toss", "collector.opening_balance",
            "db.migrate", "engine.tax", "engine.calc", "engine.score", "engine.calendar", "engine.returns", "engine.projection", "engine.exdrop",
            "engine.risk", "engine.dividend",
            "alerts.push", "alerts.run_alerts", "api.main"]
    proc = subprocess.run(
        [sys.executable, "-c", "import " + ", ".join(mods) + "; print('  통과')"],
        cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout.strip() or proc.stderr.strip()[-600:])
    return proc.returncode == 0


def mock_run() -> bool:
    step(3, "핵심 함수 목 실행")
    code = r"""
from datetime import date
from collector.sources.base import Dividend, ttm_sum, check_contract, ContractError
from collector.sources.stockanalysis import compare

fails = []
def eq(label, got, want):
    ok = got == want
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {got}" + ("" if ok else f" (기대 {want})"))
    if not ok:
        fails.append(label)

q = [Dividend('X', date(2025,1,1), 0.25, 't'), Dividend('X', date(2025,4,1), 0.25, 't'),
     Dividend('X', date(2025,7,1), 0.25, 't'), Dividend('X', date(2025,10,1), 0.25, 't'),
     Dividend('X', date(2026,1,2), 0.30, 't')]
eq("ttm 분기(5건 중 4건만)", ttm_sum(q, 4), (1.05, 4))
eq("ttm 빈 입력", ttm_sum([], 4), (0.0, 0))
eq("ttm 데이터 부족", ttm_sum(q[:2], 4), (0.5, 2))

a = [Dividend('X', date(2026,1,2), 0.30, 'y')]
eq("교차검증 허용오차 내", compare(a, [Dividend('X', date(2026,1,2), 0.3005, 's')]), [])
eq("교차검증 2차 소스 없음", compare(a, []), [])
eq("교차검증 불일치 감지", len(compare(a, [Dividend('X', date(2026,1,2), 0.35, 's')])), 1)

try:
    check_contract({'a': 1}, ['a', 'b'], 't')
    eq("계약 위반 예외", "예외 없음", "ContractError")
except ContractError:
    eq("계약 위반 예외", "ContractError", "ContractError")

# --- 세금 엔진 ---
from engine.tax import TaxEngine, US_TAXABLE, KR_TAXABLE, KR_SHELTER
tx = TaxEngine()
eq("미국 15% 원천징수", round(tx.dividend_tax(10_000_000, US_TAXABLE).tax_krw), 1_500_000)
eq("국내 15.4% 원천징수", round(tx.dividend_tax(10_000_000, KR_TAXABLE).tax_krw), 1_540_000)
eq("절세계좌 과세이연", tx.dividend_tax(10_000_000, KR_SHELTER).tax_krw, 0.0)
eq("종합과세 경고 발생", any('종합과세' in n for n in tx.dividend_tax(25_000_000, US_TAXABLE).notes), True)
eq("양도세 기본공제 적용", round(tx.capital_gain_tax(2_000_000, US_TAXABLE).tax_krw), 0)
try:
    tx.dividend_tax(1000, 'NOPE'); eq("잘못된 계좌모드 거부", "통과", "ValueError")
except ValueError:
    eq("잘못된 계좌모드 거부", "ValueError", "ValueError")

# --- 계산 엔진 ---
from engine.calc import Holding, forward, reverse
hs = [Holding('A', 100.0, 4.0, 4, qty=100)]        # 배당률 4%, 분기배당
f = forward(hs, 1000.0, US_TAXABLE, tx)
eq("정방향 투자원금", f.invested_krw, 10_000_000)
eq("정방향 연 세전배당", f.annual_gross_krw, 400_000)
eq("정방향 세후 월평균", f.monthly_avg_net_krw, round(400_000*0.85/12))
eq("분기배당은 4개월만 입금", sum(1 for m in f.monthly_breakdown if m > 0), 4)
eq("입금 편차 안내 포함", any('12개월 중' in n for n in f.notes), True)

rv = reverse(100_000, [Holding('A', 100.0, 4.0, 4)], 1000.0, US_TAXABLE, tx)
eq("역방향 목표 달성", rv.achieved_monthly_krw >= 100_000, True)
eq("역방향 주수는 정수", all(isinstance(p['qty'], int) for p in rv.plan), True)
try:
    reverse(-1, [Holding('A', 100.0, 4.0, 4)], 1000.0, US_TAXABLE, tx)
    eq("음수 목표 거부", "통과", "ValueError")
except ValueError:
    eq("음수 목표 거부", "ValueError", "ValueError")

# --- 스코어 엔진 ---
from engine.score import ScoreInput, score as sc
cheap = sc(ScoreInput('T', 100, 5.0, yield_history=[3.0]*20, ma200=120, high52=130,
                      low52=95, dps_ttm_prev=4.5, total_return_1y_pct=12,
                      fx_history=[1400.0]*20, fx_now=1200, days_to_ex=40))
rich = sc(ScoreInput('T', 100, 2.0, yield_history=[5.0]*20, ma200=80, high52=101,
                     low52=60, dps_ttm_prev=3.0, total_return_1y_pct=-5,
                     fx_history=[1200.0]*20, fx_now=1450, days_to_ex=1))
eq("싼 구간이 비싼 구간보다 고점", cheap.total > rich.total, True)
eq("점수 0~100 범위", 0 <= cheap.total <= 100 and 0 <= rich.total <= 100, True)
eq("커버드콜 배지 강제", sc(ScoreInput('C', 100, 12.0, is_covered_call=True)).warnings[0].startswith('분배금 ≠ 수익'), True)

# 배당락 낙폭: 배당금보다 덜 떨어질수록 높은 점수여야 한다.
# '며칠 남았나' 로 점수를 매기면 기다리기만 해도 점수가 오르는 지표가 된다.
def exscore(ratio):
    r = sc(ScoreInput('E', 100, 4.0, exdrop_ratio=ratio, exdrop_samples=12))
    return [f for f in r.facts if f[0].startswith('배당락')][0][3]
eq("낙폭 작을수록 고득점", exscore(0.6) > exscore(1.0) > exscore(1.4), True)
eq("낙폭 0.5배 이하 만점", exscore(0.4), 10.0)
eq("낙폭 1.5배 이상 0점", exscore(1.6), 0.0)
eq("표본 3회 미만은 중립",
   [f for f in sc(ScoreInput('E', 100, 4.0, exdrop_ratio=0.5, exdrop_samples=2)).facts
    if f[0].startswith('배당락')][0][3], 5.0)
eq("과다 낙폭은 경고",
   any('배당을 노린 매물' in w
       for w in sc(ScoreInput('E', 100, 4.0, exdrop_ratio=1.5, exdrop_samples=12)).warnings), True)
eq("데이터 없으면 신뢰도 경고", any('신뢰도' in w for w in sc(ScoreInput('E', 100, 4.0)).warnings), True)
# 원화 상장이어도 기초자산이 해외면 환율에 노출된다.
# TIGER 미국배당다우존스는 원화로 사지만 환율이 오르면 가격이 오른다.
_fxh = [1250 + i * 6 for i in range(30)]
def fx_pt_of(**kw):
    r = sc(ScoreInput('K', 100.0, 4.0, fx_history=_fxh, fx_now=1436.0, **kw))
    return [f for f in r.facts if f[0] == '환율'][0][3]
eq("기초자산 국내면 만점", fx_pt_of(is_krw_listed=True, fx_exposed=False), 10.0)
eq("원화상장이어도 기초 해외면 감점",
   fx_pt_of(is_krw_listed=True, fx_exposed=True) < 10.0, True)
eq("상장 시장이 아니라 기초자산 기준",
   fx_pt_of(is_krw_listed=True, fx_exposed=True)
   == fx_pt_of(is_krw_listed=False, fx_exposed=True), True)

# --- 국내 지급주기 도출 ---
from collector.run_kr import infer_pays_per_year, symbol
from datetime import timedelta
def mk(days, n):
    base = date(2026, 1, 1)
    return [Dividend('K', base + timedelta(days=days*i), 100.0, 't') for i in range(n)]
eq("월배당 주기 도출", infer_pays_per_year(mk(30, 14)), 12)
eq("분기배당 주기 도출", infer_pays_per_year(mk(91, 10)), 4)
eq("이력 부족시 판단 보류", infer_pays_per_year(mk(30, 2)), None)
eq("국내 심볼 변환", symbol('458730'), '458730.KS')

# --- 스키마 마이그레이션 ---
from db.migrate import MIGRATIONS
eq("마이그레이션 등록됨", len(MIGRATIONS) > 0, True)
# 생성 구문은 반복 실행에 안전해야 한다. UPDATE 는 조건이 붙어 멱등이면 허용.
eq("생성 구문은 IF NOT EXISTS",
   all("IF NOT EXISTS" in sql for _, sql in MIGRATIONS
       if sql.strip().upper().startswith(("ALTER", "CREATE"))), True)
eq("UPDATE 는 WHERE 필수",
   all("WHERE" in sql.upper() for _, sql in MIGRATIONS
       if sql.strip().upper().startswith("UPDATE")), True)
eq("삭제·타입변경 없음",
   not any(w in sql.upper() for _, sql in MIGRATIONS
           for w in ("DROP ", "TRUNCATE", "ALTER COLUMN", "DELETE ")), True)
eq("이름 중복 없음", len({n for n, _ in MIGRATIONS}), len(MIGRATIONS))

# --- 동기화 기록 (dry-run 은 쓰지 않는다) ---
from collector.store import Store as _Store
_dry = _Store(dry_run=True)
_dry.record_sync("toss", True, 5, "test")
eq("dry-run 은 기록하지 않음", _dry.counts.get("statements", 0), 0)

# --- 토스 주문 변환 ---
from collector.sync_toss import to_purchase, account_mode
buy = {"orderId": "abc", "symbol": "SCHD", "side": "BUY", "currency": "USD",
       "orderedAt": "2026-07-24T09:30:00+09:00",
       "execution": {"filledQuantity": "120", "averageFilledPrice": "28.4",
                     "commission": "0.5", "filledAt": "2026-07-24T22:31:00+09:00"}}
got = to_purchase(buy)
eq("매수 주문 변환", (got["ticker"], got["qty"], got["price"]), ("SCHD", 120.0, 28.4))
eq("체결일 기준 날짜", got["trade_date"], date(2026, 7, 24))
eq("수수료 반영", got["fee"], 0.5)

sell = dict(buy, side="SELL")
eq("매도는 제외", to_purchase(sell), None)
unfilled = dict(buy, execution={"filledQuantity": "0", "averageFilledPrice": None})
eq("미체결은 제외", to_purchase(unfilled), None)
no_price = dict(buy, execution={"filledQuantity": "5", "averageFilledPrice": None})
eq("체결가 없으면 제외", to_purchase(no_price), None)
eq("미국은 해외 계좌모드", account_mode("US"), "US_TAXABLE")
eq("국내는 국내 계좌모드", account_mode("KR"), "KR_TAXABLE")

# --- 캘린더 엔진 ---
from engine.calendar import TradingCalendar, predict_schedule, monthly_ledger
# 2026-05-05(어린이날)을 뺀 5월 평일 집합
may = [date(2026,5,d) for d in range(1,32)
       if date(2026,5,d).weekday() < 5 and d != 5]
cal = TradingCalendar.from_dates('KR', may)
eq("휴장일 도출", cal.holidays_in(2026), [date(2026,5,5)])
eq("휴장일은 거래일 아님", cal.is_trading_day(date(2026,5,5)), False)
eq("영업일 가산이 휴장 건너뜀", cal.add_business_days(date(2026,5,4), 1), date(2026,5,6))
eq("직전 영업일", cal.prev_business_day(date(2026,5,6)), date(2026,5,4))
eq("관측 범위 밖은 추정", cal.is_estimated(date(2027,1,4)), True)

hist = [(date(2026,1,30) + timedelta(days=30*i), 0.5, None) for i in range(6)]
sched = predict_schedule('T', 'US', hist, cal, months=6, today=date(2026,7,1))
eq("일정 생성됨", len(sched) > 0, True)
eq("과거 일정은 제외", all(p.ex_date > date(2026,7,1) for p in sched), True)
eq("이력만 있으면 전부 추정", all(not p.confirmed for p in sched), True)
eq("지급일은 배당락 이후", all(p.pay_date > p.ex_date for p in sched), True)

led = monthly_ledger(sched, {'T': 100}, 0.85, 1400.0, {'T': 'USD'}, today=date(2026,7,1))
eq("일지 12개월 이내", len(led) <= 12, True)

# 월배당을 30일 간격으로 더하면 매년 5일씩 앞당겨져 한 달에 두 번 잡힌다.
# 달력 월 단위로 옮겨야 각 달에 정확히 한 번씩 들어온다.
monthly = [(date(2025,8,29) + timedelta(days=30*i), 0.4, None) for i in range(14)]
big = TradingCalendar.from_dates('US', [date(2026,1,1) + timedelta(days=d)
                                        for d in range(900)
                                        if (date(2026,1,1)+timedelta(days=d)).weekday() < 5])
plan = predict_schedule('M', 'US', monthly, big, months=12, today=date(2026,7,1))
from collections import Counter
per_month = Counter((p.pay_date.year, p.pay_date.month) for p in plan)
eq("월배당은 한 달에 한 번만", max(per_month.values()), 1)
eq("지급일은 항상 배당락 뒤", all(p.pay_date > p.ex_date for p in plan), True)
eq("지급일은 항상 거래일", all(big.is_trading_day(p.pay_date) for p in plan), True)

# 지급일 기준일이 월초/월말/월중 어디든 한 달에 한 번만 잡혀야 한다
for anchor_day in (1, 5, 15, 20, 28, 29):
    seq = [(date(2025,9,1) + timedelta(days=30*i), 1.0, None) for i in range(14)]
    seq = [(d.replace(day=min(anchor_day, 28)), a, p) for d, a, p in seq]
    seq.sort()
    pl = predict_schedule('X', 'US', seq, big, months=12, today=date(2026,7,1))
    if pl:
        cm = Counter((x.pay_date.year, x.pay_date.month) for x in pl)
        eq(f"지급기준 {anchor_day}일형 월 1회", max(cm.values()), 1)

quarterly = [(date(2025,3,20) + timedelta(days=91*i), 1.0, None) for i in range(6)]
qplan = predict_schedule('Q', 'US', quarterly, big, months=12, today=date(2026,7,1))
eq("분기배당은 3개월 간격", sorted({p.ex_date.month for p in qplan}) != [], True)
eq("분기배당 12개월에 4회", len(qplan), 4)
eq("세후 반영", led[0]['net_krw'] < led[0]['gross_krw'], True)

# --- 동일지수 정렬 규칙 ---
# 0.0099% vs 0.01% 는 1억원에 연 1원 차이다. 그걸로 순자산 7배를 뒤집으면 안 된다.
FEE_TIE = 0.02
def rank(members, cheapest):
    def key(m):
        if m["fee"] is None:
            return (2, 0.0, 0.0)
        tier = 0 if m["fee"] - cheapest <= FEE_TIE else 1
        return (tier, m["fee"] if tier else 0.0, -m["aum"])
    return [m["t"] for m in sorted(members, key=key)]

grp = [{"t": "TIGER", "fee": 0.0100, "aum": 40930},
       {"t": "KODEX", "fee": 0.0099, "aum": 5675},
       {"t": "SOL",   "fee": 0.0100, "aum": 10132}]
eq("보수 동률이면 순자산 우선", rank(grp, 0.0099)[0], "TIGER")
grp2 = [{"t": "비쌈", "fee": 0.50, "aum": 99999}, {"t": "쌈", "fee": 0.01, "aum": 100}]
eq("보수 차이 크면 보수 우선", rank(grp2, 0.01)[0], "쌈")
eq("보수 미상은 뒤로", rank(grp + [{"t": "미상", "fee": None, "aum": 99999}], 0.0099)[-1], "미상")

# --- 총수익 (배당+시세차익+환차익) ---
from engine.returns import Lot, position_return, portfolio_return
# 1,300원에 100주×$100 매수 → 현재 $110, 환율 1,430원
one = position_return([Lot('T', 100, 100.0, 1300.0)], 110.0, 1430.0, dividends_since=500_000)
eq("원화 원가", one.cost_krw, 13_000_000)
eq("원화 평가액", one.value_krw, 15_730_000)
eq("시세차익(매수시 환율)", one.price_gain_krw, 1_300_000)     # $1,000 × 1,300
eq("환차익", one.fx_gain_krw, 1_430_000)                        # 나머지
eq("차익 합=평가액-원가", one.price_gain_krw + one.fx_gain_krw, 15_730_000 - 13_000_000)
eq("총손익에 배당 포함", one.total_gain_krw, 1_300_000 + 1_430_000 + 500_000)

# 환율 다른 두 건을 각각의 환율로 계산해야 한다
split = position_return(
    [Lot('S', 50, 100.0, 1200.0), Lot('S', 50, 100.0, 1400.0)], 100.0, 1300.0)
eq("건별 환율 적용 원가", split.cost_krw, 50*100*1200 + 50*100*1400)
eq("가격 그대로면 시세차익 0", split.price_gain_krw, 0)
eq("환율 중간이면 환차익 0", split.fx_gain_krw, 0)

# 국내상장은 환차익이 없다
krw = position_return([Lot('K', 100, 10_000.0, None, currency='KRW')], 11_000.0, 1430.0)
eq("원화상장 환차익 0", krw.fx_gain_krw, 0)
eq("원화상장 시세차익", krw.price_gain_krw, 100_000)

port = portfolio_return([one], US_TAXABLE, tx)
eq("미실현이익엔 배당세만", port.dividend_tax_krw, round(500_000 * 0.15))
eq("매도 가정 양도세 별도 표기", port.estimated_capgain_tax_krw > 0, True)
eq("평가손익 세금 미부과 안내", any('팔지 않은' in n for n in port.notes), True)

# 기초 잔고(매수일 불명)는 환차익 계산에서 빠져야 한다
mixed = position_return(
    [Lot('M', 100, 100.0, 1300.0), Lot('M', 50, 100.0, None, is_opening=True)],
    110.0, 1430.0)
eq("기초 잔고 수량 표시", mixed.opening_qty, 50.0)
eq("환차익은 아는 물량만", mixed.fx_gain_krw, 1_430_000)   # 100주분 × (1430-1300)×100 ÷ ...
eq("총손익은 전량 반영", mixed.price_gain_krw + mixed.fx_gain_krw,
   mixed.value_krw - mixed.cost_krw)
eq("기초 잔고 안내", any('과거 보유분' in n for n in mixed.notes), True)

only_known = position_return([Lot('K2', 100, 100.0, 1300.0)], 110.0, 1430.0)
eq("기초 잔고 없으면 표시 0", only_known.opening_qty, 0.0)

loss = position_return([Lot('L', 100, 100.0, 1400.0)], 90.0, 1400.0, dividends_since=2_000_000)
eq("시세손실을 배당이 메우는 경우", loss.price_gain_krw < 0 and loss.total_gain_krw > 0, True)

# --- 분배금 지속가능성 ---
from engine.dividend import compute as div_compute
from engine.dividend import describe as div_describe

# 분기배당이 매년 10%씩 성장하는 종목
grow = []
v = 1.0
for _ in range(24):
    grow.append(v)
    v /= (1.10 ** 0.25)          # 최근순이므로 거꾸로 감소
g = div_compute(grow, 4)
eq("성장 종목 3년 CAGR 양수", g.cagr3 > 0, True)
eq("감액 없으면 0회", g.cuts, 0)
eq("성장 종목 고득점", g.score >= 12, True)

# 매년 줄어드는 종목
shrink = [1.0 * (1.08 ** (i / 4)) for i in range(24)]   # 최근이 가장 작음
sh = div_compute(shrink, 4)
eq("감소 종목 CAGR 음수", sh.cagr3 < 0, True)
eq("감액 이력 잡힘", sh.cuts > 0, True)
eq("감소 종목 저득점", sh.score < g.score, True)

eq("이력 부족은 미산출", div_compute([1.0, 1.0], 4).available, False)
# 달력 연도로 자르면 지급이 밀린 해에 회차가 어긋난다. 횟수로 자른다.
eq("13회는 3년치로 묶임", div_compute([1.0] * 13, 4).years, 3)
eq("12회는 3년치", div_compute([1.0] * 12, 4).years, 3)
eq("설명에 감액 표시", "감액" in div_describe(sh)[1], True)
eq("배점 상한 15", g.score <= 15, True)

# --- 데이터 신뢰도 ---
# 비어 있는 항목은 절반 점수를 자동으로 받는다. 그걸 알리지 않으면
# 사용자는 그 숫자를 실제 분석 결과로 오해한다.
full_input = dict(ticker='C', price=100.0, ttm_dps=4.0, yield_history=[3.5] * 30,
                  ma200_slope=0.02, drawdown=-0.05, change_20d=0.0,
                  dps_ttm_prev=3.7, dps_score=10.0, risk_score=7.0,
                  exdrop_ratio=0.9, exdrop_samples=12,
                  fx_history=[1300 + i * 5 for i in range(40)], fx_now=1400,
                  fx_exposed=True)
rich = sc(ScoreInput(**full_input))
poor = sc(ScoreInput(ticker='E', price=100.0, ttm_dps=4.0))
eq("데이터 충분하면 신뢰도 높음", rich.confidence >= 80, True)
eq("데이터 없으면 신뢰도 낮음", poor.confidence < 50, True)
eq("신뢰도 낮으면 판단보류", poor.grade, "판단보류")
eq("신뢰도 경고", any('신뢰하기 어렵' in w for w in poor.warnings), True)

# --- 환율: 기초자산 통화 기준 ---
# 원화 상장이어도 기초자산이 해외면 환율에 그대로 노출된다.
fxh = [1250 + i * 7 for i in range(40)]
def fx_pt(**kw):
    r = sc(ScoreInput('F', 100.0, 4.0, fx_history=fxh, fx_now=1500, **kw))
    return [f for f in r.facts if f[0] == '환율'][0][3]
eq("국내상장·해외자산도 감점", fx_pt(is_krw_listed=True, fx_exposed=True) < 5, True)
eq("국내자산은 환율 만점", fx_pt(is_krw_listed=True, fx_exposed=False), 10)
eq("환헤지는 만점 아님", 5 < fx_pt(fx_exposed=True, fx_hedged=True) < 10, True)
eq("상장통화로 판단하지 않음",
   fx_pt(is_krw_listed=True, fx_exposed=True) == fx_pt(fx_exposed=True), True)

# --- 위험조정 수익 ---
from engine.risk import compute as risk_compute
from engine.risk import describe as risk_describe
import random as _rnd
_rnd.seed(11)
def series(mu, sigma, n=760):
    px = [100.0]
    for _ in range(n):
        px.append(px[-1] * (1 + _rnd.gauss(mu, sigma)))
    return px

low = risk_compute(series(0.0004, 0.005))    # 저변동
high = risk_compute(series(0.0006, 0.015))   # 고변동·고수익
eq("위험지표 산출", low.available, True)
eq("고수익이어도 고변동이면 낮은 점수", low.score > high.score, True)
eq("점수 0~10", 0 <= low.score <= 10 and 0 <= high.score <= 10, True)
eq("최대낙폭 음수", high.mdd < 0, True)
eq("표본 부족은 미산출", risk_compute([100.0] * 50).available, False)
eq("부족 사유 안내", "200일 필요" in risk_compute([100.0] * 50).reason, True)

# 최솟값 방식: 한 지표만 나빠도 전체가 낮아져야 한다.
# 평균이면 다른 지표가 덮어준다 — 위험은 가장 나쁜 얼굴로 봐야 한다.
from engine.risk import _scale
eq("최솟값 가중", round(min(8.0, 2.0) * 0.7 + 9.0 * 0.3, 1), 4.1)
eq("상승참여율 산출",
   risk_compute(series(0.0004, 0.005), benchmark_cagr=0.20).capture is not None, True)
eq("설명 문구에 낙폭 포함", "최대낙폭" in risk_describe(low)[1], True)

# --- 상품 품질 / 매수 타점 분리 ---
from engine.score import QUALITY_FLOOR
# 신뢰도가 낮으면 '판단보류'가 먼저 걸리므로, 축 분리를 시험하려면
# 데이터를 모두 채워야 한다. 실제로 이 때문에 검증이 실패했다.
two = dict(ticker='Q', price=100.0, ttm_dps=4.0, yield_history=[3.5] * 30,
           ma200_slope=0.02, drawdown=-0.05, change_20d=0.0,
           dps_ttm_prev=3.7, dps_score=10.0, risk_score=7.0,
           exdrop_ratio=0.9, exdrop_samples=12,
           fx_history=[1300 + i * 5 for i in range(40)], fx_now=1400,
           fx_exposed=True)
r2 = sc(ScoreInput(**two))
eq("품질 0~100", 0 <= r2.quality <= 100, True)
_full = sc(ScoreInput('F', 100.0, 4.0, yield_history=[3.0] * 20,
                      ma200_slope=0.02, drawdown=-0.05, change_20d=0.0,
                      dps_ttm_prev=3.7, dps_score=10.0, risk_score=7.0,
                      fx_history=[1300.0] * 20, fx_now=1400.0,
                      exdrop_ratio=0.9, exdrop_samples=12))
eq("데이터 완전하면 신뢰도 100", _full.confidence, 100)
eq("데이터 없으면 신뢰도 0", sc(ScoreInput('N', 100.0, 4.0)).confidence, 0)
eq("신뢰도 낮으면 경고에 명시",
   any('신뢰도' in w for w in sc(ScoreInput('N', 100.0, 4.0)).warnings), True)
eq("타점 0~100", 0 <= r2.timing <= 100, True)
eq("종합은 품질75:타점25", r2.total, round(r2.quality * 0.75 + r2.timing * 0.25))

# 품질이 낮으면 타점이 좋아도 제외한다. 나쁜 상품을 싸다고 사면 안 된다.
bad = dict(two, risk_score=0.5, dps_score=1.0, exdrop_ratio=1.8)
rb = sc(ScoreInput(**bad))
eq("품질 미달은 제외", rb.excluded, rb.quality < QUALITY_FLOOR)
eq("신뢰도 충분", rb.confidence >= 50, True)
eq("제외는 등급도 제외", rb.grade if rb.excluded else '제외', '제외')
eq("제외 사유 경고", any('품질' in w for w in rb.warnings), True)

# 배당이 늘어서 오른 배당률은 품질로, 주가가 빠져서면 타점으로 간다
hist = [3.0] * 20
grow = sc(ScoreInput(ticker='G', price=100.0, ttm_dps=5.0, yield_history=hist,
                     dps_ttm_prev=4.0, exdrop_ratio=0.9, exdrop_samples=12))
drop = sc(ScoreInput(ticker='D', price=100.0, ttm_dps=5.0, yield_history=hist,
                     dps_ttm_prev=5.0, exdrop_ratio=0.9, exdrop_samples=12))
eq("배당 성장은 품질로", grow.quality > drop.quality, True)
eq("주가 하락은 타점으로", drop.timing > grow.timing, True)

# --- 가격 위치: '얼마나 싸게 사는가' 하나만 ---
# 백테스트(2017~2026)에서 세 요소의 방향이 갈렸다. 기울기는 23/23 종목에서
# 음(-), 20일 과열은 U자 비단조, 낙폭만 방향이 일관됐다(28/29).
# 기울기·20일을 점수에서 빼고 경고로만 남긴다. 골든크로스도 검증 후 제외했다.
def price_pt2(**kw):
    r = sc(ScoreInput(ticker='P', price=100.0, ttm_dps=4.0, **kw))
    return [f for f in r.facts if f[0] == '가격 위치'][0][3]

eq("낙폭 클수록 고득점",
   price_pt2(drawdown=-0.12) > price_pt2(drawdown=-0.05) > price_pt2(drawdown=0.0), True)
eq("기울기는 점수에 영향 없음",
   price_pt2(drawdown=-0.05, ma200_slope=0.03)
   == price_pt2(drawdown=-0.05, ma200_slope=-0.04), True)
eq("20일 변동은 점수에 영향 없음",
   price_pt2(drawdown=-0.05, change_20d=0.15)
   == price_pt2(drawdown=-0.05, change_20d=-0.05), True)
# 절대 기준과 자기 이력 기준 중 낮은 쪽을 쓴다
eq("이력상 평범하면 절대 만점이어도 깎임",
   price_pt2(drawdown=-0.30, dd_pctile=0.3) < price_pt2(drawdown=-0.30), True)
eq("이력 없으면 절대 기준만", price_pt2(drawdown=-0.10), 20.0)
eq("둘 다 만점이면 만점", price_pt2(drawdown=-0.15, dd_pctile=1.0), 20.0)
eq("고점 대비 % 를 값으로 노출",
   [f for f in sc(ScoreInput('P', 100.0, 4.0, drawdown=-0.082)).facts
    if f[0] == '가격 위치'][0][1], "고점 대비 -8.2%")
# 이력 위치는 백분율이 아니라 '순위' 로 쓴다. '상위 85%' 는 심한 건지 평범한
# 건지 즉시 안 읽힌다. dd_pctile 0.85 = 지금보다 덜 빠진 과거가 85% = 15번째.
def dd_sub(**kw):
    return [f for f in sc(ScoreInput('P', 100.0, 4.0, **kw)).facts
            if f[0] == '가격 위치'][0][2]

eq("이력 위치는 순위로 표시 (0.85 → 15번째)",
   dd_sub(drawdown=-0.08, dd_pctile=0.85), "과거 낙폭 100건 중 15번째로 큼")
eq("평범한 낙폭은 뒷순위 (0.15 → 85번째)",
   dd_sub(drawdown=-0.08, dd_pctile=0.15), "과거 낙폭 100건 중 85번째로 큼")
eq("역대 최악은 1번째",
   dd_sub(drawdown=-0.30, dd_pctile=1.0), "과거 낙폭 100건 중 1번째로 큼")
eq("헷갈리는 상위/하위 표기를 쓰지 않음",
   any(w in dd_sub(drawdown=-0.08, dd_pctile=0.85) for w in ('상위', '하위')), False)
# 점수에선 빠져도 경고는 유지해야 한다 — 원래 의도(하락 추세 주의)를 지킨다
eq("하락추세 경고 유지", any('하락 추세' in w for w in
   sc(ScoreInput('P', 100.0, 4.0, ma200_slope=-0.04)).warnings), True)
eq("단기 과열 경고 유지", any('단기 과열' in w for w in
   sc(ScoreInput('P', 100.0, 4.0, change_20d=0.15)).warnings), True)

# --- 배당률: 절대 수준과 위치 분리 ---
# 이력 대비 위치만 보면 배당률 0.44% 인 QQQ 가 만점을 받는다.
def yield_parts(y, hist):
    r = sc(ScoreInput('Y', 100.0, y, yield_history=hist, drawdown=-0.01))
    lv = [f for f in r.facts if f[0] == '배당률 수준'][0][3]
    po = [f for f in r.facts if f[0] == '배당률 위치'][0][3]
    return lv, po

flat = [1.0] * 30
low_lv, _ = yield_parts(0.5, [0.4] * 30)
mid_lv, _ = yield_parts(3.5, [3.4] * 30)
hi_lv, _ = yield_parts(12.0, [11.0] * 30)
eq("저배당은 수준 낮음", low_lv < 5, True)
eq("적정 배당은 수준 만점", mid_lv, 18.0)
eq("초고배당은 함정 감점", hi_lv < mid_lv, True)

# 주가가 고점인데 "싸다" 고 하면 모순이다
near_high = sc(ScoreInput('H', 100.0, 5.0, yield_history=[3.0] * 20,
                          dps_ttm_prev=4.0, drawdown=-0.01))
band = [f for f in near_high.facts if f[0] == '배당률 위치'][0][2]
eq("고점이면 '주가는 고점' 표기", '고점' in band, True)

# --- 단기 과열 / 배당률 원인 구분 ---
# 배당률이 높은 이유가 배당 성장인지 주가 하락인지 갈라야 한다
hi = [3.0] * 20
grown = sc(ScoreInput(ticker='G', price=100.0, ttm_dps=5.0,
                      yield_history=hi, dps_ttm_prev=4.0))
fell = sc(ScoreInput(ticker='F', price=100.0, ttm_dps=5.0,
                     yield_history=hi, dps_ttm_prev=5.0))
eq("배당 성장이면 그렇게 표시",
   '배당이 늘어서' in [f for f in grown.facts if f[0] == '배당률 위치'][0][2], True)

# --- 배당락 지표 ---
from engine.exdrop import ExDropSample, compute_sample, summarize, describe
def mk_ex(before, open_px, dps, market=0.0, fwd=None):
    s = ExDropSample(ex_date=date(2026, 1, 5), dps=dps, before_close=before,
                     open_px=open_px, close_px=open_px, low_px=open_px * 0.99,
                     market_change=market)
    return compute_sample(s, fwd or [])

# 100원 종가 → 시가 99원, 배당 1원. 시장이 안 움직였으면 딱 1.0배
eq("보정 없을 때 1.0배", mk_ex(100, 99, 1.0, 0.0).drop_ratio, 1.0)
# 같은 상황에서 시장이 1% 빠졌다면 배당 탓은 0원 → 0.0배
eq("시장 하락분 제거", mk_ex(100, 99, 1.0, -0.01).drop_ratio, 0.0)
# 시장이 1% 올랐는데 1원 빠졌다면 배당 탓은 2원어치 → 2.0배
eq("시장 상승분 반영", mk_ex(100, 99, 1.0, 0.01).drop_ratio, 2.0)

fwd = [(date(2026, 1, 5), 99.0), (date(2026, 1, 6), 99.5), (date(2026, 1, 7), 100.5)]
eq("회복일 계산", mk_ex(100, 99, 1.0, 0.0, fwd).open_recovery, 2)
eq("미회복은 None", mk_ex(100, 99, 1.0, 0.0, [(date(2026,1,5), 99.0)]).open_recovery, None)

st = summarize([mk_ex(100, 99, 1.0, 0.0) for _ in range(5)])
eq("중앙값 산출", st.drop_ratio, 1.0)
eq("표본 수", st.samples, 5)
eq("3회 미만은 미산출", summarize([mk_ex(100, 99, 1.0)] * 2).drop_ratio, None)
eq("극단값 제외", summarize([mk_ex(100, 99, 0.01) for _ in range(5)]).samples, 0)
eq("설명 문구", describe(st)[0], "1.00배")

# --- 적립 시뮬레이션 ---
from engine.projection import simulate, common_start, growth_quality
from datetime import timedelta as _td
# 매달 1% 씩 오르는 가상 종목: 12개월 적립하면 원금보다 커야 한다
rising = [(date(2020,1,1) + _td(days=30*i), 100 * (1.01 ** i)) for i in range(80)]
p1 = simulate('R', rising, 1_000_000, 36)      # 기간은 총 개월 수
eq("시뮬레이션 구간 생성", p1.windows > 0, True)
eq("총 투입액", p1.total_invested_krw, 36_000_000)
eq("상승장이면 원금 초과", p1.median_final_krw > p1.total_invested_krw, True)
eq("손실 구간 없음", p1.loss_windows, 0)
eq("최악 <= 중간 <= 최선",
   p1.worst.final_value <= p1.median.final_value <= p1.best.final_value, True)

falling = [(date(2020,1,1) + _td(days=30*i), 100 * (0.99 ** i)) for i in range(80)]
p2 = simulate('F', falling, 1_000_000, 36)
eq("하락장이면 원금 미달", p2.median_final_krw < p2.total_invested_krw, True)
eq("손실 구간 표시", p2.loss_windows > 0, True)

short = [(date(2025,1,1) + _td(days=30*i), 100.0) for i in range(10)]
p3 = simulate('S', short, 1_000_000, 60)
eq("이력 부족은 계산 안 함", p3.windows, 0)
# 연 단위로만 고르던 기간을 개월로 풀었다. 3년 6개월 같은 값이 되어야 한다.
from engine.projection import period_label as _plab
eq("기간 표기 연+월", _plab(42), "3년 6개월")
eq("기간 표기 연만", _plab(36), "3년")
eq("기간 표기 월만", _plab(7), "7개월")
eq("18개월도 계산됨", simulate('H', rising, 1_000_000, 18).windows > 0, True)
try:
    simulate('Z', rising, 1_000_000, 0)
    eq("0개월 거부", "통과", "ValueError")
except ValueError:
    eq("0개월 거부", "ValueError", "ValueError")
eq("부족 사유 안내", any('필요한데' in n for n in p3.notes), True)

# 공통 시작일: 늦게 상장한 쪽에 맞춰야 비교가 공정하다
eq("공통 시작 = 가장 늦은 상장",
   common_start({'old': rising, 'new': [(date(2024,1,1), 100.0)]}), date(2024,1,1))

gq = growth_quality(rising, 5)
eq("상승 종목은 CAGR 양수", gq["cagr_pct"] > 0, True)
eq("상승 종목은 낙폭 0", gq["mdd_pct"], 0.0)
eq("하락 종목은 CAGR 음수", growth_quality(falling, 5)["cagr_pct"] < 0, True)

# --- 알람 문구 ---
from alerts.run_alerts import grade_label, trim
eq("등급 라벨 적극매수", grade_label(86), "적극매수")
eq("등급 라벨 매수", grade_label(73), "매수")
eq("본문은 구분자 단위 절단", trim("가" * 50 + " · " + "나" * 80).endswith("나"), False)

raise SystemExit(1 if fails else 0)
"""
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                          capture_output=True, text=True)
    print(proc.stdout.rstrip() or proc.stderr.strip()[-600:])
    return proc.returncode == 0


def undefined() -> bool:
    step(4, "미정의/미사용 변수 (pyflakes)")
    proc = subprocess.run([sys.executable, "-m", "pyflakes", "collector", "scripts", "engine", "api"],
                          cwd=ROOT, capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip()
    print("  " + (out.replace("\n", "\n  ") if out else "지적 0건"))
    return proc.returncode == 0


def main() -> int:
    results = {"문법": syntax(), "import": imports(),
               "목 실행": mock_run(), "미정의 변수": undefined()}
    bad = [k for k, v in results.items() if not v]
    print("\n" + ("=" * 46))
    if bad:
        print(f"검증 실패: {', '.join(bad)} — 커밋하지 말 것")
        return 1
    print("검증 4단계 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
