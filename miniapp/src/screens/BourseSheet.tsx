import { useEffect, useState } from 'react'
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
    { key: 'mead', name: 'Медовуха', emoji: '🍯', ask: 19, ask_qty: 12, bid: null, bid_qty: null, floor: 7, ceil: 22 },
    { key: 'roast', name: 'Жаркое', emoji: '🍖', ask: null, ask_qty: null, bid: 24, bid_qty: 8, floor: 5, ceil: 28 },
  ],
  sellers: [
    { name: 'Кривая Кружка', sold: 240, me: false },
    { name: 'African Eastern', sold: 155, me: true },
    { name: 'У дохлого песца', sold: 90, me: false },
  ],
  goods: [{ key: 'cheese', name: 'Сыр', emoji: '🧀', stock: 18 }],
}
const bourseApi = (): Promise<BState> => DEV ? Promise.resolve(DEMO) : api<BState>('bourse')

type Tab = 'buy' | 'bids' | 'prices' | 'mine'

export default function BourseSheet({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<BState | null>(null)
  const [tab, setTab] = useState<Tab>('buy')

  useEffect(() => { bourseApi().then(setD).catch(() => setD({ ok: true, open: false })) }, [])

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="auc-sheet brs-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="auc-head">📈 Биржа Недоливска</div>

        {d === null ? <div className="center" style={{ padding: '40px 0' }}><div className="spin" /></div>
          : !d.open ? (
            <div className="auc-lock">
              <div className="auc-lock-emo">📈</div>
              <div className="auc-lock-h">Биржа скоро откроется</div>
              <p className="auc-lock-txt">«Купцы уже спорят за цену у весов, маклеры точат перья. Вот-вот ударим в колокол — выставляй лоты и лови барыш.»</p>
            </div>
          ) : (
            <>
              <div className="brs-tabs">
                <button className={`brs-tab${tab === 'buy' ? ' on' : ''}`} onClick={() => { haptic('light'); setTab('buy') }}>🛒 Купить</button>
                <button className={`brs-tab${tab === 'bids' ? ' on' : ''}`} onClick={() => { haptic('light'); setTab('bids') }}>📣 Заявки</button>
                <button className={`brs-tab${tab === 'prices' ? ' on' : ''}`} onClick={() => { haptic('light'); setTab('prices') }}>📊 Цены</button>
                <button className={`brs-tab${tab === 'mine' ? ' on' : ''}`} onClick={() => { haptic('light'); setTab('mine') }}>📦 Мои</button>
              </div>

              <div className="brs-body">
                {tab === 'buy' && (
                  (d.sells && d.sells.length > 0) ? d.sells.map((o) => (
                    <div key={o.id} className="brs-row">
                      <GoodIcon k={o.key} size={30} />
                      <div className="brs-row-id"><b>{o.name}</b><small>×{o.qty} · {o.who}</small></div>
                      <div className="brs-row-px"><span className="brs-px"><ResIcon k="gold" size={12} />{o.unit}</span><small>/шт</small></div>
                    </div>
                  )) : <p className="auc-empty">«На прилавках пусто — никто не выставил товар на продажу.»</p>
                )}

                {tab === 'bids' && (
                  (d.buys && d.buys.length > 0) ? d.buys.map((o) => (
                    <div key={o.id} className="brs-row">
                      <GoodIcon k={o.key} size={30} />
                      <div className="brs-row-id"><b>{o.name}</b><small>хотят ×{o.qty} · {o.who}</small></div>
                      <div className="brs-row-px"><span className="brs-px buy"><ResIcon k="gold" size={12} />{o.unit}</span><small>/шт</small></div>
                    </div>
                  )) : <p className="auc-empty">«Заявок на скупку нет — никто пока не ищет товар.»</p>
                )}

                {tab === 'prices' && (
                  <>
                    <div className="brs-board-h"><span>товар</span><span>покупка</span><span>продажа</span></div>
                    {(d.board && d.board.length > 0) ? d.board.map((b) => (
                      <div key={b.key} className="brs-board-row">
                        <span className="brs-bg"><GoodIcon k={b.key} size={22} />{b.name}</span>
                        <span className="brs-bid">{b.bid != null ? `${b.bid}` : '—'}{b.bid_qty ? <small> ×{b.bid_qty}</small> : null}</span>
                        <span className="brs-ask">{b.ask != null ? `${b.ask}` : '—'}{b.ask_qty ? <small> ×{b.ask_qty}</small> : null}</span>
                      </div>
                    )) : <p className="auc-empty">«Стакан пуст — ни лотов, ни заявок.»</p>}
                    {d.sellers && d.sellers.length > 0 && (
                      <div className="brs-sellers">
                        <div className="brs-sec-h">🏆 Лучшие продавцы</div>
                        {d.sellers.map((s, i) => (
                          <div key={i} className={`brs-seller${s.me ? ' me' : ''}`}>
                            <span className="brs-medal">{['🥇', '🥈', '🥉'][i] || `${i + 1}.`}</span>
                            <span className="brs-seller-nm">{s.name}{s.me ? ' (ты)' : ''}</span>
                            <span className="brs-seller-n">{fmt(s.sold)} ед.</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}

                {tab === 'mine' && (
                  (d.mine && d.mine.length > 0) ? d.mine.map((o) => (
                    <div key={o.id} className="brs-row">
                      <GoodIcon k={o.key} size={30} />
                      <div className="brs-row-id"><b>{o.name}</b><small>{o.side === 'sell' ? 'продаю' : 'куплю'} ×{o.qty}</small></div>
                      <div className="brs-row-px"><span className={`brs-px${o.side === 'buy' ? ' buy' : ''}`}><ResIcon k="gold" size={12} />{o.unit}</span><small>/шт</small></div>
                    </div>
                  )) : <p className="auc-empty">«У тебя нет ни лотов, ни заявок на бирже.»</p>
                )}
              </div>

              <p className="auc-hint">📈 Биржа — обкатка. Купля-продажа и заявки подключатся следующей волной; сейчас видно стакан и цены.</p>
            </>
          )}

        <button className="btn auc-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
