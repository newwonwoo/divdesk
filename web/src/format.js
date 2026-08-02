// 화면 전체가 쓰는 표시 규칙. 한 곳에 모아 두면 형식이 어긋나지 않는다.

// 원화. 소수점 없음.
export const won = (n) =>
  n == null || Number.isNaN(Number(n)) ? '—' : Math.round(Number(n)).toLocaleString('ko-KR')

// 달러. 소수점 2자리.
export const usd = (n) =>
  n == null || Number.isNaN(Number(n)) ? '—'
    : Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

// 수량. 소수점 매수를 하면 0.2070주 같은 값이 나온다.
// 반올림해서 0으로 보이면 데이터가 틀린 줄 알게 되므로, 작은 값일수록 자릿수를 늘린다.
export const qty = (n) => {
  const v = Number(n)
  if (n == null || Number.isNaN(v)) return '—'
  if (Number.isInteger(v)) return v.toLocaleString('ko-KR')
  if (Math.abs(v) < 1) return v.toFixed(4)
  if (Math.abs(v) < 100) return v.toFixed(2)
  return Math.round(v).toLocaleString('ko-KR')
}

// 부호를 붙인 원화. 이익은 초록, 손실은 붉은색으로 쓰라는 뜻의 색상값도 같이 준다.
export const signed = (n) => {
  const v = Number(n) || 0
  return { text: `${v > 0 ? '+' : ''}${won(v)}`, color: v > 0 ? 'var(--in)' : v < 0 ? 'var(--out)' : undefined }
}

export const pct = (n, digits = 2) =>
  n == null || Number.isNaN(Number(n)) ? '—' : `${Number(n).toFixed(digits)}%`

export const signedPct = (n, digits = 2) => {
  const v = Number(n) || 0
  return `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`
}

// 입력창용. 타이핑 중에도 세 자리마다 쉼표를 넣는다.
export const commafy = (raw) => {
  const digits = String(raw).replace(/[^0-9]/g, '')
  return digits ? Number(digits).toLocaleString('ko-KR') : ''
}
export const uncomma = (raw) => Number(String(raw).replace(/[^0-9]/g, '')) || 0

// 종목 표시. 국내는 티커가 숫자라 이름 없이는 알아볼 수 없다.
export const label = (item) => {
  if (!item) return ''
  const name = item.name || ''
  if (!name) return item.ticker
  return item.market === 'KR' ? name : `${item.ticker} ${name}`
}

// 국내는 브랜드가 곧 종목 구분이다. TIGER·KODEX 를 지우면
// "고배당주"·"고배당"만 남아 어느 상품인지 알 수 없다. 전체 이름을 쓴다.
export const shortLabel = (item) => {
  if (!item) return ''
  if (item.market === 'KR') return item.name || item.ticker
  return item.ticker
}

export const MODES = [
  { key: 'US_TAXABLE', label: '일반계좌 · 미국상장', short: '일반·미국' },
  { key: 'KR_TAXABLE', label: '일반계좌 · 국내상장', short: '일반·국내' },
  { key: 'KR_SHELTER', label: '절세계좌 (ISA·연금)', short: '절세계좌' },
]

export const GRADE = (n) =>
  n == null ? { cls: 's-none', text: '미산출' }
    : n >= 85 ? { cls: 's-buy', text: '적극매수' }
    : n >= 70 ? { cls: 's-buy', text: '매수' }
    : n >= 55 ? { cls: 's-hold', text: '관망' }
    : { cls: 's-wait', text: '보류' }
