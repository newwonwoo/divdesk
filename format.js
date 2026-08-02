// 빌드는 통과하지만 실행하면 죽는 참조를 잡는다.
// 부모에서 prop 전달을 끊었는데 자식이 계속 참조하면 화면이 통째로 안 뜬다.
// 실제로 그 사고가 났고, 빌드만으로는 발견되지 않았다.
//
// 한계: 정규식 기반이라 스코프를 정확히 보지 못한다. 중첩 중괄호 안쪽 식별자는
// 놓칠 수 있다(타점 탭 사고 때 5개 중 3개를 잡았다). 3개만 잡아도 빌드가
// 실패하므로 게이트 역할은 하지만, "통과 = 안전" 은 아니다.
// 정확히 하려면 파서(acorn 등)가 필요하고 의존성이 늘어난다 — 지금은 이 선에서 멈춘다.
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

// 아래 둘은 '변수' 가 아니라서 미정의 검사 대상이 아니다.
// 자동 수집을 쓰면 이걸 걸러 주지 않으면 오탐이 쏟아진다.
const KEYWORDS = new Set(`
  return const let var await async function class new typeof instanceof void delete
  if else for while do switch case break continue try catch finally throw
  of in this super yield import export default from as
  true false null undefined NaN Infinity
`.trim().split(/\s+/))

// JSX 기본 태그(<div> 등)는 소문자라 식별자처럼 보인다.
const HTML_TAGS = new Set(`
  a abbr article aside b br button code col colgroup div em footer form h1 h2 h3
  h4 h5 h6 header hr i img input label li main nav ol option p path pre s section
  select small span strong style sub summary svg table tbody td textarea tfoot th
  thead tr u ul
`.trim().split(/\s+/))

// 모듈 최상위 선언(헬퍼·상수·import)도 컴포넌트 안에서 그대로 쓸 수 있다.
// 손으로 KNOWN 에 적어 두면 새 헬퍼를 추가할 때마다 오탐이 난다. 자동으로 모은다.
for (const m0 of src.matchAll(/^(?:export\s+)?(?:async\s+)?(?:const|let|var|function|class)\s+([\w$]+)/gm)) {
  KNOWN.add(m0[1])
}
for (const m0 of src.matchAll(/^import\s+(?:([\w$]+)\s*,?\s*)?(?:\{([^}]*)\})?/gm)) {
  if (m0[1]) KNOWN.add(m0[1])
  if (m0[2]) m0[2].split(',').forEach(p => KNOWN.add(p.split(' as ').pop().trim()))
}

// 문자열·주석·정규식 리터럴을 지운다. 지우지 않으면 정규식 플래그(/.../g)의 g 나
// 문자열 안 단어가 변수 참조로 잡힌다.
const strip = (s) => s
  .replace(/\/\/[^\n]*/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/'[^']*'|"[^"]*"|`[^`]*`/g, "''")
  // 정규식은 (, ',', =, : 뒤에 오는 것만 지운다. 그러지 않으면 </div> 의 슬래시를
  // 정규식 시작으로 오인해 JSX 를 망가뜨린다.
  // 치환 결과는 식별자가 아니어야 한다. /re/ 같은 걸 넣으면 re 가 미정의로 잡힌다.
  .replace(/([(,=:]\s*)\/(?![/*])(?:\\.|\[[^\]]*\]|[^/\n\\])+\/[gimsuy]*/g, '$1 0 ')

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
    // 괄호 없는 화살표 인자도 선언이다: .map(e => ...), .filter(x => ...)
    ...[...body.matchAll(/(?:^|[^.\w$])([\w$]+)\s*=>/g)].map(x => x[1]),
    // 괄호 있는 화살표 인자 전체 — 구조분해 포함.
    // .map(([k, v, sub], i) => ...) 의 k·v·sub·i 가 전부 선언이다.
    ...[...body.matchAll(/\(([^()]*)\)\s*=>/g)].flatMap(x => x[1].match(/[\w$]+/g) || []),
    // catch (e)
    ...[...body.matchAll(/catch\s*\(\s*([\w$]+)/g)].map(x => x[1]),
    // 구조분해 선언: const { a, b } = ... / const [a, b] = ...
    ...[...body.matchAll(/(?:const|let|var)\s*\{([^}]*)\}\s*=/g)]
      .flatMap(x => x[1].split(',').map(p => p.split(':').pop().split('=')[0].trim())),
    ...[...body.matchAll(/(?:const|let|var)\s*\[([^\]]*)\]\s*=/g)]
      .flatMap(x => x[1].split(',').map(p => p.split('=')[0].trim())),
    // for (const x of ...) 형태
    ...[...body.matchAll(/for\s*\(\s*(?:const|let|var)\s+([\w$]+)\s+of/g)].map(x => x[1]),
  ].filter(Boolean))

  // 감시할 이름을 손으로 적어 두면 목록에 없는 것은 그냥 지나간다.
  // 실제로 타점 탭에서 quality·timing·facts 를 선언 없이 쓰다가 화면이 죽었는데
  // WATCH 목록에 없어 이 검사기를 통과했다. 그래서 **JSX 안에서 쓰이는 식별자를
  // 자동으로 수집**해 검사한다. 렌더 중 ReferenceError 가 나면 리액트가 트리를
  // 통째로 버리므로, 화면을 죽이는 건 대부분 JSX 안의 참조다.
  const clean = strip(body)
  const WATCH = new Set()
  // JSX 중괄호 안의 소문자 시작 식별자만 본다.
  //  - 앞에 점이 없어야 함        속성 접근(e.total)이 아니어야 하므로
  //  - 뒤에 콜론이 없어야 함      객체 키(width: ...)가 아니어야 하므로
  //  - 뒤에 = 가 없어야 함        JSX 속성·대입이 아니어야 하므로
  //  - 대문자 시작 제외           컴포넌트 이름은 import 로 들어온다
  for (const brace of clean.matchAll(/\{([^{}]*)\}/g)) {
    // 중괄호 안에 JSX 가 통째로 들어오는 경우가 있다({cond && <div>안내 문구</div>}).
    // 태그 사이 본문 텍스트는 코드가 아니므로 지운다 — 안 그러면 한글·영문 단어가
    // 전부 변수 참조로 잡힌다.
    const expr = brace[1].replace(/>[^<>]*</g, '><')
    for (const t of expr.matchAll(
      /(^|[^.\w$])([a-z_$][\w$]*)\b(?!\s*[:=])/g)) {
      const id = t[2]
      if (!KEYWORDS.has(id) && !HTML_TAGS.has(id)) WATCH.add(id)
    }
  }
  for (const id of WATCH) {
    // 앞에 점이 없고(속성 접근 아님), 뒤에 콜론이 없어야(객체 키 아님) 변수 참조다.
    // 문자열·주석 안의 단어도 걸러야 오탐이 없다.
    const code = strip(body.slice(m[0].length))
    const used = new RegExp(`(^|[^.\\w$])${id}\\b(?!\\s*:)`).test(code)
    if (used && !declared.has(id) && !KNOWN.has(id)) {
      console.error(`  ✗ ${name}: '${id}' 를 쓰는데 정의가 없습니다`)
      bad++
    }
  }
}
console.log(bad ? `\n미정의 참조 ${bad}건 — 화면이 안 뜹니다` : '컴포넌트 참조 검사 통과')
process.exit(bad ? 1 : 0)
