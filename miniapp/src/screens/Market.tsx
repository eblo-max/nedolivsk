import { useEffect, useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { ResIcon, fmt } from '../components/icons'
import Sheet from '../components/Sheet'

interface ShopItem { key: string; name: string; emoji: string; price: number; room: number; limit: number; max: number; have: number }
interface TorgState { ok: boolean; open: boolean; gold?: number; limit?: number; shop?: ShopItem[] }

/** Торг: скупщик (купить сырьё за золото). Закрыт для всех (lock-экран), кроме
 * админа/флага TORG_OPEN — гейт серверный. Аукцион и биржа — «скоро». */
export default function Market() {
  const [d, setD] = useState<TorgState | null>(null)
  const [pick, setPick] = useState<ShopItem | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2000) }

  const load = () => api<TorgState>('torg').then(setD).catch(() => setD({ ok: true, open: false }))
  useEffect(() => { load() }, [])

  async function buy(it: ShopItem, qty: number) {
    if (busy || qty <= 0) return
    setBusy(true); haptic('medium')
    try {
      const r = await api<TorgState & { bought?: { qty: number; cost: number } }>('torg/buy', { res: it.key, qty })
      setD(r); hapticNotify('success')
      flash(`+${r.bought?.qty ?? qty} ${it.name} · −${fmt(r.bought?.cost ?? 0)} 🪙`)
      const upd = r.shop?.find((x) => x.key === it.key)
      setPick(upd && upd.max > 0 ? upd : null)
    } catch (e) {
      flash((e as { code?: string })?.code === 'cant' ? 'Не по карману или лимит' : 'Не вышло'); hapticNotify('warning')
    } finally { setBusy(false) }
  }

  if (!d) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>

  // ── ЗАКРЫТО: lock-экран для всех ──
  if (!d.open) return (
    <div className="scr">
      <div className="torg-lock rise">
        <div className="torg-lock-emo">🔒</div>
        <div className="torg-lock-h">Сегодня Торг откроется</div>
        <p className="torg-lock-txt">«Скупщик точит карандаш, купцы тащат тюки, на бирже уже бранятся за цену. Загляни чуть погодя — вот-вот распахнём ставни.»</p>
        <div className="torg-lock-soon">🛒 Скупщик · 🔨 Аукцион · 📈 Биржа</div>
      </div>
    </div>
  )

  // ── ОТКРЫТО (админ/флаг): скупщик ──
  return (
    <div className="scr">
      {toast && <div className="toast">{toast}</div>}
      <div className="hero rise" style={{ paddingBottom: 0 }}>
        <div className="nm">Торг</div>
        <div className="flavor" style={{ margin: '6px 14px 0', fontSize: 13.5 }}>«Скупщик берёт втридорога, да зато сразу — золото в дело.»</div>
      </div>

      <div className="card rise" style={{ animationDelay: '.04s' }}>
        <div className="card-h"><span className="he">🛒</span>ЛАВКА СКУПЩИКА
          <span className="cnt"><ResIcon k="gold" size={15} /> {fmt(d.gold ?? 0)}</span></div>
        <div className="card-b">
          <p className="muted" style={{ fontStyle: 'italic', margin: '0 0 6px', fontSize: 13 }}>Сырьё вылазок за золото. Дневной лимит — {d.limit}/сутки на ресурс.</p>
          <div className="torg-grid">
            {(d.shop || []).map((it) => (
              <button key={it.key} className="torg-tile" disabled={busy} onClick={() => { haptic('light'); setPick(it) }}>
                <ResIcon k={it.key} size={30} />
                <span className="torg-nm">{it.name}</span>
                <span className="torg-pr"><ResIcon k="gold" size={12} /> {it.price}<small>/шт</small></span>
                <span className={`torg-room ${it.room <= 0 ? 'out' : ''}`}>{it.room <= 0 ? 'лимит' : `ост. ${it.room}`}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="card rise" style={{ animationDelay: '.1s' }}>
        <div className="card-h"><span className="he">🔨</span>АУКЦИОН<span className="cnt">скоро</span></div>
        <div className="card-b"><span className="muted" style={{ fontStyle: 'italic' }}>Лоты между игроками — на подходе.</span></div>
      </div>
      <div className="card rise" style={{ animationDelay: '.14s' }}>
        <div className="card-h"><span className="he">📈</span>БИРЖА<span className="cnt">скоро</span></div>
        <div className="card-b"><span className="muted" style={{ fontStyle: 'italic' }}>Котировки и сбыт оптом — на подходе.</span></div>
      </div>

      {pick && (
        <Sheet title={`🛒 ${pick.emoji} ${pick.name}`} onClose={() => setPick(null)}>
          <p className="bd-desc">Цена <b>{pick.price} 🪙</b>/шт · в погребе <b>{pick.have}</b> · сегодня можно ещё <b>{pick.room}</b></p>
          {pick.max <= 0 ? (
            <p className="muted" style={{ fontStyle: 'italic', marginTop: 8 }}>
              {pick.room <= 0 ? 'Дневной лимит на этот ресурс исчерпан — заходи завтра.' : 'Не хватает золота на покупку.'}
            </p>
          ) : (
            <div className="kv-list">
              {[10, 50, 100].filter((q) => q <= pick.max).map((q) => (
                <button key={q} className="heal-opt" disabled={busy} onClick={() => buy(pick, q)}>
                  <span>×{q}</span><b><ResIcon k="gold" size={14} /> {fmt(q * pick.price)}</b>
                </button>
              ))}
              <button className="btn gold" style={{ marginTop: 6 }} disabled={busy} onClick={() => buy(pick, pick.max)}>
                Взять максимум ×{pick.max} · {fmt(pick.max * pick.price)} 🪙
              </button>
            </div>
          )}
        </Sheet>
      )}
    </div>
  )
}
