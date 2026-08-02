"""배당락일 지표.

배당락일에 주가가 떨어지는 이유는 두 가지가 섞여 있다.
  ① 배당금을 뗐으니 당연히 떨어지는 몫
  ② 그날 시장 전체가 움직인 몫

②를 빼지 않으면 배당률이 낮은 종목일수록 시장 잡음에 휩쓸린다.
실제로 QQQ(배당률 0.44%)가 "배당금의 -2.87배" 라는 무의미한 값을 냈다.
그래서 같은 날 기준 지수가 움직인 만큼을 빼고 ①만 남긴다.

시점은 **시가**를 쓴다. 배당락은 개장 시점에 가격에 반영되고 그 뒤는 일반 매매다.
장중 등락까지 넣으면 배당락이 아닌 것을 재게 된다.

내는 값 (점수는 낙폭 배수 하나만, 나머지는 표시용):
  drop_ratio     시장보정 낙폭 ÷ 배당금. 1.0 이면 배당금만큼만 떨어진 정상
  open_recovery  당일 시가에서 전날 종가를 회복하기까지 걸린 거래일
  close_recovery 당일 종가에서 전날 종가를 회복하기까지 걸린 거래일
  intraday_gap   (당일 종가 − 당일 저가) ÷ 전날 종가. 장중에 얼마나 되돌렸는지
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

# 회복일을 이 거래일 넘게 찾지 않는다. 그 이상이면 배당락과 무관한 흐름이다.
RECOVERY_LIMIT = 40


@dataclass
class ExDropSample:
    ex_date: object
    dps: float
    before_close: float
    open_px: float | None
    close_px: float | None
    low_px: float | None
    market_change: float | None      # 기준 지수의 당일 변동률 (0.012 = +1.2%)
    drop_ratio: float | None = None
    open_recovery: int | None = None
    close_recovery: int | None = None
    intraday_gap: float | None = None


@dataclass
class ExDropStat:
    samples: int = 0
    drop_ratio: float | None = None        # 중앙값. 점수 대상
    open_recovery: float | None = None     # 중앙값 거래일
    close_recovery: float | None = None
    intraday_gap: float | None = None      # 중앙값 %
    unrecovered: int = 0                   # 한도 안에 회복 못 한 횟수
    detail: list = field(default_factory=list)


def compute_sample(sample: ExDropSample, forward_prices: list) -> ExDropSample:
    """한 번의 배당락을 계산한다.

    forward_prices: [(날짜, 종가), ...] — 배당락 당일부터 이후 거래일 순서
    """
    before = sample.before_close
    if before <= 0 or sample.dps <= 0:
        return sample

    # 시장이 움직인 만큼을 빼고 배당 때문에 떨어진 몫만 남긴다.
    #
    # market_change 가 -1% 면 시장 탓 하락이 before×1% 다. 그만큼은 배당 탓이
    # 아니므로 실제 하락에서 **빼야** 한다. 부호가 음수이니 그대로 더하면
    # 오히려 늘어난다 — 그래서 절댓값이 아니라 부호를 살려 뺄셈으로 처리한다.
    #   보정낙폭 = (전날종가 - 시가) + before × market_change
    market_drop = -before * (sample.market_change or 0.0)   # 시장 탓 하락분
    if sample.open_px is not None:
        raw_drop = before - sample.open_px
        sample.drop_ratio = round((raw_drop - market_drop) / sample.dps, 3)

    if sample.low_px is not None and sample.close_px is not None:
        sample.intraday_gap = round((sample.close_px - sample.low_px) / before * 100, 3)

    # 전날 종가를 다시 넘어서기까지 걸린 거래일
    for idx, (_, close) in enumerate(forward_prices[:RECOVERY_LIMIT]):
        if close is not None and close >= before:
            if sample.open_recovery is None:
                sample.open_recovery = idx
            sample.close_recovery = idx
            break
    return sample


def summarize(samples: list) -> ExDropStat:
    """여러 배당락을 모아 중앙값을 낸다.

    평균이 아니라 중앙값을 쓰는 이유: 배당락일에 시장이 크게 흔들린 한두 번이
    평균을 통째로 왜곡한다. 중앙값은 그런 이상치에 둔감하다.
    """
    stat = ExDropStat()
    valid = [s for s in samples if s.drop_ratio is not None]
    # 배당락과 무관한 급등락이 섞인 구간은 버린다
    valid = [s for s in valid if -1.0 <= s.drop_ratio <= 4.0]
    stat.samples = len(valid)
    if len(valid) < 3:
        return stat

    stat.drop_ratio = round(statistics.median(s.drop_ratio for s in valid), 3)

    recovered = [s.open_recovery for s in valid if s.open_recovery is not None]
    if recovered:
        stat.open_recovery = round(statistics.median(recovered), 1)
    else:
        stat.open_recovery = None       # 한 번도 회복 못 함
    closed = [s.close_recovery for s in valid if s.close_recovery is not None]
    if closed:
        stat.close_recovery = round(statistics.median(closed), 1)
    stat.unrecovered = sum(1 for s in valid if s.open_recovery is None)

    gaps = [s.intraday_gap for s in valid if s.intraday_gap is not None]
    if gaps:
        stat.intraday_gap = round(statistics.median(gaps), 2)

    stat.detail = [{
        "ex_date": s.ex_date, "drop_ratio": s.drop_ratio,
        "open_recovery": s.open_recovery, "intraday_gap": s.intraday_gap,
    } for s in valid[:6]]
    return stat


def describe(stat: ExDropStat) -> tuple[str, str]:
    """(값, 부연) 문자열. 화면이 그대로 쓴다."""
    if stat.drop_ratio is None:
        return "표본 부족", f"배당락 {stat.samples}회분만 확인됨"

    ratio = stat.drop_ratio
    if ratio < 0.8:
        verdict = "배당금보다 덜 떨어짐"
    elif ratio <= 1.2:
        verdict = "배당금만큼 떨어짐"
    else:
        verdict = "배당금보다 더 떨어짐"

    parts = [verdict]
    if stat.open_recovery is None:
        parts.append(f"{RECOVERY_LIMIT}거래일 안에 회복 못 함")
    else:
        parts.append(f"회복 {stat.open_recovery:g}일")
        if stat.unrecovered:
            parts.append(f"미회복 {stat.unrecovered}회")
    return f"{ratio:.2f}배", " · ".join(parts)
