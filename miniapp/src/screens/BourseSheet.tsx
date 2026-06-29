import { useEffect, useMemo, useState } from 'react'
import { api, errText, ApiError } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { GoodIcon, ResIcon, fmt } from '../components/icons'

interface BOrder { id: number; side: string; qty: number; unit: number; key: string; name: string; emoji: string; who?: string }
interface BRow { key: string; name: string; emoji: string; ask?: number | null; ask_qty?: number | null; bid?: number | null; bid_qty?: number | null; floor: number; ceil: number }
interface BSeller { name: string; sold: number; me: boolean }
interface BGood { key: string; name: string; emoji: string; stock: number; floor: number; ceil: number; presets: number[]; room: number }
interface BState {
  ok: boolean; open: boolean; admin?: boolean; gold?: number; done?: string
  sells?: BOrder[]; buys?: BOrder[]; mine?: BOrder[]; board?: BRow[]; sellers?: BSeller[]; goods?: BGood[]
  qty_max?: number; max_orders?: number
}

// ── ПРЕВЬЮ-ДЕМО (только import.meta.env.DEV). В прод-сборке вырезается. ──
const DEV = import.meta.env.DEV
const DEMO: BState = {
  ok: true, open: true, admin: true, gold: 4810, qty_max: 50, max_orders: 3,
  sells: [
    { id: 1, side: 'sell', key: 'ale1', name: 'Хмельной эль', emoji: '🍺', qty: 30, unit: 6, who: 'Кума Дарья' },
    { id: 2, side: 'sell', key: 'mead', name: 'Медовуха', emoji: '🍯', qty: 12, unit: 19, who: 'Балагур Прохор' },
  ],
  buys: [
    { id: 4, side: 'buy', key: 'cheese', name: 'Сыр', emoji: '🧀', qty: 8, unit: 16, who: 'Купец Гордей' },
    { id: 5, side: 'buy', key: 'ale3', name: 'Тройной эль', emoji: '🍺', qty: 20, unit: 17, who: 'Шинкарь Тит' },
  ],
  mine: [{ id: 6, side: 'sell', key: 'cheese', name: 'Сыр', emoji: '🧀', qty: 10, unit: 14 }],
  board: [
    { key: 'ale1', name: 'Хмельной эль', emoji: '🍺', ask: 6, ask_qty: 30, bid: 4, bid_qty: 15, floor: 3, ceil: 9 },
    { key: 'mead', name: 'Медовуха', emoji: '🍯', ask: 19, ask_qty: 12, bid: 14, bid_qty: 4, floor: 7, ceil: 22 },
    { key: 'cheese', name: 'Сыр', emoji: '🧀', ask: 14, ask_qty: 10, bid: 16, bid_qty: 8, floor: 6, ceil: 24 },
  ],
  sellers: [
    { name: 'Кривая Кружка', sold: 240, me: false },
    { name: 'African Eastern', sold: 155, me: true },
    { name: 'У дохлого песца', sold: 90, me: false },
  ],
  goods: [
    { key: 'cheese', name: 'Сыр', emoji: '🧀', stock: 18, floor: 6, ceil: 24, presets: [10, 12, 16], room: 60 },
    { key: 'mead', name: 'Медовуха', emoji: '🍯', stock: 9, floor: 7, ceil: 22, presets: [8, 11, 14], room: 60 },
    { key: 'ale1', name: 'Хмельной эль', emoji: '🍺', stock: 0, floor: 3, ceil: 9, presets: [4, 5, 7], room: 60 },
  ],
}
const bourseGet = (): Promise<BState> => DEV ? Promise.resolve(DEMO) : api<BState>('bourse')
// DEV: имитируем сделку локально, чтобы прощёлкать UI в превью (в проде — реальный эндпоинт)
function bourseAct(payload: Record<string, unknown>): Promise<BState> {
  if (!DEV) return api<BState>('bourse/act', payload)
  const r: BState = { ...DEMO }
  const msg: Record<string, string> = { buy: 'Куплено', fill: 'Продано в заявку', sell: 'Лот выставлен',
    bid: 'Заявка размещена', cancel: 'Снято' }
  return Promise.resolve({ ...r, done: `🧪 демо: ${msg[String(payload.op)] || 'готово'}` })
}

type Tab = 'buy' | 'bids' | 'prices' | 'mine'
const TABS: { id: Tab; ic: string; t: string }[] = [
  { id: 'buy', ic: '🛒', t: 'Купить' }, { id: 'bids', ic: '📣', t: 'Заявки' },
  { id: 'prices', ic: '📊', t: 'Цены' }, { id: 'mine', ic: '📦', t: 'Мои' },
]
// активное действие поверх доски
type Act =
  | { k: 'buy' | 'fill'; o: BOrder }
  | { k: 'cancel'; o: BOrder }
  | { k: 'new'; side: 'sell' | 'bid' }

function Ticket({ o, label, onClick }: { o: BOrder; label: string; onClick?: () => void }) {
  const buy = o.side === 'buy'
  return (
    <button className={`brs-tk${buy ? ' buy' : ''}${onClick ? ' tap' : ''}`} onClick={onClick} disabled={!onClick}>
      <span className="brs-tk-ic"><GoodIcon k={o.key} size={34} /></span>
      <span className="brs-tk-mid"><b>{o.name}</b>
        <small>{label} <span className="brs-tk-q">×{o.qty}</span>{o.who ? <> · {o.who}</> : null}</small></span>
      <span className="brs-tk-px"><span className="brs-tk-num"><ResIcon k="gold" size={13} />{o.unit}</span><small>за штуку</small></span>
    </button>
  )
}

export default function BourseSheet({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<BState | null>(null)
  const [tab, setTab] = useState<Tab>('prices')
  const [act, setAct] = useState<Act | null>(null)
  const [busy, setBusy] = useState(false)
  const [qty, setQty] = useState(0)
  const [price, setPrice] = useState(0)
  const [pick, setPick] = useState<BGood | null>(null)
  const [toast, setToast] = useState('')
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2400) }

  const load = () => bourseGet().then(setD).catch(() => setD({ ok: true, open: false }))
  useEffect(() => { load() }, [])
  const open = !!d?.open
  useEffect(() => {
    if (!open || act) return                        // в эфире — но не во время оформления сделки
    const i = setInterval(load, 8000)
    return () => clearInterval(i)
  }, [open, act])

  const maxQty = useMemo(() => Math.max(1, ...((d?.board || []).flatMap((b) => [b.ask_qty || 0, b.bid_qty || 0]))), [d])
  const ticker = useMemo(() => (d?.board || []).filter((b) => b.ask != null || b.bid != null), [d])
  const myStock = useMemo(() => new Map((d?.goods || []).map((g) => [g.key, g.stock])), [d])
  const tabIdx = TABS.findIndex((t) => t.id === tab)

  const closeAct = () => { setAct(null); setPick(null); setQty(0); setPrice(0) }
  async function run(payload: Record<string, unknown>) {
    if (busy) return
    setBusy(true); haptic('medium')
    try {
      const r = await bourseAct(payload)
      setD(r); hapticNotify('success'); if (r.done) flash(r.done); closeAct()
    } catch (e) {
      flash(errText(e, 'Не вышло')); hapticNotify('warning')
      if ((e as ApiError)?.code === 'gone') closeAct()
    } finally { setBusy(false) }
  }

  // лимиты для текущего действия
  const cap = (() => {
    if (!act || !d) return 0
    if (act.k === 'buy') return Math.min(act.o.qty, Math.floor((d.gold ?? 0) / act.o.unit), (myStock.has(act.o.key) ? 999 : 999))
    if (act.k === 'fill') return Math.min(act.o.qty, myStock.get(act.o.key) ?? 0)
    return 0
  })()

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="auc-sheet brs-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="brs-top">
          <div className="brs-title"><span className="brs-glyph">📈</span> Биржа Недоливска</div>
          {ticker.length > 0 && (
            <div className="brs-tape-row">
              <span className="brs-live"><span className="brs-live-dot" />в эфире</span>
              <div className="brs-tape"><div className="brs-tape-run">
                {[...ticker, ...ticker].map((b, i) => (<span key={i} className="brs-tape-q">{b.emoji}<i>{b.ask ?? b.bid}</i></span>))}
              </div></div>
            </div>
          )}
        </div>
        {toast && <div className="toast">{toast}</div>}

        {d === null ? <div className="center" style={{ padding: '40px 0' }}><div className="spin" /></div>
          : !d.open ? (
            <div className="auc-lock">
              <div className="auc-lock-emo">📈</div>
              <div className="auc-lock-h">Биржа скоро откроется</div>
              <p className="auc-lock-txt">«Купцы уже спорят за цену у весов, маклеры точат перья. Вот-вот ударим в колокол — выставляй лоты и лови барыш.»</p>
            </div>
          ) : act ? (
            // ── ПАНЕЛЬ ДЕЙСТВИЯ ──
            <div className="brs-act">
              <button className="brs-back" onClick={() => { haptic('light'); closeAct() }}>‹ назад к доске</button>

              {(act.k === 'buy' || act.k === 'fill') && (() => {
                const o = act.o, isBuy = act.k === 'buy'
                const q = Math.min(qty || 1, cap)
                const gross = q * o.unit
                return (
                  <>
                    <div className="brs-act-h"><GoodIcon k={o.key} size={40} />
                      <div><b>{o.name}</b><small>{isBuy ? `продаёт ${o.who}` : `куплю · ${o.who}`} · по {o.unit} 🪙/шт</small></div></div>
                    {cap <= 0 ? (
                      <p className="auc-empty">{isBuy ? '«Не хватает золота даже на одну штуку.»' : '«Нет такого товара в погребе.»'}</p>
                    ) : (<>
                      <div className="brs-cap">{isBuy ? 'Сколько купить' : 'Сколько продать'} · до {cap}</div>
                      <div className="brs-qtys">
                        {[5, 10, 25].filter((n) => n <= cap).map((n) => (
                          <button key={n} className={`auc-qty${q === n ? ' on' : ''}`} onClick={() => { haptic('light'); setQty(n) }}>{n}</button>
                        ))}
                        <button className={`auc-qty${q === cap ? ' on' : ''}`} onClick={() => { haptic('light'); setQty(cap) }}>Всё {cap}</button>
                      </div>
                      <button className={`btn brs-go${isBuy ? '' : ' sell'}`} disabled={busy || q <= 0}
                        onClick={() => run({ op: act.k, order_id: o.id, qty: q })}>
                        {isBuy ? <>🛒 Купить {q} · −{fmt(gross)} 🪙</> : <>📤 Продать {q} · +{fmt(Math.round(gross * 0.95))} 🪙</>}
                      </button>
                    </>)}
                  </>
                )
              })()}

              {act.k === 'cancel' && (
                <>
                  <div className="brs-act-h"><GoodIcon k={act.o.key} size={40} />
                    <div><b>{act.o.name}</b><small>{act.o.side === 'sell' ? 'твой лот' : 'твоя заявка'} · ×{act.o.qty} по {act.o.unit} 🪙</small></div></div>
                  <p className="auc-hint">{act.o.side === 'sell' ? 'Товар вернётся в погреб.' : `Залог ${fmt(act.o.qty * act.o.unit)} 🪙 вернётся.`}</p>
                  <button className="btn brs-go cancel" disabled={busy} onClick={() => run({ op: 'cancel', order_id: act.o.id })}>✋ Снять</button>
                </>
              )}

              {act.k === 'new' && (() => {
                const side = act.side, list = (d.goods || []).filter((g) => side === 'sell' ? g.stock > 0 : g.room > 0)
                if (!pick) return (
                  <>
                    <div className="brs-cap">{side === 'sell' ? 'Что продаёшь?' : 'Что хочешь купить?'}</div>
                    {list.length > 0 ? (
                      <div className="auc-goods">
                        {list.map((g) => (
                          <button key={g.key} className="auc-gtile" onClick={() => { haptic('light'); setPick(g); setQty(Math.min(5, side === 'sell' ? g.stock : g.room)); setPrice(g.presets[1] ?? g.floor) }}>
                            <GoodIcon k={g.key} size={34} /><span className="auc-gnm">{g.name}</span>
                            <span className="auc-gstock">{side === 'sell' ? `×${g.stock}` : `${g.floor}–${g.ceil}🪙`}</span>
                          </button>
                        ))}
                      </div>
                    ) : <p className="auc-empty">{side === 'sell' ? '«В погребе пусто — нечего продавать.»' : '«Лимит скупки исчерпан — загляни позже.»'}</p>}
                  </>
                )
                const max = side === 'sell' ? Math.min(pick.stock, d.qty_max ?? 50) : Math.min(pick.room, d.qty_max ?? 50, Math.floor((d.gold ?? 0) / Math.max(1, price)))
                const q = Math.min(qty || 1, Math.max(1, max))
                const inRange = price >= pick.floor && price <= pick.ceil
                return (
                  <>
                    <button className="auc-back" onClick={() => { setPick(null) }}>‹ другой товар</button>
                    <div className="brs-act-h"><GoodIcon k={pick.key} size={40} />
                      <div><b>{pick.name}</b><small>{side === 'sell' ? `в погребе ${pick.stock}` : `лимит ${pick.room}`} · коридор {pick.floor}–{pick.ceil} 🪙</small></div></div>
                    <div className="brs-cap">Объём · до {max}</div>
                    <div className="brs-qtys">
                      {[5, 10, 25].filter((n) => n <= max).map((n) => (
                        <button key={n} className={`auc-qty${q === n ? ' on' : ''}`} onClick={() => { haptic('light'); setQty(n) }}>{n}</button>
                      ))}
                      {max > 0 && <button className={`auc-qty${q === max ? ' on' : ''}`} onClick={() => setQty(max)}>Всё {max}</button>}
                    </div>
                    <div className="brs-cap">Цена за штуку · коридор {pick.floor}–{pick.ceil}</div>
                    <div className="brs-qtys">
                      {pick.presets.map((pp) => (
                        <button key={pp} className={`auc-qty${price === pp ? ' on' : ''}`} onClick={() => { haptic('light'); setPrice(pp) }}>{pp} 🪙</button>
                      ))}
                    </div>
                    <button className={`btn brs-go${side === 'sell' ? ' sell' : ''}`} disabled={busy || q <= 0 || !inRange}
                      onClick={() => run({ op: side, good: pick.key, qty: q, price })}>
                      {side === 'sell' ? <>📤 Выставить {q} по {price} 🪙</> : <>📣 Куплю {q} по {price} 🪙 (залог {fmt(q * price)})</>}
                    </button>
                  </>
                )
              })()}
            </div>
          ) : (
            <>
              <div className="brs-seg" style={{ ['--i' as string]: tabIdx }}>
                <div className="brs-seg-glow" />
                {TABS.map((t) => {
                  const cnt = t.id === 'buy' ? d.sells?.length : t.id === 'bids' ? d.buys?.length : t.id === 'mine' ? d.mine?.length : 0
                  return (
                    <button key={t.id} className={`brs-seg-b${tab === t.id ? ' on' : ''}`} onClick={() => { haptic('light'); setTab(t.id) }}>
                      <span className="brs-seg-ic">{t.ic}</span>{t.t}{!!cnt && <span className="brs-seg-n">{cnt}</span>}
                    </button>
                  )
                })}
              </div>

              <div className="brs-body">
                {tab === 'buy' && (
                  (d.sells && d.sells.length > 0) ? d.sells.map((o) => <Ticket key={o.id} o={o} label="продают" onClick={() => { haptic('light'); setQty(0); setAct({ k: 'buy', o }) }} />)
                    : <p className="auc-empty">«На прилавках пусто — никто не выставил товар. Свой лот — во вкладке «Мои».»</p>
                )}

                {tab === 'bids' && (
                  (d.buys && d.buys.length > 0) ? d.buys.map((o) => <Ticket key={o.id} o={o} label="ищут" onClick={() => { haptic('light'); setQty(0); setAct({ k: 'fill', o }) }} />)
                    : <p className="auc-empty">«Заявок на скупку нет. Свою заявку «куплю» — во вкладке «Мои».»</p>
                )}

                {tab === 'prices' && (<>
                  <div className="brs-depth-leg">
                    <span className="brs-leg-side"><span className="dot bid" />спрос · купят</span>
                    <span className="brs-leg-side ask">продают · предложение<span className="dot ask" /></span>
                  </div>
                  {(d.board && d.board.length > 0) ? d.board.map((b, idx) => {
                    const bidW = b.bid_qty ? Math.max(7, (b.bid_qty / maxQty) * 100) : 0
                    const askW = b.ask_qty ? Math.max(7, (b.ask_qty / maxQty) * 100) : 0
                    const spread = (b.ask != null && b.bid != null) ? b.ask - b.bid : null
                    const range = Math.max(1, b.ceil - b.floor)
                    const pos = (p: number) => Math.min(100, Math.max(0, ((p - b.floor) / range) * 100))
                    const bidPos = b.bid != null ? pos(b.bid) : null
                    const askPos = b.ask != null ? pos(b.ask) : null
                    const stock = myStock.get(b.key) || 0
                    const profit = stock > 0 && b.bid != null
                    return (
                      <div key={b.key} className={`brs-dp${stock ? ' mine' : ''}`} style={{ ['--di' as string]: idx }}>
                        <div className="brs-dp-head">
                          <span className="brs-dp-nm"><GoodIcon k={b.key} size={22} />{b.name}{stock ? <span className="brs-dp-mine">🎒 {stock}</span> : null}</span>
                          <span className="brs-dp-tags">
                            {profit ? <span className="brs-dp-profit">💰 берут {b.bid}</span> : null}
                            {spread != null ? <span className="brs-dp-spread">спред {spread}</span> : null}
                          </span>
                        </div>
                        <div className="brs-dp-bars">
                          <div className="brs-dp-side bid">
                            {b.bid != null ? (<><span className="brs-dp-px">{b.bid}{b.bid_qty ? <i>×{b.bid_qty}</i> : null}</span><span className="brs-dp-bar" style={{ width: `${bidW}%` }} /></>) : <span className="brs-dp-none">нет спроса</span>}
                          </div>
                          <span className="brs-dp-mid" />
                          <div className="brs-dp-side ask">
                            {b.ask != null ? (<><span className="brs-dp-bar" style={{ width: `${askW}%` }} /><span className="brs-dp-px">{b.ask}{b.ask_qty ? <i>×{b.ask_qty}</i> : null}</span></>) : <span className="brs-dp-none">нет лотов</span>}
                          </div>
                        </div>
                        <div className="brs-dp-corr">
                          <span className="brs-dp-edge">{b.floor}</span>
                          <div className="brs-dp-track">
                            {bidPos != null && askPos != null && askPos >= bidPos && <span className="brs-dp-fill" style={{ left: `${bidPos}%`, width: `${askPos - bidPos}%` }} />}
                            {bidPos != null && <span className="brs-dp-mark bid" style={{ left: `${bidPos}%` }} />}
                            {askPos != null && <span className="brs-dp-mark ask" style={{ left: `${askPos}%` }} />}
                          </div>
                          <span className="brs-dp-edge">{b.ceil}</span>
                        </div>
                      </div>
                    )
                  }) : <p className="auc-empty">«Пусто — ни лотов, ни заявок.»</p>}

                  {d.sellers && d.sellers.length > 0 && (
                    <div className="brs-lead">
                      <div className="brs-sec-h">🏆 Лучшие купцы мира</div>
                      {d.sellers.slice(0, 5).map((s, i) => (
                        <div key={i} className={`brs-ld${s.me ? ' me' : ''}`}>
                          <span className={`brs-ld-rk r${i + 1}`}>{['①', '②', '③'][i] || i + 1}</span>
                          <span className="brs-ld-nm">{s.name}{s.me ? ' · ты' : ''}</span>
                          <span className="brs-ld-bar"><i style={{ width: `${Math.round((s.sold / (d.sellers![0].sold || 1)) * 100)}%` }} /></span>
                          <span className="brs-ld-n">{fmt(s.sold)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>)}

                {tab === 'mine' && (<>
                  <div className="brs-new-row">
                    <button className="brs-new sell" onClick={() => { haptic('light'); setAct({ k: 'new', side: 'sell' }) }}>📤 Продать</button>
                    <button className="brs-new" onClick={() => { haptic('light'); setAct({ k: 'new', side: 'bid' }) }}>📣 Куплю</button>
                  </div>
                  {(d.mine && d.mine.length > 0) ? d.mine.map((o) => (
                    <div key={o.id} className="brs-mine-row">
                      <Ticket o={o} label={o.side === 'sell' ? 'продаю' : 'куплю'} />
                      <button className="brs-mine-x" disabled={busy} onClick={() => { haptic('light'); setAct({ k: 'cancel', o }) }}>✋</button>
                    </div>
                  )) : <p className="auc-empty">«У тебя нет ни лотов, ни заявок на бирже.»</p>}
                </>)}
              </div>

              <p className="auc-hint">📡 Цены в реальном времени. Налог биржи с продажи — 5%.</p>
            </>
          )}

        <button className="btn auc-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
