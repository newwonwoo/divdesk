import React, { useCallback, useEffect, useState } from 'react'
import { api, DOC } from './api.jsx'
import {
  commafy, GRADE, label, MODES, pct, qty, shortLabel,
  signed, signedPct, uncomma, usd, won,
} from './format.js'
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

function Notes({ items, title = '계산 기준과 주의사항' }) {
  const [open, setOpen] = useState(false)
  if (!items?.length) return null
  return (
    <div className="fold">
      <button className="fold-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>{title} ({items.length})</span>
        <span className="fold-mark">{open ? '−' : '+'}</span>
      </button>
      {open && <div className="fold-body">{items.map((n, i) => <p key={i}>{n}</p>)}</div>}
    </div>
  )
}

const Err = ({ msg }) => msg ? <div className="warn">{msg}</div> : null

// 만원 단위. 막대 위에 숫자가 없으면 높이만 보고 크기를 가늠해야 한다.
const manwon = (v) => {
  const n = Math.round(Number(v) / 10000)
  return n > 0 ? n.toLocaleString('ko-KR') : ''
}

function MonthStrip({ values, labels, marks }) {
  const max = Math.max(...values.map(v => Math.abs(Number(v) || 0)), 1)
  if (!values.length || values.every(v => !v)) {
    return <div className="empty">표시할 입금 내역이 없습니다.</div>
  }
  return (
    <>
      <div className="strip">
        {values.map((v, i) => (
          <div className="mo" key={i} title={`${won(v)}원`}>
            <em className="mo-v">{manwon(v)}</em>
            <div className={v > 0 ? (marks && marks[i] === false ? 'bar est' : 'bar') : 'bar zero'}
              style={{ height: v > 0 ? `${Math.max(4, (v / max) * 100)}%` : '3px' }} />
            <b>{labels ? labels[i] : i + 1}</b>
          </div>
        ))}
      </div>
      <div className="legend">
        <span>단위: 만원</span>
        {marks && <><span><i className="sw" />확정</span><span><i className="sw est" />추정</span></>}
      </div>
    </>
  )
}

/* ── 계산기 ───────────────────────────── */

function Calculator({ etfs, onDoc }) {
  const [mode, setMode] = useState('US_TAXABLE')
  const [dir, setDir] = useState('forward')
  const [target, setTarget] = useState('1,000,000')
  const [items, setItems] = useState([])
  const [sel, setSel] = useState('')
  const [amt, setAmt] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const usable = etfs.filter(e => e.close != null)


  const selMeta = usable.find(e => e.ticker === sel)
  const tickers = items.map(i => i.ticker)
  const totalAmount = items.reduce((a, i) => a + i.amount, 0)
  const onAdd = (row) => setItems(p => [...p.filter(x => x.ticker !== row.ticker), row])
  const onRemove = (t) => setItems(p => p.filter(x => x.ticker !== t))

  const run = async () => {
    setBusy(true); setErr(''); setData(null)
    try {
      const body = dir === 'forward'
        ? await api.forward({
            amount_krw: totalAmount, tickers, account_mode: mode,
            weights: Object.fromEntries(items.map(i => [i.ticker, i.amount])),
          })
        : await api.reverse({
            target_monthly_krw: uncomma(target), tickers, account_mode: mode,
          })
      setData(body)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const fwd = data && (dir === 'forward' ? data.result : data.result.forward)
  const rev = data && dir === 'reverse' ? data.result : null

  return (
    <>
      <div className="card">
        <h2>계산 방향 <InfoBtn k="dir" onOpen={onDoc} /></h2>
        <label>계좌</label>
        <select value={mode} onChange={e => { setMode(e.target.value); setData(null) }}>
          {MODES.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
        {mode === 'KR_SHELTER' && (
          <div className="hint">절세계좌에는 국내상장 ETF만 담을 수 있습니다.</div>
        )}
        <div style={{ marginTop: 14 }} />
        <div className="dir">
          <button aria-selected={dir === 'forward'} onClick={() => { setDir('forward'); setData(null) }}>
            금액 → 월배당
          </button>
          <button aria-selected={dir === 'reverse'} onClick={() => { setDir('reverse'); setData(null) }}>
            월배당 → 필요금액
          </button>
        </div>

        {dir === 'reverse' && (
          <>
            <label style={{ marginTop: 14 }}>목표 월배당 (세후)</label>
            <div className="field">
              <input inputMode="numeric" value={target}
                onChange={e => setTarget(commafy(e.target.value))} />
              <em>원</em>
            </div>
          </>
        )}

        <div style={{ marginTop: 16 }}>
          <label>담을 종목과 금액</label>
          {usable.length === 0
            ? <div className="empty">수집된 가격 데이터가 있는 종목이 없습니다.</div>
            : <>
                <select value={sel} onChange={e => setSel(e.target.value)}>
                  <option value="">종목 선택</option>
                  {usable.map(e => (
                    <option key={e.ticker} value={e.ticker}>{label(e)}</option>
                  ))}
                </select>
                {selMeta && (
                  <div className="pick-info">
                    <span className="tag">{selMeta.strategy}</span>
                    {selMeta.expense_ratio != null &&
                      <span className="tag">보수 {selMeta.expense_ratio}%</span>}
                    {selMeta.score != null && <span className="tag">타점 {selMeta.score}점</span>}
                    {selMeta.is_covered_call &&
                      <span className="tag warn-tag">분배금 ≠ 수익</span>}
                  </div>
                )}
                <div className="field" style={{ marginTop: 12 }}>
                  <input inputMode="numeric" placeholder="금액" value={amt}
                    onChange={e => setAmt(commafy(e.target.value))} />
                  <em>원</em>
                </div>
                <button className="btn ghost" disabled={!sel || uncomma(amt) <= 0}
                  onClick={() => {
                    onAdd({ ticker: sel, amount: uncomma(amt), meta: selMeta })
                    setSel(''); setAmt('')
                  }}>담기</button>

                {items.length > 0 && (
                  <div className="picked">
                    {items.map(i => (
                      <div className="picked-row" key={i.ticker}>
                        <span>{label(i.meta) || i.ticker}</span>
                        <b className="num">{won(i.amount)}원</b>
                        <button className="del"
                          onClick={() => onRemove(i.ticker)}>삭제</button>
                      </div>
                    ))}
                    <div className="picked-row total">
                      <span>합계 {items.length}종목</span>
                      <b className="num">{won(totalAmount)}원</b>
                      <span />
                    </div>
                  </div>
                )}
              </>}
        </div>

        <button className="btn"
          disabled={busy || !items.length || (dir === 'forward' && totalAmount <= 0)}
          onClick={run}>
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
                  <b className="num">{qty(p.qty)}주 · {won(p.cost_krw)}원</b>
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

/* ── 적립 시뮬레이션 ───────────────────── */

function Projection({ etfs, onDoc }) {
  const [picked, setPicked] = useState(['SCHD'])
  const [monthly, setMonthly] = useState('500')
  const [cur, setCur] = useState('USD')
  const [years, setYears] = useState(10)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const usable = etfs.filter(e => e.market === 'US' && e.close != null)
  const toggle = (t) =>
    setPicked(p => p.includes(t) ? p.filter(x => x !== t) : [...p, t])

  const run = async () => {
    setBusy(true); setErr(''); setData(null)
    try {
      setData(await api.projection({
        monthly_usd: cur === 'KRW' ? uncomma(monthly) : Number(monthly),
        currency: cur, years, tickers: picked,
      }))
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <>
      <div className="card">
        <h2>적립 시뮬레이션 <InfoBtn k="proj" onOpen={onDoc} /></h2>

        <label>통화</label>
        <div className="dir">
          {[['USD', '달러 $'], ['KRW', '원화 ₩']].map(([k, t]) => (
            <button key={k} aria-selected={cur === k}
              onClick={() => { setCur(k); setMonthly(k === 'USD' ? '500' : '700,000'); setData(null) }}>
              {t}
            </button>
          ))}
        </div>

        <label style={{ marginTop: 16 }}>매달 넣을 금액</label>
        <div className="field">
          <em style={{ paddingLeft: 0, paddingRight: 8 }}>{cur === 'USD' ? '$' : '₩'}</em>
          <input inputMode="numeric" value={monthly}
            onChange={e => setMonthly(cur === 'KRW'
              ? commafy(e.target.value) : e.target.value.replace(/[^0-9]/g, ''))} />
        </div>

        <label style={{ marginTop: 16 }}>기간</label>
        <div className="dir">
          {[5, 10, 15, 20].map(y => (
            <button key={y} aria-selected={years === y}
              onClick={() => { setYears(y); setData(null) }}>{y}년</button>
          ))}
        </div>

        <label style={{ marginTop: 16 }}>매수 종목</label>
        <div className="picklist">
          {usable.map(e => (
            <button key={e.ticker} className="pick" aria-pressed={picked.includes(e.ticker)}
              onClick={() => toggle(e.ticker)}>
              <span className="pick-name">{label(e)}</span>
              <span className="pick-meta">
                {e.strategy}
                {e.expense_ratio != null && ` · 보수 ${e.expense_ratio}%`}
                {e.score != null && ` · 타점 ${e.score}점`}
                {e.is_covered_call && ' · 분배금 ≠ 수익'}
              </span>
            </button>
          ))}
        </div>
        <div className="hint">SPY·VOO·QQQ는 비교 기준으로 항상 함께 계산됩니다.</div>

        <button className="btn" disabled={busy || !picked.length || !Number(monthly)}
          onClick={run}>
          {busy ? '계산 중…' : '계산하기'}
        </button>
        <Err msg={err} />
      </div>

      {data && (
        <div className="card">
          <h2>{data.years}년 뒤 예상</h2>
          <div className="hero-sub">
            매달 {data.currency === 'KRW'
              ? `${won(uncomma(monthly))}원 (약 $${Math.round(data.monthly_usd)})`
              : `$${Number(monthly).toLocaleString()}`} × {data.years * 12}개월
            <br />총 ${data.total_invested_usd.toLocaleString()} ·
            {' '}{won(data.total_invested_krw)}원 투입
          </div>

          {data.results.map(r => (
            <div className="row-item" key={r.ticker}>
              <div className="row-main">
                <div className="tk">{r.ticker}
                  {r.is_benchmark && <span className="tag bench">기준</span>}
                </div>
                <div className="kv">
                  <span>최악 ${Math.round(r.worst_final_usd).toLocaleString()}</span>
                  <span>최선 ${Math.round(r.best_final_usd).toLocaleString()}</span>
                  {r.loss_windows > 0 && (
                    <span style={{ color: 'var(--out)' }}>원금 미달 {r.loss_windows}회</span>
                  )}
                </div>
                <div className="hint">
                  데이터 {r.data_from?.slice(0, 7)}부터 {r.data_years}년치 ·
                  시작 시점 {r.windows}가지 시험
                </div>
              </div>
              <div className="row-right">
                <b>${Math.round(r.median_final_usd).toLocaleString()}</b>
                <s>{won(r.median_final_krw)}원</s>
                <s style={{ color: 'var(--in)' }}>연 {pct(r.median_annual_pct)}</s>
              </div>
            </div>
          ))}

          <Notes items={[data.fx_note, data.period_note,
            ...(data.results[0]?.notes || [])].filter(Boolean)} />
        </div>
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

function Duplicates({ onDoc }) {
  const [groups, setGroups] = useState([])
  useEffect(() => { api.duplicates().then(r => setGroups(r.groups)).catch(() => {}) }, [])
  if (!groups.length) return null
  return (
    <div className="card">
      <h2>같은 지수 중복 <InfoBtn k="dup" onOpen={onDoc} /></h2>
      {groups.map(g => (
        <div key={g.index} style={{ marginBottom: 14 }}>
          <div className="hint" style={{ marginTop: 0 }}>{g.index}</div>
          {g.members.map((m, i) => (
            <div className="picked-row" key={m.ticker}>
              <span>{i === 0 && <span className="tag bench">추천</span>} {shortLabel(m)}</span>
              <b className="num">
                {m.expense_ratio != null ? `보수 ${m.expense_ratio}%` : '보수 미확인'}
              </b>
              <span />
            </div>
          ))}
          <div className="hint">{g.advice}</div>
        </div>
      ))}
    </div>
  )
}

function Screener({ onDoc }) {
  const [items, setItems] = useState(null)
  const [market, setMarket] = useState('ALL')
  const [err, setErr] = useState('')

  useEffect(() => {
    api.scores().then(r => setItems(r.items)).catch(e => setErr(e.message))
  }, [])

  if (err) return <div className="card"><Err msg={err} /></div>
  if (!items) return <div className="card"><div className="empty">불러오는 중…</div></div>

  const scored = items
    .filter(i => market === 'ALL' || i.market === market)
    .sort((a, b) => (b.total ?? -1) - (a.total ?? -1))
  const withScore = scored.filter(e => e.total != null)
  const without = scored.filter(e => e.total == null)

  return (
    <div className="card">
      <h2>오늘의 매수타점 <InfoBtn k="score" onOpen={onDoc} /></h2>
      <div className="dir" style={{ marginBottom: 14 }}>
        {[['ALL', '전체'], ['US', '미국'], ['KR', '국내']].map(([k, t]) => (
          <button key={k} aria-selected={market === k} onClick={() => setMarket(k)}>{t}</button>
        ))}
      </div>
      {withScore.length === 0 && (
        <div className="empty">아직 산출된 점수가 없습니다.<br />
          수집 배치와 점수 계산을 먼저 실행하세요.</div>
      )}
      {withScore.map(e => {
        const g = GRADE(e.total)
        const [why, warn] = (e.reason || '').split('⚠')
        return (
          <div className="etf" key={e.ticker}>
            <div className={`score ${g.cls}`}><b>{e.total}</b><s>{g.text}</s></div>
            <div className="etf-main">
              <div className="tk">{shortLabel(e)}<small>{e.strategy}</small></div>
              {quality != null && (
                <div className="axes">
                  <div className={`axis${excluded ? ' bad' : ''}`}>
                    <span className="axis-l">상품 품질</span>
                    <span className="bar-wrap wide">
                      <span className="bar-fill" style={{ width: `${quality}%` }} />
                    </span>
                    <b>{quality}</b>
                  </div>
                  <div className="axis">
                    <span className="axis-l">매수 타점</span>
                    <span className="bar-wrap wide">
                      <span className="bar-fill t" style={{ width: `${timing}%` }} />
                    </span>
                    <b>{timing}</b>
                  </div>
                  <div className="axis-note">
                    품질 75% + 타점 25%
                    {confidence != null && confidence < 80 && (
                      <span className="low-conf"> · 데이터 신뢰도 {confidence}%</span>
                    )}
                  </div>
                </div>
              )}
              {facts.length > 0
                ? <table className="facts">
                    <tbody>
                      {facts.map(([k, v, sub, got, max], i) => (
                        <tr key={i}>
                          <th>{k}</th>
                          <td className="fv">{v}</td>
                          <td className="fs">{sub}</td>
                          <td className="fp">
                            <span className="bar-wrap">
                              <span className="bar-fill"
                                style={{ width: `${Math.round((got / max) * 100)}%` }} />
                            </span>
                            <b>{got}</b><s>/{max}</s>
                          </td>
                        </tr>
                      ))}
                      <tr className="ftot">
                        <th>합계</th><td /><td />
                        <td className="fp"><b>{e.total}</b><s>/100</s></td>
                      </tr>
                    </tbody>
                  </table>
                : <div className="why">{why?.trim()}</div>}
              {e.is_covered_call && (
                <button className="badge" onClick={() => onDoc('cc')}>분배금 ≠ 수익</button>
              )}
              {warn && <div className="hint out">{warn.trim()}</div>}
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

/* ── 동기화 상태 ──────────────────────── */

const AGO = (iso) => {
  if (!iso) return '없음'
  const days = Math.floor((Date.now() - new Date(iso)) / 86400000)
  return days === 0 ? '오늘' : days === 1 ? '어제' : `${days}일 전`
}

function SyncStatus({ onChanged }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    api.syncStatus().then(setData).catch(() => setData(null))
  }, [])
  useEffect(() => { load() }, [load])

  const pull = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await api.syncToss()
      setMsg(r.added > 0 ? `${r.added}건을 새로 불러왔습니다.` : '새로운 매수 내역이 없습니다.')
      load(); onChanged?.()
    } catch (e) { setMsg(e.message) } finally { setBusy(false) }
  }

  const toss = data?.items?.find(i => i.source === 'toss')
  const bad = data?.items?.filter(i => i.state !== 'ok') || []

  return (
    <div className="card">
      <h2>토스증권 연동</h2>
      {bad.length > 0 && (
        <div className="warn">
          <b>데이터가 갱신되지 않고 있습니다</b>
          {bad.map(i => <div key={i.source}>{i.label}: {i.message}</div>)}
          <div className="hint">아래 숫자는 그 시점 기준이라 지금과 다를 수 있습니다.</div>
        </div>
      )}
      <div className="rows">
        <div className="row"><span>마지막 동기화</span><b>{AGO(toss?.last_success)}</b></div>
        <div className="row"><span>자동 실행</span><b>매일 아침 6:30</b></div>
      </div>
      <button className="btn" disabled={busy} onClick={pull}>
        {busy ? '불러오는 중…' : '지금 불러오기'}
      </button>
      {msg && <div className="hint">{msg}</div>}
    </div>
  )
}

/* ── 잔고 대조 ────────────────────────── */

function Reconcile({ onDoc, refresh }) {
  const [data, setData] = useState(null)

  useEffect(() => { api.reconcile().then(setData).catch(() => setData(null)) }, [refresh])
  if (!data) return null
  if (!data.available) return (
    <div className="card">
      <h2>잔고 대조 <InfoBtn k="recon" onOpen={onDoc} /></h2>
      <div className="hint">{data.reason}</div>
    </div>
  )

  const bad = data.items.filter(i => i.state !== 'ok')
  return (
    <div className="card">
      <h2>잔고 대조 <InfoBtn k="recon" onOpen={onDoc} /></h2>
      {bad.length === 0
        ? <div className="rows">
            <div className="row"><span>증권사 잔고와</span>
              <b style={{ color: 'var(--in)' }}>일치</b></div>
          </div>
        : <div className="warn">
            <b>{bad.length}종목이 실제 잔고와 다릅니다</b>
            {bad.map(i => (
              <div key={i.ticker} style={{ marginTop: 8 }}>
                {i.ticker} · 기록 {qty(i.booked)}주 / 실제
                {' '}{i.actual == null ? '없음' : qty(i.actual) + '주'}
                <div className="hint out">{i.note}</div>
              </div>
            ))}
          </div>}
      <div className="hint">{data.note}</div>
    </div>
  )
}

/* ── 매수기록 ─────────────────────────── */

const today = () => new Date().toISOString().slice(0, 10)

const PAGE = 30

function Ledger({ etfs, onDoc, onChanged }) {
  const [items, setItems] = useState([])
  const [shown, setShown] = useState(PAGE)
  const [watch, setWatch] = useState(null)
  const [manual, setManual] = useState(false)
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
        qty: Number(form.qty), price: uncomma(form.price), account_mode: 'KR_SHELTER',
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
      <SyncStatus onChanged={() => { load(); onChanged?.() }} />
      <Reconcile onDoc={onDoc} refresh={items.length} />
      <div className="card">
        <button className="fold-head" onClick={() => setManual(!manual)} aria-expanded={manual}>
          <span>절세계좌 기록 직접 입력</span>
          <span className="fold-mark">{manual ? '−' : '+'}</span>
        </button>
        {manual && <div className="fold-body">
        <p className="hint">일반계좌는 토스에서 자동으로 들어옵니다.
          여기는 토스가 주지 않는 절세계좌(ISA·연금) 전용입니다.</p>
        <div className="grid2" style={{ marginTop: 12 }}>
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
        </div>}
      </div>

      <div className="card">
        <h2>매수기록 {items.length}건</h2>
        {items.length === 0
          ? <div className="empty">아직 기록이 없습니다.</div>
          : <table>
              <tbody>
                <tr><th>일자</th><th>종목</th><th style={{ textAlign: 'right' }}>수량</th>
                    <th style={{ textAlign: 'right' }}>단가</th><th /></tr>
                {items.slice(0, shown).map(p => (
                  <tr key={p.id}>
                    <td className="num">{String(p.trade_date).slice(5)}</td>
                    <td>{p.ticker}</td>
                    <td className="n">{qty(p.qty)}</td>
                    <td className="n">{Number(p.price).toLocaleString('ko-KR')}</td>
                    <td style={{ textAlign: 'right' }}>
                      <button className="del" onClick={() => remove(p.id)}>삭제</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>}
        {shown < items.length && (
          <button className="btn ghost" onClick={() => setShown(shown + PAGE)}>
            {items.length - shown}건 더 보기
          </button>
        )}

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

function Calendar({ onDoc }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)

  useEffect(() => {
    setData(null); setErr('')
    api.calendar().then(setData).catch(e => setErr(e.message))
  }, [])

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
        <h2>앞으로 12개월 배당 <InfoBtn k="cal" onOpen={onDoc} /></h2>
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
        <div className="fold-list">
        {data.months.map(m => (
          <div key={`${m.year}-${m.month}`}>
            <button className="fold-head"
              aria-expanded={open === `${m.year}${m.month}`}
              onClick={() => setOpen(open === `${m.year}${m.month}` ? null : `${m.year}${m.month}`)}>
              <span>{MONTH_LABEL(m.year, m.month)}
                {!m.all_confirmed && <span className="tag">추정</span>}</span>
              <b className="num">{won(m.net_krw)}원</b>
            </button>
            {open === `${m.year}${m.month}` && (
              <div className="fold-body">
                {m.items.map((it, i) => (
                  <div className="row" key={i}>
                    <span>{it.pay_date.slice(5)} · {it.ticker}</span>
                    <b className="num">{won(it.net_krw)}원</b>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        </div>
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

function Returns({ onDoc, reloadKey }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setData(null); setErr('')
    api.returns().then(setData).catch(e => setErr(e.message))
  }, [reloadKey])

  if (err) return <div className="card"><Err msg={err} /></div>
  if (!data || data.empty) return null

  const r = data.result
  return (
    <>
      <div className="card">
        <h2>총수익 <InfoBtn k="total" onOpen={onDoc} /></h2>
        <div className="hero">
          <div className="hero-v" style={{ color: signed(r.total_return_krw).color }}>
            {signed(r.total_return_krw).text}원
          </div>
          <div className="hero-p" style={{ color: signed(r.total_return_krw).color }}>
            {signedPct(r.total_return_pct)}
          </div>
        </div>
        <div className="hero-sub">
          {won(r.cost_krw)}원 → {won(r.value_krw)}원
          {data.accounts?.length > 1 && (
            <div className="kv" style={{ marginTop: 6 }}>
              {data.accounts.map(a => (
                <span key={a.mode}>
                  {MODES.find(m => m.key === a.mode)?.short || a.mode} {won(a.cost_krw)}원
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="metrics">
          <div className="metric">
            <div className="metric-l">시세차익</div>
            <div className="metric-v" style={{ color: signed(r.price_gain_krw).color }}>
              {signed(r.price_gain_krw).text}</div>
          </div>
          <div className="metric">
            <div className="metric-l">환차익</div>
            <div className="metric-v" style={{ color: signed(r.fx_gain_krw).color }}>
              {signed(r.fx_gain_krw).text}</div>
          </div>
          <div className="metric">
            <div className="metric-l">받은 배당 (세후)</div>
            <div className="metric-v" style={{ color: 'var(--in)' }}>
              {signed(r.dividend_net_krw).text}</div>
            <div className="metric-s">세금 {won(r.dividend_tax_krw)}원 차감</div>
          </div>
          <div className="metric">
            <div className="metric-l">매도 시 양도세</div>
            <div className="metric-v">
              {r.estimated_capgain_tax_krw > 0 ? won(r.estimated_capgain_tax_krw) : '없음'}</div>
            <div className="metric-s">지금 전부 판다고 가정</div>
          </div>
        </div>
        <Notes items={r.notes} />
      </div>

      <div className="card">
        <h2>종목별 손익</h2>
        {r.positions.map(p => (
          <div className="row-item" key={p.ticker}>
            <div className="row-main">
              <div className="tk">{p.ticker}
                <small>{qty(p.qty)}주 · 평단 {usd(p.avg_price)}</small>
              </div>
              <div className="kv">
                <span>시세 <b style={{ color: signed(p.price_gain_krw).color }}>
                  {signed(p.price_gain_krw).text}</b></span>
                <span>환 <b style={{ color: signed(p.fx_gain_krw).color }}>
                  {signed(p.fx_gain_krw).text}</b></span>
                <span>배당 <b style={{ color: 'var(--in)' }}>+{won(p.dividend_krw)}</b></span>
              </div>
              {p.opening_qty > 0 && (
                <div className="hint">이 중 {qty(p.opening_qty)}주는 매수 이력이 없어
                  환차익 계산에서 제외</div>
              )}
              {p.price_gain_krw < 0 && p.dividend_krw > -p.price_gain_krw && (
                <div className="badge">배당이 시세손실을 메움</div>
              )}
            </div>
            <div className="row-right">
              <b style={{ color: signed(p.total_gain_krw).color }}>{signedPct(p.return_pct)}</b>
              <s>{signed(p.total_gain_krw).text}원</s>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

function Dashboard({ onDoc, reloadKey }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setData(null); setErr('')
    api.portfolio().then(setData).catch(e => setErr(e.message))
  }, [reloadKey])

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
  const [etfs, setEtfs] = useState([])
  const [doc, setDoc] = useState(null)
  const [err, setErr] = useState('')
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    api.etfs().then(r => { setEtfs(r.items); setErr('') })
      .catch(e => { setErr(e.message); setEtfs([]) })
  }, [])

  const asof = etfs.find(e => e.price_date)?.price_date

  return (
    <div className="wrap">
      <header>
        <div className="brand"><h1>DivDesk</h1><span>배당ETF 매수검토</span></div>
        <div className="asof num">
          {asof ? `데이터 기준 ${asof}` : '수집된 데이터 없음'}
        </div>
      </header>

      <nav role="tablist">
        {[['home', '홈'], ['calc', '계산'], ['proj', '시뮬레이션'],
          ['score', '타점'], ['ledger', '기록']].map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k}
            onClick={() => { setTab(k); window.scrollTo(0, 0) }}>{label}</button>
        ))}
      </nav>


      <Err msg={err} />

      {tab === 'home' && (
        <>
          <Returns onDoc={setDoc} reloadKey={reloadKey} />
          <Calendar onDoc={setDoc} key={reloadKey} />
        </>
      )}
      {tab === 'calc' && <Calculator etfs={etfs} onDoc={setDoc} />}
      {tab === 'proj' && <Projection etfs={etfs} onDoc={setDoc} />}
      {tab === 'score' && (
        <>
          <Screener onDoc={setDoc} />
          <Duplicates onDoc={setDoc} />
        </>
      )}
      {tab === 'ledger' && (
        <>
          <Ledger etfs={etfs} onDoc={setDoc}
            onChanged={() => setReloadKey(k => k + 1)} />
          <PushSetting onDoc={setDoc} />
        </>
      )}


      <Sheet docKey={doc} onClose={() => setDoc(null)} />
    </div>
  )
}
