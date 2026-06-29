import { useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { GoodIcon, ResIcon, fmt } from '../components/icons'

export interface TradeData {
  good: string; name: string; emoji: string; qty: number
  merchant: string; memoji: string; avatar: number | null
  intro: string; fv: number; prices: number[]; counter?: number | null
}
interface TradeResp {
  ok: boolean; result?: 'sold' | 'counter' | 'walk'; react?: string
  qty?: number; gold?: number; unit?: number; trade?: TradeData | null; state?: unknown
}

const TIER = ['подешевле', 'по рынку', 'втридорога']
const npcSrc = (a: number | null) => a ? `${import.meta.env.BASE_URL}npc/${a}.png` : ''

// DEV: имитация торга для превью (в проде — реальный /api/trade, мок вырезается)
const DEV = import.meta.env.DEV
function tradeApi(op: string, idx: number | undefined, d: TradeData): Promise<TradeResp> {
  if (!DEV) return api<TradeResp>('trade', idx != null ? { op, idx } : { op })
  if (op === 'decline') return Promise.resolve({ ok: true, result: 'walk', react: '«Тьфу! Грабёж средь бела дня. Бывай»' })
  if (op === 'offer') {
    const unit = d.prices[idx ?? 0]
    if (idx === 2) return Promise.resolve({ ok: true, result: 'counter', react: '«Знаю я рынок: красная цена — вот столько. Ну так что?»', trade: { ...d, counter: Math.round(d.prices[1]) } })
    return Promise.resolve({ ok: true, result: 'sold', react: '«Цена честная. По рукам»', qty: d.qty, gold: unit * d.qty, unit })
  }
  if (op === 'accept') { const u = d.counter || d.prices[1]; return Promise.resolve({ ok: true, result: 'sold', react: '«Вот это по-нашему. Заверни»', qty: d.qty, gold: u * d.qty, unit: u }) }
  if (op === 'push') return Promise.resolve({ ok: true, result: 'counter', react: '«Эх… ну чуть накину, последний раз»', trade: { ...d, counter: (d.counter || 0) + 1 } })
  return Promise.resolve({ ok: true, result: 'walk', react: '' })
}

function Portrait({ d, size = 56 }: { d: TradeData; size?: number }) {
  const [bad, setBad] = useState(false)
  if (d.avatar && !bad) return <img className="trd-face" style={{ width: size, height: size }} src={npcSrc(d.avatar)} alt="" onError={() => setBad(true)} />
  return <span className="trd-face trd-face-emo" style={{ width: size, height: size, fontSize: size * 0.5 }}>{d.memoji}</span>
}

export default function TradeSheet({ offer, onClose, onState }: {
  offer: TradeData; onClose: () => void; onState?: (st: unknown) => void
}) {
  const [d, setD] = useState<TradeData>(offer)
  const [phase, setPhase] = useState<'deal' | 'sold' | 'walk'>('deal')
  const [react, setReact] = useState('')
  const [sold, setSold] = useState<{ qty: number; gold: number; unit: number } | null>(null)
  const [busy, setBusy] = useState(false)

  async function act(op: string, idx?: number) {
    if (busy) return
    setBusy(true); haptic('medium')
    try {
      const r = await tradeApi(op, idx, d)
      if (r.state) onState?.(r.state)
      setReact(r.react || '')
      if (r.result === 'sold') { setSold({ qty: r.qty || 0, gold: r.gold || 0, unit: r.unit || 0 }); setPhase('sold'); hapticNotify('success') }
      else if (r.result === 'walk') { setPhase('walk'); hapticNotify('warning') }
      else if (r.result === 'counter' && r.trade) { setD(r.trade); haptic('light') }
    } catch { setPhase('walk') }
    finally { setBusy(false) }
  }

  const haggling = d.counter != null

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="sv-card trd-card" onClick={(e) => e.stopPropagation()}>
        <div className="trd-top">
          <Portrait d={d} />
          <div className="trd-id">
            <div className="trd-name">{d.memoji} {d.merchant}</div>
            <div className="trd-intro">{d.intro}</div>
          </div>
        </div>

        <div className="trd-want">
          <GoodIcon k={d.good} size={34} />
          <div className="trd-want-t"><b>{d.name} ×{d.qty}</b><small>рынок ~{d.fv} 🪙/шт</small></div>
        </div>

        {phase === 'sold' ? (
          <>
            <div className="trd-deal"><ResIcon k="gold" size={26} />+{fmt(sold?.gold || 0)}</div>
            <div className="trd-deal-sub">продал {sold?.qty} × по {sold?.unit} 🪙/шт</div>
            {react && <p className="trd-react sold">{react}</p>}
            <button className="btn trd-ok" onClick={() => { haptic('light'); onClose() }}>🍺 Готово</button>
          </>
        ) : phase === 'walk' ? (
          <>
            {react && <p className="trd-react walk">{react}</p>}
            <div className="trd-gone">— купец ушёл —</div>
            <button className="btn trd-ok" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
          </>
        ) : haggling ? (
          // ── идёт торг: купец дал контр-цену ──
          <>
            {react && <p className="trd-react">{react}</p>}
            <div className="trd-counter">даёт <b>{d.counter}</b> 🪙/шт · куш ≈ {fmt((d.counter || 0) * d.qty)} 🪙</div>
            <div className="trd-acts">
              <button className="btn trd-yes" disabled={busy} onClick={() => act('accept')}>✋ По рукам — {d.counter} 🪙</button>
              <div className="trd-acts-row">
                <button className="btn trd-push" disabled={busy} onClick={() => act('push')}>💪 Дожать ещё</button>
                <button className="btn trd-no" disabled={busy} onClick={() => act('decline')}>Прогнать</button>
              </div>
            </div>
          </>
        ) : (
          // ── первый ход: предложи цену ──
          <>
            <p className="trd-hint">Заломи цену — горожанин поторгуется или возьмёт.</p>
            <div className="trd-tiers">
              {d.prices.map((pp, i) => (
                <button key={i} className="trd-tier" disabled={busy} onClick={() => act('offer', i)}>
                  <span className="trd-tier-lbl">{TIER[i]}</span>
                  <span className="trd-tier-px">{pp} 🪙/шт</span>
                  <span className="trd-tier-tot">≈ {fmt(pp * d.qty)} 🪙</span>
                </button>
              ))}
            </div>
            <button className="btn trd-no full" disabled={busy} onClick={() => act('decline')}>Прогнать купца</button>
          </>
        )}
      </div>
    </div>
  )
}
