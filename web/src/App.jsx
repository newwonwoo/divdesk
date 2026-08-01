import React, { useCallback, useEffect, useState } from 'react'
import { api, won, MODES, DOC } from './api.jsx'
import { enablePush, disablePush, isSubscribed, pushStatus } from './push.js'

/* ── 공통 ─────────────────────────────── */

const InfoBtn = ({ k, onOpen }) => (
  <button className="info" aria-label="설명 보기" onClick={() => onOpen(k)}>i</button>
)

function Sheet({ docKey, onClose }) {
  if (!docKey) return null
  const [title, body] = DOC[docKey] || ['설명', null]
  return (
    <div className="sheet" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="sheet-in">
        <h3>{title}</h3>
        {body}
        <button className="btn" onClick={onClose}>닫기</button>
      </div>
    </div>
  )
}

const Notes = ({ items }) =>
  !items?.length ? null : (
    <div className="note">{items.map((n, i) => <p key={i}>· {n}</p>)}</div>
  )

const Err = ({ msg }) => msg ? <div className="warn">{msg}</div> : null

function MonthStrip({ values }) {
  const max = Math.max(...values, 1)
  return (
    <>
      <div className="strip">
        {values.map((v, i) => (
          <div className="mo" key={i}>
            <div className="bar" style={{ height: `${Math.max(2, (v / max) * 100)}%` }} />
            <b>{i + 1}</b>
          </div>
        ))}
      </div>
      <div className="legend">
        <span><i style={{ background: 'var(--in)' }} />세후 원화</span>
        <span>비어 있는 달은 그 달에 입금이 없다는 뜻입니다</span>
      </div>
    </>
  )
}

/* ── 계산기 ───────────────────────────── */

function Calculator({ mode, etfs, onDoc }) {
  const [dir, setDir] = useState('forward')
  const [amount, setAmount] = useState('50000000')
  const [target, setTarget] = useState('1000000')
  const [picked, setPicked] = useState([])
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const usable = etfs.filter(e => e.close != null)

  useEffect(() => {
    // 계좌모드가 바뀌면 담을 수 있는 종목이 달라진다. 결과는 무효화한다.
    setPicked([]); setData(null); setErr('')
  }, [mode])

  const toggle = (t) =>
    setPicked(p => p.includes(t) ? p.filter(x => x !== t) : [...p, t])

  const run = async () => {
    setBusy(true); setErr(''); setData(null)
    try {
      const body = dir === 'forward'
        ? await api.forward({ amount_krw: Number(amount), tickers: picked, account_mode: mode })
        : await api.reverse({ target_monthly_krw: Number(target), tickers: picked, account_mode: mode })
      setData(body)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const fwd = data && (dir === 'forward' ? data.result : data.result.forward)
  const rev = data && dir === 'reverse' ? data.result : null

  return (
    <>
      <div className="card">
        <h2>계산 방향 <InfoBtn k="dir" onOpen={onDoc} /></h2>
        <div className="dir">
          <button aria-selected={dir === 'forward'} onClick={() => { setDir('forward'); setData(null) }}>
            금액 → 월배당
          </button>
          <button aria-selected={dir === 'reverse'} onClick={() => { setDir('reverse'); setData(null) }}>
            월배당 → 필요금액
          </button>
        </div>

        {dir === 'forward' ? (
          <>
            <label>투자 원금</label>
            <div className="field">
              <input inputMode="numeric" value={amount}
                onChange={e => setAmount(e.target.value.replace(/[^0-9]/g, ''))} />
              <em>원</em>
            </div>
          </>
        ) : (
          <>
            <label>목표 월배당 (세후)</label>
            <div className="field">
              <input inputMode="numeric" value={target}
                onChange={e => setTarget(e.target.value.replace(/[^0-9]/g, ''))} />
              <em>원</em>
            </div>
          </>
        )}

        <div style={{ marginTop: 16 }}>
          <label>담을 종목 {picked.length > 0 && `(${picked.length}개)`}</label>
          {usable.length === 0
            ? <div className="empty">수집된 가격 데이터가 있는 종목이 없습니다.<br />
                서버에서 수집 배치를 먼저 실행하세요.</div>
            : <div className="chips">
                {usable.map(e => (
                  <button key={e.ticker} className="chip"
                    aria-pressed={picked.includes(e.ticker)}
                    onClick={() => toggle(e.ticker)}>
                    {e.ticker}{e.is_covered_call ? ' ⚠' : ''}
                  </button>
                ))}
              </div>}
        </div>

        <button className="btn" disabled={busy || !picked.length} onClick={run}>
          {busy ? '계산 중…' : '계산하기'}
        </button>
        <Err msg={err} />
      </div>

      {rev && (
        <div className="card">
          <h2>필요 금액</h2>
          <div className="result" style={{ borderTop: 0, paddingTop: 0, marginTop: 0 }}>
            <div className="lbl">월 {won(rev.target_monthly_krw)}원을 받으려면</div>
            <div className="big">{won(rev.required_krw)}원</div>
            <div className="rows">
              {rev.plan.map(p => (
                <div className="row" key={p.ticker}>
                  <span>{p.ticker}</span>
                  <b className="num">{won(p.qty)}주 · {won(p.cost_krw)}원</b>
                </div>
              ))}
              <div className="row">
                <span>달성 예상</span>
                <b className="num">{won(rev.achieved_monthly_krw)}원 ({rev.achieved_pct}%)</b>
              </div>
            </div>
          </div>
          <Notes items={rev.notes} />
        </div>
      )}

      {fwd && (
        <>
          <div className="card">
            <h2>세후 월평균 배당 <InfoBtn k="avg" onOpen={onDoc} /></h2>
            <div className="result" style={{ borderTop: 0, paddingTop: 0, marginTop: 0 }}>
              <div className="big">{won(fwd.monthly_avg_net_krw)}원</div>
              <div className="rows">
                <div className="row"><span>투자 원금</span><b className="num">{won(fwd.invested_krw)}원</b></div>
                <div className="row"><span>연 세전 배당</span><b className="num">{won(fwd.annual_gross_krw)}원</b></div>
                <div className="row">
                  <span>세금 <InfoBtn k="tax" onOpen={onDoc} /></span>
                  <b className="num minus">-{won(fwd.annual_tax_krw)}원</b>
                </div>
                <div className="row"><span>가중 배당률</span><b className="num">{fwd.weighted_yield_pct}%</b></div>
              </div>
            </div>
            <Notes items={fwd.notes} />
          </div>

          <div className="card">
            <h2>월별 실제 입금 <InfoBtn k="strip" onOpen={onDoc} /></h2>
            <MonthStrip values={fwd.monthly_breakdown} />
            <div className="asof" style={{ marginTop: 8 }}>
              환율 {data.fx?.toLocaleString('ko-KR')}원 (기준 {data.fx_date})
            </div>
          </div>
        </>
      )}
    </>
  )
}

/* ── 타점 ─────────────────────────────── */

const gradeOf = (n) =>
  n == null ? ['s-none', '미산출']
    : n >= 85 ? ['s-buy', '적극매수']
    : n >= 70 ? ['s-buy', '매수']
    : n >= 55 ? ['s-hold', '관망']
    : ['s-wait', '보류']

function Screener({ etfs, onDoc }) {
  const scored = [...etfs].sort((a, b) => (b.score ?? -1) - (a.score ?? -1))
  const withScore = scored.filter(e => e.score != null)
  const without = scored.filter(e => e.score == null)

  return (
    <div className="card">
      <h2>오늘의 매수타점 <InfoBtn k="score" onOpen={onDoc} /></h2>
      {withScore.length === 0 && (
        <div className="empty">아직 산출된 점수가 없습니다.<br />
          수집 배치와 점수 계산을 먼저 실행하세요.</div>
      )}
      {withScore.map(e => {
        const [cls, label] = gradeOf(e.score)
        const [why, warn] = (e.reason || '').split('⚠')
        return (
          <div className="etf" key={e.ticker}>
            <div className={`score ${cls}`}><b>{e.score}</b><s>{label}</s></div>
            <div className="etf-main">
              <div className="tk">{e.ticker}<small>{e.strategy}</small></div>
              <div className="why">{why?.trim()}</div>
              {e.is_covered_call && (
                <button className="badge" onClick={() => onDoc('cc')}>분배금 ≠ 수익</button>
              )}
              {warn && <div className="why" style={{ color: 'var(--out)' }}>⚠ {warn.trim()}</div>}
            </div>
          </div>
        )
      })}
      {without.length > 0 && (
        <div className="note">
          <p>데이터가 없어 점수를 내지 못한 종목 {without.length}개:
            {' '}{without.map(e => e.ticker).join(', ')}</p>
          <p>추정값으로 채우지 않고 비워 둡니다.</p>
        </div>
      )}
    </div>
  )
}

/* ── 매수기록 ─────────────────────────── */

const today = () => new Date().toISOString().slice(0, 10)

function Ledger({ mode, etfs, onDoc, onChanged }) {
  const [items, setItems] = useState([])
  const [watch, setWatch] = useState(null)
  const [form, setForm] = useState({ ticker: '', trade_date: today(), qty: '', price: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const [p, w] = await Promise.all([api.purchases(), api.watchdog()])
      setItems(p.items); setWatch(w); setErr('')
    } catch (e) { setErr(e.message) }
  }, [])

  useEffect(() => { load() }, [load])

  const submit = async () => {
    setBusy(true); setErr('')
    try {
      await api.addPurchase({
        ticker: form.ticker, trade_date: form.trade_date,
        qty: Number(form.qty), price: Number(form.price), account_mode: mode,
      })
      setForm({ ticker: '', trade_date: today(), qty: '', price: '' })
      await load(); onChanged?.()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const remove = async (id) => {
    try { await api.delPurchase(id); await load(); onChanged?.() }
    catch (e) { setErr(e.message) }
  }

  const ready = form.ticker && form.qty > 0 && form.price > 0

  return (
    <>
      <div className="card">
        <h2>매수 기록 추가</h2>
        <div className="grid2">
          <select value={form.ticker} onChange={e => setForm({ ...form, ticker: e.target.value })}>
            <option value="">종목 선택</option>
            {etfs.map(e => <option key={e.ticker} value={e.ticker}>{e.ticker} {e.name}</option>)}
          </select>
          <input type="date" value={form.trade_date} max={today()}
            onChange={e => setForm({ ...form, trade_date: e.target.value })} />
          <input inputMode="decimal" placeholder="수량" value={form.qty}
            onChange={e => setForm({ ...form, qty: e.target.value })} />
          <input inputMode="decimal" placeholder="단가" value={form.price}
            onChange={e => setForm({ ...form, price: e.target.value })} />
        </div>
        <button className="btn" disabled={busy || !ready} onClick={submit}>
          {busy ? '저장 중…' : '기록 추가'}
        </button>
        <Err msg={err} />
      </div>

      <div className="card">
        <h2>매수기록</h2>
        {items.length === 0
          ? <div className="empty">아직 기록이 없습니다.</div>
          : <table>
              <tbody>
                <tr><th>일자</th><th>종목</th><th style={{ textAlign: 'right' }}>수량</th>
                    <th style={{ textAlign: 'right' }}>단가</th><th /></tr>
                {items.map(p => (
                  <tr key={p.id}>
                    <td className="num">{String(p.trade_date).slice(5)}</td>
                    <td>{p.ticker}</td>
                    <td className="n">{won(p.qty)}</td>
                    <td className="n">{Number(p.price).toLocaleString('ko-KR')}</td>
                    <td style={{ textAlign: 'right' }}>
                      <button className="del" onClick={() => remove(p.id)}>삭제</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>}

        {watch && (
          <div className={watch.level === 'ok' ? 'note' : 'warn'}>
            <b>금융소득 워치독 <InfoBtn k="watchdog" onOpen={onDoc} /></b><br />
            {watch.year}년 누적 {won(watch.gross_krw)}원 / 기준 {won(watch.threshold_krw)}원
            ({Math.round(watch.ratio * 100)}%)<br />{watch.message}
          </div>
        )}
      </div>
    </>
  )
}

/* ── 배당예상일지 ─────────────────────── */

const MONTH_LABEL = (y, m) => `${y}.${String(m).padStart(2, '0')}`

function Calendar({ mode, onDoc }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)

  useEffect(() => {
    setData(null); setErr('')
    api.calendar(mode).then(setData).catch(e => setErr(e.message))
  }, [mode])

  if (err) return <div className="card"><Err msg={err} /></div>
  if (!data) return <div className="card"><div className="empty">불러오는 중…</div></div>
  if (data.empty) return (
    <div className="card"><h2>배당예상일지</h2>
      <div className="empty">{data.message}<br />기록 탭에서 매수 내역을 추가하세요.</div>
    </div>
  )

  const max = Math.max(...data.months.map(m => m.net_krw), 1)
  const total = data.months.reduce((a, m) => a + m.net_krw, 0)

  return (
    <>
      <div className="card">
        <h2>앞으로 12개월 <InfoBtn k="cal" onOpen={onDoc} /></h2>
        <div className="result" style={{ borderTop: 0, paddingTop: 0, marginTop: 0 }}>
          <div className="lbl">예상 수령 합계 (세후)</div>
          <div className="big">{won(total)}원</div>
        </div>
        <div className="strip" style={{ marginTop: 14 }}>
          {data.months.map(m => (
            <div className="mo" key={`${m.year}-${m.month}`}>
              <div className={m.all_confirmed ? 'bar' : 'bar est'}
                style={{ height: `${Math.max(2, (m.net_krw / max) * 100)}%` }} />
              <b>{m.month}</b>
            </div>
          ))}
        </div>
        <div className="legend">
          <span><i style={{ background: 'var(--in)' }} />확정</span>
          <span><i className="bar est" style={{ height: 9 }} />추정</span>
        </div>
      </div>

      <div className="card">
        <h2>월별 상세</h2>
        {data.months.map(m => (
          <div key={`${m.year}-${m.month}`}>
            <div className="row" style={{ cursor: 'pointer' }}
              onClick={() => setOpen(open === `${m.year}${m.month}` ? null : `${m.year}${m.month}`)}>
              <span>{MONTH_LABEL(m.year, m.month)} {m.all_confirmed ? '' : '(추정)'}</span>
              <b className="num">{won(m.net_krw)}원</b>
            </div>
            {open === `${m.year}${m.month}` && (
              <div className="note">
                {m.items.map((it, i) => (
                  <p key={i}>
                    {it.pay_date.slice(5)} · {it.ticker} · {won(it.net_krw)}원
                    {it.confirmed ? ' [확정]' : ' [추정]'}
                  </p>
                ))}
              </div>
            )}
          </div>
        ))}
        {data.no_data.length > 0 && (
          <div className="note">
            <p>배당 이력이 없어 제외한 종목: {data.no_data.join(', ')}</p>
          </div>
        )}
        <Notes items={data.notes} />
      </div>
    </>
  )
}

/* ── 알림 설정 ────────────────────────── */

function PushSetting({ onDoc }) {
  const [state, setState] = useState({ loading: true })
  const [msg, setMsg] = useState('')

  const refresh = useCallback(async () => {
    const status = pushStatus()
    let serverReady = false
    try { serverReady = (await api.pushKey()).enabled } catch { /* 서버 미설정 */ }
    const subscribed = status.ok ? await isSubscribed() : false
    setState({ loading: false, status, serverReady, subscribed })
  }, [])

  useEffect(() => { refresh() }, [refresh])

  if (state.loading) return null

  const { status, serverReady, subscribed } = state

  const toggle = async () => {
    setMsg('')
    try {
      if (subscribed) { await disablePush(); setMsg('알림을 껐습니다.') }
      else { await enablePush(); setMsg('알림을 켰습니다.') }
      await refresh()
    } catch (e) { setMsg(e.message) }
  }

  return (
    <div className="card">
      <h2>매수 추천 알림 <InfoBtn k="push" onOpen={onDoc} /></h2>
      {!status.ok && <div className="warn">{status.message}</div>}
      {status.ok && !serverReady && (
        <div className="warn">서버에 알림 키가 설정되지 않았습니다.
          EC2에서 <code>python -m alerts.push --gen-keys</code> 를 실행해 .env 에 넣어주세요.</div>
      )}
      {status.ok && serverReady && (
        <>
          <div className="row">
            <span>85점 상향 돌파 시 알림</span>
            <b>{subscribed ? '켜짐' : '꺼짐'}</b>
          </div>
          <button className={subscribed ? 'btn ghost' : 'btn'} onClick={toggle}>
            {subscribed ? '알림 끄기' : '알림 켜기'}
          </button>
          {subscribed && (
            <button className="btn ghost" onClick={async () => {
              try { const r = await api.pushTest(); setMsg(`${r.delivered}/${r.subscriptions}건 발송`) }
              catch (e) { setMsg(e.message) }
            }}>테스트 알림 보내기</button>
          )}
        </>
      )}
      {msg && <div className="note"><p>{msg}</p></div>}
    </div>
  )
}

/* ── 대시보드 ─────────────────────────── */

const Signed = ({ v, suffix = '원' }) => (
  <b className="num" style={{ color: v > 0 ? 'var(--in)' : v < 0 ? 'var(--out)' : undefined }}>
    {v > 0 ? '+' : ''}{won(v)}{suffix}
  </b>
)

function Returns({ mode, onDoc, reloadKey }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setData(null); setErr('')
    api.returns(mode).then(setData).catch(e => setErr(e.message))
  }, [mode, reloadKey])

  if (err) return <div className="card"><Err msg={err} /></div>
  if (!data || data.empty) return null

  const r = data.result
  return (
    <>
      <div className="card">
        <h2>총수익 <InfoBtn k="total" onOpen={onDoc} /></h2>
        <div className="result" style={{ borderTop: 0, paddingTop: 0, marginTop: 0 }}>
          <div className="lbl">배당 + 시세차익 + 환차익</div>
          <div className="big" style={{ color: r.total_return_krw >= 0 ? 'var(--in)' : 'var(--out)' }}>
            {r.total_return_krw > 0 ? '+' : ''}{won(r.total_return_krw)}원
          </div>
          <div className="lbl">{r.total_return_pct > 0 ? '+' : ''}{r.total_return_pct}%</div>
          <div className="rows">
            <div className="row"><span>투자 원금</span><b className="num">{won(r.cost_krw)}원</b></div>
            <div className="row"><span>현재 평가액</span><b className="num">{won(r.value_krw)}원</b></div>
            <div className="row"><span>├ 시세차익</span><Signed v={r.price_gain_krw} /></div>
            <div className="row"><span>└ 환차익</span><Signed v={r.fx_gain_krw} /></div>
            <div className="row"><span>받은 배당 (세후)</span><Signed v={r.dividend_net_krw} /></div>
          </div>
        </div>
        {r.estimated_capgain_tax_krw > 0 && (
          <div className="note">
            <p>지금 전부 매도하면 양도세 약 {won(r.estimated_capgain_tax_krw)}원이 발생합니다.</p>
          </div>
        )}
        <Notes items={r.notes} />
      </div>

      <div className="card">
        <h2>종목별 손익</h2>
        {r.positions.map(p => (
          <div className="etf" key={p.ticker}>
            <div className="etf-main">
              <div className="tk">{p.ticker}
                <small>{won(p.qty)}주 · 평단 {p.avg_price.toLocaleString('ko-KR')}</small>
              </div>
              <div className="why">
                시세 <span style={{ color: p.price_gain_krw >= 0 ? 'var(--in)' : 'var(--out)' }}>
                  {p.price_gain_krw > 0 ? '+' : ''}{won(p.price_gain_krw)}</span>
                {' · '}환 <span style={{ color: p.fx_gain_krw >= 0 ? 'var(--in)' : 'var(--out)' }}>
                  {p.fx_gain_krw > 0 ? '+' : ''}{won(p.fx_gain_krw)}</span>
                {' · '}배당 +{won(p.dividend_krw)}
              </div>
              {p.price_gain_krw < 0 && p.dividend_krw > -p.price_gain_krw && (
                <div className="badge">배당이 시세손실을 메움</div>
              )}
            </div>
            <div className="yld">
              <b style={{ color: p.return_pct >= 0 ? 'var(--in)' : 'var(--out)' }}>
                {p.return_pct > 0 ? '+' : ''}{p.return_pct}%
              </b>
              <s>{won(p.total_gain_krw)}원</s>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

function Dashboard({ mode, onDoc, reloadKey }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setData(null); setErr('')
    api.portfolio(mode).then(setData).catch(e => setErr(e.message))
  }, [mode, reloadKey])

  if (err) return <div className="card"><Err msg={err} /></div>
  if (!data) return <div className="card"><div className="empty">불러오는 중…</div></div>
  if (data.empty) return (
    <div className="card"><h2>내 포트폴리오</h2>
      <div className="empty">{data.message}<br />기록 탭에서 매수 내역을 추가하세요.</div>
    </div>
  )

  const r = data.result
  return (
    <>
      <div className="card">
        <h2>내 포트폴리오 <InfoBtn k="avg" onOpen={onDoc} /></h2>
        <div className="result" style={{ borderTop: 0, paddingTop: 0, marginTop: 0 }}>
          <div className="lbl">세후 월평균 배당</div>
          <div className="big">{won(r.monthly_avg_net_krw)}원</div>
          <div className="rows">
            <div className="row"><span>투자 원금</span><b className="num">{won(r.invested_krw)}원</b></div>
            <div className="row"><span>연 세후 배당</span><b className="num">{won(r.annual_net_krw)}원</b></div>
            <div className="row"><span>가중 배당률</span><b className="num">{r.weighted_yield_pct}%</b></div>
          </div>
        </div>
        <Notes items={r.notes} />
      </div>
      <div className="card">
        <h2>월별 입금 <InfoBtn k="strip" onOpen={onDoc} /></h2>
        <MonthStrip values={r.monthly_breakdown} />
      </div>
    </>
  )
}

/* ── 앱 ───────────────────────────────── */

export default function App() {
  const [tab, setTab] = useState('home')
  const [mode, setMode] = useState('US_TAXABLE')
  const [etfs, setEtfs] = useState([])
  const [doc, setDoc] = useState(null)
  const [err, setErr] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  // 계좌모드가 담을 수 있는 시장을 정한다. 절세계좌엔 국내상장만 들어간다.
  const market = mode === 'US_TAXABLE' ? 'US' : 'KR'

  useEffect(() => {
    api.etfs(market).then(r => { setEtfs(r.items); setErr('') })
      .catch(e => { setErr(e.message); setEtfs([]) })
  }, [market])

  const asof = etfs.find(e => e.price_date)?.price_date

  return (
    <div className="wrap">
      <header>
        <div className="brand"><h1>DivDesk</h1><span>배당ETF 매수검토</span></div>
        <div className="asof num">
          {asof ? `데이터 기준 ${asof}` : '수집된 데이터 없음'}
        </div>
        <div className="seg" role="tablist">
          {MODES.map(m => (
            <button key={m.key} role="tab" aria-selected={mode === m.key}
              onClick={() => setMode(m.key)}>{m.label}</button>
          ))}
        </div>
        {mode === 'KR_SHELTER' && (
          <div className="note">
            <p>절세계좌(ISA·연금·IRP)에는 국내상장 ETF만 담을 수 있어 국내 종목만 표시합니다.</p>
          </div>
        )}
      </header>

      <Err msg={err} />

      {tab === 'home' && (
        <>
          <Returns mode={mode} onDoc={setDoc} reloadKey={reloadKey} />
          <Dashboard mode={mode} onDoc={setDoc} reloadKey={reloadKey} />
        </>
      )}
      {tab === 'calc' && <Calculator mode={mode} etfs={etfs} onDoc={setDoc} />}
      {tab === 'score' && <Screener etfs={etfs} onDoc={setDoc} />}
      {tab === 'cal' && <Calendar mode={mode} onDoc={setDoc} key={reloadKey} />}
      {tab === 'ledger' && (
        <>
          <Ledger mode={mode} etfs={etfs} onDoc={setDoc}
            onChanged={() => setReloadKey(k => k + 1)} />
          <PushSetting onDoc={setDoc} />
        </>
      )}

      <nav role="tablist">
        {[['home', '홈'], ['calc', '계산'], ['score', '타점'], ['cal', '일지'], ['ledger', '기록']].map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k}
            onClick={() => { setTab(k); window.scrollTo(0, 0) }}>{label}</button>
        ))}
      </nav>

      <Sheet docKey={doc} onClose={() => setDoc(null)} />
    </div>
  )
}
