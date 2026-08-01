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
            "engine.tax", "engine.calc", "engine.score", "engine.calendar", "engine.returns", "engine.projection",
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
eq("데이터 없으면 신뢰도 경고", any('신뢰도' in w for w in sc(ScoreInput('E', 100, 4.0)).warnings), True)
eq("원화상장은 환율 항목 만점", sc(ScoreInput('K', 100, 4.0, is_krw_listed=True)).fx_pos, 10.0)

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

# --- 적립 시뮬레이션 ---
from engine.projection import simulate, common_start, growth_quality
from datetime import timedelta as _td
# 매달 1% 씩 오르는 가상 종목: 12개월 적립하면 원금보다 커야 한다
rising = [(date(2020,1,1) + _td(days=30*i), 100 * (1.01 ** i)) for i in range(80)]
p1 = simulate('R', rising, 1_000_000, 3)
eq("시뮬레이션 구간 생성", p1.windows > 0, True)
eq("총 투입액", p1.total_invested_krw, 36_000_000)
eq("상승장이면 원금 초과", p1.median_final_krw > p1.total_invested_krw, True)
eq("손실 구간 없음", p1.loss_windows, 0)
eq("최악 <= 중간 <= 최선",
   p1.worst.final_value <= p1.median.final_value <= p1.best.final_value, True)

falling = [(date(2020,1,1) + _td(days=30*i), 100 * (0.99 ** i)) for i in range(80)]
p2 = simulate('F', falling, 1_000_000, 3)
eq("하락장이면 원금 미달", p2.median_final_krw < p2.total_invested_krw, True)
eq("손실 구간 표시", p2.loss_windows > 0, True)

short = [(date(2025,1,1) + _td(days=30*i), 100.0) for i in range(10)]
p3 = simulate('S', short, 1_000_000, 5)
eq("이력 부족은 계산 안 함", p3.windows, 0)
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
