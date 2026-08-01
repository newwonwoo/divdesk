// 빌드는 통과하지만 실행하면 죽는 참조를 잡는다.
// 부모에서 prop 전달을 끊었는데 자식이 계속 참조하면 화면이 통째로 안 뜬다.
// 실제로 그 사고가 났고, 빌드만으로는 발견되지 않았다.
const fs = require('fs')
const src = fs.readFileSync('src/App.jsx', 'utf8')

const KNOWN = new Set([
  'React', 'api', 'DOC', 'won', 'usd', 'qty', 'signed', 'pct', 'signedPct',
  'commafy', 'uncomma', 'label', 'shortLabel', 'MODES', 'GRADE',
  'useState', 'useEffect', 'useCallback', 'enablePush', 'disablePush',
  'isSubscribed', 'pushStatus', 'InfoBtn', 'Sheet', 'Notes', 'Err', 'Loading',
  'MonthStrip', 'Metric', 'AGO', 'today', 'PAGE', 'TABS', 'MONTH_LABEL',
  'Signed', 'gradeOf', 'SyncStatus', 'Reconcile', 'PushSetting', 'Duplicates',
  'Screener', 'Calculator', 'Projection', 'Calendar', 'Ledger', 'Returns',
  'Dashboard', 'Builder', 'App', 'window', 'Date', 'Math', 'Number',
  'Object', 'Array', 'JSON', 'console', 'fetch', 'document', 'navigator',
])

let bad = 0
const fnRe = /function (\w+)\(\{([^}]*)\}\)\s*\{/g
let m
while ((m = fnRe.exec(src))) {
  const [, name, propsRaw] = m
  const start = m.index
  // 함수 본문 끝을 중괄호 균형으로 찾는다
  let depth = 0, i = src.indexOf('{', start + m[0].length - 1), end = i
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++
    else if (src[i] === '}') { depth--; if (depth === 0) { end = i; break } }
  }
  const body = src.slice(start, end)
  const declared = new Set([
    ...propsRaw.split(',').map(p => p.split(':')[0].split('=')[0].trim()),
    ...[...body.matchAll(/const \[(\w+),\s*(\w+)\]/g)].flatMap(x => [x[1], x[2]]),
    ...[...body.matchAll(/(?:const|let|var)\s+(\w+)\s*=/g)].map(x => x[1]),
    ...[...body.matchAll(/\((\w+)\)\s*=>/g)].map(x => x[1]),
    ...[...body.matchAll(/\.map\(\((\w+)/g)].map(x => x[1]),
  ].filter(Boolean))

  // 부모가 전달을 끊기 쉬운 prop 만 본다. 속성 접근(a.items)은 제외해야 오탐이 없다.
  for (const id of ['mode', 'etfs', 'onDoc', 'onChanged', 'reloadKey']) {
    const used = new RegExp(`[^.\\w'"\`]${id}\\b(?!\\s*:)`).test(body.slice(m[0].length))
    if (used && !declared.has(id) && !KNOWN.has(id)) {
      console.error(`  ✗ ${name}: '${id}' 를 쓰는데 정의가 없습니다`)
      bad++
    }
  }
}
console.log(bad ? `\n미정의 참조 ${bad}건 — 화면이 안 뜹니다` : '컴포넌트 참조 검사 통과')
process.exit(bad ? 1 : 0)
