import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { haptic } from '../telegram'
import { GoodIcon, ResIcon, fmt } from '../components/icons'

interface BOrder { id: number; side: string; qty: number; unit: number; key: string; name: string; emoji: string; who?: string }
interface BRow { key: string; name: string; emoji: string; ask?: number | null; ask_qty?: number | null; bid?: number | null; bid_qty?: number | null; floor: number; ceil: number }
interface BSeller { name: string; sold: number; me: boolean }
interface BGood { key: string; name: string; emoji: string; stock: number }
interface BState {
  ok: boolean; open: boolean; admin?: boolean; gold?: number
  sells?: BOrder[]; buys?: BOrder[]; mine?: BOrder[]; board?: BRow[]; sellers?: BSeller[]; goods?: BGood[]
}

// ── ПРЕВЬЮ-ДЕМО (только import.meta.env.DEV) — на localhost нет реальных ордеров.
// В прод-сборке вырезается. См. [[miniapp-no-sample-in-prod]].
const DEV = import.meta.env.DEV
const DEMO: BState = {
  ok: true, open: true, admin: true, gold: 4810,
  sells: [
    { id: 1, side: 'sell', key: 'ale1', name: 'Хмельной эль', emoji: '🍺', qty: 30, unit: 6, who: 'Кума Дарья' },
    { id: 2, side: 'sell', key: 'mead', name: 'Медовуха', emoji: '🍯', qty: 12, unit: 19, who: 'Балагур Прохор' },
    { id: 3, side: 'sell', key: 'bread', name: 'Хлеб', emoji: '🍞', qty: 50, unit: 7, who: 'Пекарь Влас' },
  ],
  buys: [
    { id: 4, side: 'buy', key: 'roast', name: 'Жаркое', emoji: '🍖', qty: 8, unit: 24, who: 'Купец Гордей' },
    { id: 5, side: 'buy', key: 'ale3', name: 'Тройной эль', emoji: '🍺', qty: 20, unit: 17, who: 'Шинкарь Тит' },
  ],
  mine: [
    { id: 6, side: 'sell', key: 'cheese', name: 'Сыр', emoji: '🧀', qty: 10, unit: 14 },
  ],
  board: [
    { key: 'ale1', name: 'Хмельной эль', emoji: '🍺', ask: 6, ask_qty: 30, bid: 4, bid_qty: 15, floor: 3, ceil: 9 },
    { key: 'mead', name: 'Медовуха', emoji: '🍯', ask: 19, ask_qty: 12, bid: 14, bid_qty: 4, floor: 7, ceil: 22 },
    { key: 'roast', name: 'Жаркое', emoji: '🍖', ask: null, ask_qty: null, bid: 24, bid_qty: 8, floor: 5, ceil: 28 },
    { key: 'bread', name: 'Хлеб', emoji: '🍞', ask: 7, ask_qty: 50, bid: 5, bid_qty: 22, floor: 4, ceil: 10 },
  ],
  sellers: [
    { name: 'Кривая Кружка', sold: 240, me: false },
    { name: 'African Eastern', sold: 155, me: true },
    { name: 'У дохлого песца', sold: 90, me: false },
  ],
  goods: [{ key: 'cheese', name: 'Сыр', emoji: '🧀', stock: 18 }, { key: 'mead', name: 'Медовуха', emoji: '🍯', stock: 9 }],
}
const bourseApi = (): Promise<BState> => DEV ? Promise.resolve(DEMO) : api<BState>('bourse')

type Tab = 'buy' | 'bids' | 'prices' | 'mine'
const TABS: { id: Tab; ic: string; t: string }[] = [
  { id: 'buy', ic: '🛒', t: 'Купить' }, { id: 'bids', ic: '📣', t: 'Заявки' },
  { id: 'prices', ic: '📊', t: 'Цены' }, { id: 'mine', ic: '📦', t: 'Мои' },
]

/** Глассовый «трейд-тикет» ордера. buy=зелёный (заявка), sell=золото (продажа). */
function Ticket({ o, label }: { o: BOrder; label: string }) {
  const buy = o.side === 'buy'
  return (
    <div className={`brs-tk${buy ? ' buy' : ''}`} style={{ ['--d' as string]: '0ms' }}>
      <div className="brs-tk-ic"><GoodIcon k={o.key} size={34} /></div>
      <div className="brs-tk-mid">
        <b>{o.name}</b>
        <small>{label} <span className="brs-tk-q">×{o.qty}</span>{o.who ? <> · {o.who}</> : null}</small>
      </div>
      <div className="brs-tk-px">
        <span className="brs-tk-num"><ResIcon k="gold" size={13} />{o.unit}</span>
        <small>за штуку</small>
      </div>
    </div>
  )
}

export default function BourseSheet({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<BState | null>(null)
  const [tab, setTab] = useState<Tab>('prices')

  const load = () => bourseApi().then(setD).catch(() => setD({ ok: true, open: false }))
  useEffect(() => { load() }, [])
  // «в эфире»: тихо подтягиваем свежие цены раз в 8с (как в торговом терминале)
  const open = !!d?.open
  useEffect(() => {
    if (!open) return
    const i = setInterval(load, 8000)
    return () => clearInterval(i)
  }, [open])

  // нормировка глубины стакана: бары bid/ask относительно макс. объёма по доске
  const maxQty = useMemo(() => Math.max(1, ...((d?.board || []).flatMap((b) => [b.ask_qty || 0, b.bid_qty || 0]))), [d])
  // лента котировок (лучшие цены) для бегущей строки
  const ticker = useMemo(() => (d?.board || []).filter((b) => b.ask != null || b.bid != null), [d])
  // погреб: что у меня есть на продажу — для подсветки «твой товар»/«выгодно»
  const myStock = useMemo(() => new Map((d?.goods || []).map((g) => [g.key, g.stock])), [d])
  const tabIdx = TABS.findIndex((t) => t.id === tab)

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="auc-sheet brs-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="brs-top">
          <div className="brs-title"><span className="brs-glyph">📈</span> Биржа Недоливска</div>
          {ticker.length > 0 && (
            <div className="brs-tape-row">
              <span className="brs-live"><span className="brs-live-dot" />в эфире</span>
              <div className="brs-tape"><div className="brs-tape-run">
                {[...ticker, ...ticker].map((b, i) => (
                  <span key={i} className="brs-tape-q">{b.emoji}<i>{b.ask ?? b.bid}</i></span>
                ))}
              </div></div>
            </div>
          )}
        </div>

        {d === null ? <div className="center" style={{ padding: '40px 0' }}><div className="spin" /></div>
          : !d.open ? (
            <div className="auc-lock">
              <div className="auc-lock-emo">📈</div>
              <div className="auc-lock-h">Биржа скоро откроется</div>
              <p className="auc-lock-txt">«Купцы уже спорят за цену у весов, маклеры точат перья. Вот-вот ударим в колокол — выставляй лоты и лови барыш.»</p>
            </div>
          ) : (
            <>
              <div className="brs-seg" style={{ ['--i' as string]: tabIdx }}>
                <div className="brs-seg-glow" />
                {TABS.map((t) => {
                  const cnt = t.id === 'buy' ? d.sells?.length : t.id === 'bids' ? d.buys?.length : t.id === 'mine' ? d.mine?.length : 0
                  return (
                    <button key={t.id} className={`brs-seg-b${tab === t.id ? ' on' : ''}`} onClick={() => { haptic('light'); setTab(t.id) }}>
                      <span className="brs-seg-ic">{t.ic}</span>{t.t}
                      {!!cnt && <span className="brs-seg-n">{cnt}</span>}
                    </button>
                  )
                })}
              </div>

              <div className="brs-body">
                {tab === 'buy' && (
                  (d.sells && d.sells.length > 0) ? d.sells.map((o) => <Ticket key={o.id} o={o} label="продают" />)
                    : <p className="auc-empty">«На прилавках пусто — никто не выставил товар на продажу.»</p>
                )}

                {tab === 'bids' && (
                  (d.buys && d.buys.length > 0) ? d.buys.map((o) => <Ticket key={o.id} o={o} label="ищут" />)
                    : <p className="auc-empty">«Заявок на скупку нет — никто пока не ищет товар.»</p>
                )}

                {tab === 'prices' && (
                  <>
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
                      const profit = stock > 0 && b.bid != null   // есть товар + кто-то его берёт
                      return (
                        <div key={b.key} className={`brs-dp${stock ? ' mine' : ''}`} style={{ ['--di' as string]: idx }}>
                          <div className="brs-dp-head">
                            <span className="brs-dp-nm"><GoodIcon k={b.key} size={22} />{b.name}
                              {stock ? <span className="brs-dp-mine">🎒 {stock}</span> : null}</span>
                            <span className="brs-dp-tags">
                              {profit ? <span className="brs-dp-profit">💰 берут {b.bid}</span> : null}
                              {spread != null ? <span className="brs-dp-spread">спред {spread}</span> : null}
                            </span>
                          </div>
                          <div className="brs-dp-bars">
                            <div className="brs-dp-side bid">
                              {b.bid != null ? (<>
                                <span className="brs-dp-px">{b.bid}{b.bid_qty ? <i>×{b.bid_qty}</i> : null}</span>
                                <span className="brs-dp-bar" style={{ width: `${bidW}%` }} />
                              </>) : <span className="brs-dp-none">нет спроса</span>}
                            </div>
                            <span className="brs-dp-mid" />
                            <div className="brs-dp-side ask">
                              {b.ask != null ? (<>
                                <span className="brs-dp-bar" style={{ width: `${askW}%` }} />
                                <span className="brs-dp-px">{b.ask}{b.ask_qty ? <i>×{b.ask_qty}</i> : null}</span>
                              </>) : <span className="brs-dp-none">нет лотов</span>}
                            </div>
                          </div>
                          <div className="brs-dp-corr">
                            <span className="brs-dp-edge">{b.floor}</span>
                            <div className="brs-dp-track">
                              {bidPos != null && askPos != null && askPos >= bidPos &&
                                <span className="brs-dp-fill" style={{ left: `${bidPos}%`, width: `${askPos - bidPos}%` }} />}
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
                  </>
                )}

                {tab === 'mine' && (
                  (d.mine && d.mine.length > 0) ? d.mine.map((o) => <Ticket key={o.id} o={o} label={o.side === 'sell' ? 'продаю' : 'куплю'} />)
                    : <p className="auc-empty">«У тебя нет ни лотов, ни заявок на бирже.»</p>
                )}
              </div>

              <p className="auc-hint">📡 Цены в реальном времени. Купля-продажа и заявки — следующей волной.</p>
            </>
          )}

        <button className="btn auc-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
