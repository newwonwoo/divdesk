const BASE = import.meta.env.VITE_API_BASE || '/api'

async function req(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  let body = null
  try { body = await res.json() } catch { /* 본문 없는 응답 */ }
  if (!res.ok) {
    // 서버가 왜 거절했는지 그대로 보여준다. 삼키지 않는다.
    const detail = body?.detail
    const msg = Array.isArray(detail)
      ? detail.map(d => d.msg).join(', ')
      : (detail || `요청 실패 (${res.status})`)
    throw new Error(msg)
  }
  return body
}

export const api = {
  health: () => req('/health'),
  etfs: (market) => req('/etfs' + (market ? `?market=${market}` : '')),
  scores: () => req('/scores'),
  forward: (payload) => req('/calc/forward', { method: 'POST', body: JSON.stringify(payload) }),
  reverse: (payload) => req('/calc/reverse', { method: 'POST', body: JSON.stringify(payload) }),
  purchases: () => req('/purchases'),
  addPurchase: (p) => req('/purchases', { method: 'POST', body: JSON.stringify(p) }),
  delPurchase: (id) => req(`/purchases/${id}`, { method: 'DELETE' }),
  portfolio: (mode) => req(`/portfolio?account_mode=${mode}`),
  returns: (mode) => req(`/portfolio/returns?account_mode=${mode}`),
  watchdog: () => req('/watchdog'),
  calendar: (mode) => req(`/calendar?account_mode=${mode}`),
  holidays: (market, year) => req(`/calendar/holidays?market=${market}&year=${year}`),
  pushKey: () => req('/push/key'),
  pushTest: () => req('/push/test', { method: 'POST' }),
  alerts: () => req('/alerts'),
  syncStatus: () => req('/sync/status'),
}

export const won = (n) =>
  n == null || Number.isNaN(n) ? '—' : Math.round(n).toLocaleString('ko-KR')

export const MODES = [
  { key: 'US_TAXABLE', label: '일반·미국상장' },
  { key: 'KR_TAXABLE', label: '일반·국내상장' },
  { key: 'KR_SHELTER', label: '절세계좌' },
]

// ⓘ 버튼이 여는 설명. "간결하되 추가설명은 버튼으로" 요구사항의 실체.
export const DOC = {
  dir: ['계산 방향',
    <>
      <p>두 방향 모두 같은 세금 규칙을 씁니다.</p>
      <p><b>금액 → 월배당</b>: 원금을 넣으면 세후 월평균과 월별 입금 편차를 보여줍니다.</p>
      <p><b>월배당 → 필요금액</b>: 목표 월배당을 넣으면 필요 원금과 종목별 주수를 역산합니다.
        주식은 정수로만 살 수 있어 내림한 뒤 부족분을 다시 채웁니다.</p>
    </>],
  avg: ['세후 월평균 배당은 어떻게 나오나요',
    <>
      <p><code>연 세전배당 ÷ 12 × (1 − 실효세율) × 환율</code></p>
      <p>연 세전배당은 최근 지급된 분배금 합계를 보유 주수에 곱한 값입니다.
        예상치가 아니라 이미 지급된 금액 기준입니다.</p>
      <p>지급 횟수로 잘라서 계산합니다. 기간(예: 최근 1년)으로 자르면 지급일이 밀린 해에
        한 번이 더 잡혀 배당률이 부풀려집니다.</p>
    </>],
  strip: ['월별 입금이 왜 들쭉날쭉한가요',
    <>
      <p>분기배당 종목은 3·6·9·12월에만 입금됩니다. 그래서 &lsquo;월평균&rsquo;과
        &lsquo;이번 달 실제 입금&rsquo;은 다릅니다.</p>
      <p>월배당 종목을 섞으면 평탄해집니다. 다만 월배당 상품 상당수가 커버드콜이라
        분배금 안정성은 따로 봐야 합니다.</p>
    </>],
  score: ['타점 점수 계산식',
    <>
      <p>100점을 여섯 항목으로 나눕니다.</p>
      <p><code>배당률 밴드 30 · 가격 위치 20 · 분배금 건강도 20 · 총수익 정합성 10 · 환율 위치 10 · 배당락 타이밍 10</code></p>
      <p>85 이상 적극매수, 70~84 매수, 55~69 분할·관망, 55 미만 보류.</p>
      <p>배당률이 높다고 점수가 오르지 않습니다. <b>그 종목의 과거 자기 배당률 대비 지금이 싼지</b>를 봅니다.
        커버드콜은 분배금 일부가 옵션 프리미엄·원금환급이라 총수익 항목에서 감점될 수 있습니다.</p>
    </>],
  tax: ['계좌모드에 따라 세금이 왜 달라지나요',
    <>
      <p><b>일반·미국상장</b>: 현지에서 15% 원천징수. 한국 배당소득세율(14%)보다 높아
        통상 추가 납부가 없습니다. 매매차익은 별건으로 양도세 22%(연 250만원 공제, 분리과세)입니다.</p>
      <p><b>일반·국내상장</b>: 분배금 15.4% 원천징수. 국내상장 해외ETF는 매매차익도
        배당소득으로 과세되고 금융소득 한도에 합산됩니다.</p>
      <p><b>절세계좌</b>: 분배금이 즉시 과세되지 않고 이연됩니다. 다만 국내상장 ETF만 담을 수 있습니다.</p>
      <p>세율은 앱에 박혀 있지 않고 서버 설정값에서 읽습니다. 세법이 바뀌면 그 값만 갱신됩니다.</p>
    </>],
  watchdog: ['금융소득 워치독',
    <>
      <p>연간 금융소득(이자+배당)이 2,000만원을 넘으면 초과분이 다른 소득과 합산돼
        누진세율(6.6~49.5%)이 적용됩니다.</p>
      <p>기준의 80%에 닿으면 미리 알려드립니다. 이때부터는 절세계좌 활용을 검토할 시점입니다.</p>
      <p>여기 집계되는 값은 이 앱에 기록된 배당만입니다. 예금 이자 등 다른 금융소득은 포함되지 않습니다.</p>
    </>],
  total: ['총수익은 어떻게 계산하나요',
    <>
      <p><code>총수익 = 배당 + 시세차익 + 환차익</code></p>
      <p><b>시세차익</b>은 주가가 오른 몫, <b>환차익</b>은 환율이 움직인 몫입니다.
        원화 투자자에게는 이 둘을 나눠 봐야 합니다 — 주가가 그대로여도
        1,300원에 사서 1,430원이면 원화로는 이익이고, 반대면 손실입니다.</p>
      <p>나눠 산 경우 <b>매수건마다 그때의 환율</b>을 각각 적용합니다.
        평균 환율을 쓰면 환차익이 틀어집니다.</p>
      <p>시세차익·환차익은 아직 팔지 않은 평가손익이라 세금이 붙지 않았습니다.
        "지금 전부 팔면" 예상 세금은 따로 표시합니다.</p>
    </>],
  cal: ['배당예상일지는 어떻게 만드나요',
    <>
      <p>보유 종목의 과거 배당 이력에서 지급 간격을 뽑아 앞으로 12개월 일정을 만듭니다.</p>
      <p>지급일은 배당락일에서 시장 규칙으로 계산합니다. 미국은 배당락 4영업일 뒤,
        국내는 지급기준일 다음 달 초가 기준입니다.</p>
      <p>휴장일은 <b>수집된 시세에서 도출</b>합니다. 거래가 있었던 날이 거래일이고
        평일 중 빠진 날이 휴장일이라, 공휴일 표를 따로 관리하지 않아도 저절로 맞습니다.</p>
      <p><b>확정</b> 표시는 운용사가 공시한 배당이고, 나머지는 추정치입니다.
        추정 금액은 최근 4회 평균에 추세를 절반만 반영합니다 —
        커버드콜은 변동이 커서 추세를 그대로 밀면 과하게 나옵니다.</p>
    </>],
  ret: ['총수익률은 어떻게 계산하나요',
    <>
      <p>수정종가(분배금을 재투자한 것으로 보정한 가격)의 1년 전 대비 비율입니다.</p>
      <p>가격 변동에 분배금을 단순히 더하는 방식은 재투자 효과를 빼먹은 근사치라
        쓰지 않습니다. 수정종가가 없는 종목에서만 그 방식으로 물러섭니다.</p>
      <p>이 값이 분배율보다 낮으면 분배금이 원금을 깎고 있다는 신호입니다.</p>
    </>],
  push: ['매수 추천 알림',
    <>
      <p>점수가 85점 이상으로 <b>올라선 날에만</b> 보냅니다.
        매일 85점이라고 매일 보내면 알림이 소음이 되기 때문입니다.</p>
      <p>같은 종목은 14일 안에 다시 보내지 않습니다.</p>
      <p>아이폰은 <b>홈 화면에 추가한 상태</b>에서만 알림을 받을 수 있습니다.
        사파리 공유 → 홈 화면에 추가를 먼저 해주세요.</p>
    </>],
  cc: ['분배금 ≠ 수익',
    <>
      <p>커버드콜 ETF는 옵션을 팔아 받은 프리미엄을 분배금으로 나눠줍니다.
        여기에 원금 일부를 돌려주는 몫(ROC)이 섞이기도 합니다.</p>
      <p>그래서 분배율이 10%를 넘어도 <b>총수익(가격 변동 + 분배금)</b>은 낮거나 마이너스일 수 있습니다.
        기초자산이 오를 때 그 상승을 다 못 따라가는 구조이기 때문입니다.</p>
      <p>분배율만 보고 판단하지 마시고 총수익 항목을 함께 보세요.</p>
    </>],
}
