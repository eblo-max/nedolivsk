import { useEffect, useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify, openTgLink } from '../telegram'
import { ResIcon, fmt } from '../components/icons'
import Sheet from '../components/Sheet'

interface ShopItem { key: string; name: string; emoji: string; price: number; room: number; limit: number; max: number; have: number }
interface TorgState { ok: boolean; open: boolean; gold?: number; limit?: number; shop?: ShopItem[] }

const MERCHANT = `${import.meta.env.BASE_URL}npc/15.png`   // аватар скупщика

/** Торг: лавка скупщика (купить сырьё за золото). Закрыт для всех (ставни + замок),
 * кроме админа/флага TORG_OPEN — гейт серверный. Аукцион и биржа — «скоро». */
export default function Market() {
  const [d, setD] = useState<TorgState | null>(null)
  const [pick, setPick] = useState<ShopItem | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const [avOk, setAvOk] = useState(true)
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

  // ── ЗАКРЫТО: ставни лавки с замком ──
  if (!d.open) return (
    <div className="scr torg-closed">
      <div className="torg-stall rise">
        <div className="torg-stall-sign">— ЛАВКА ЗАКРЫТА —</div>
        <div className="torg-shutters">
          <i className="torg-plank l" /><i className="torg-plank r" />
          <span className="torg-bolt b1" /><span className="torg-bolt b2" />
          <div className="torg-pad">🔒</div>
        </div>
      </div>
      <div className="torg-lock-h rise" style={{ animationDelay: '.06s' }}>Сегодня Торг откроется</div>
      <p className="torg-lock-txt rise" style={{ animationDelay: '.1s' }}>«Скупщик точит карандаш, купцы тащат тюки, на бирже уже бранятся за цену. Загляни чуть погодя — вот-вот распахнём ставни.»</p>
      <div className="torg-lock-soon rise" style={{ animationDelay: '.14s' }}>🛒 Скупщик · 🔨 Аукцион · 📈 Биржа</div>
      <button className="btn torg-chan rise" style={{ animationDelay: '.18s' }} onClick={() => { haptic('light'); openTgLink('https://t.me/nedolivsk') }}>📣 Узнать о запуске — @nedolivsk</button>
    </div>
  )

  // ── ОТКРЫТО (админ/флаг): лавка скупщика ──
  return (
    <div className="scr">
      {toast && <div className="toast">{toast}</div>}

      {/* купеческий баннер */}
      <div className="torg-merchant rise">
        <div className="torg-mav">
          {avOk ? <img src={MERCHANT} alt="" onError={() => setAvOk(false)} /> : <span className="torg-mav-emo">⚖️</span>}
        </div>
        <div className="torg-minfo">
          <div className="torg-mname">Скупщик</div>
          <div className="torg-mline">«Беру всё, плачу золотом — да втридорога, не обессудь.»</div>
        </div>
        <div className="torg-pouch"><ResIcon k="gold" size={20} /><b>{fmt(d.gold ?? 0)}</b></div>
      </div>

      {/* лавка — ящики с товаром */}
      <div className="torg-cap">🛒 Лавка скупщика<span>сырьё за золото · лимит {d.limit}/сутки</span></div>
      <div className="torg-grid">
        {(d.shop || []).map((it) => {
          const used = Math.max(0, it.limit - it.room), pct = Math.round((used / it.limit) * 100)
          return (
            <button key={it.key} className={`torg-crate${it.max <= 0 ? ' off' : ''}`} disabled={busy} onClick={() => { haptic('light'); setPick(it) }}>
              <span className="torg-tag"><ResIcon k="gold" size={11} />{it.price}</span>
              <span className="torg-ic"><ResIcon k={it.key} size={34} /></span>
              <span className="torg-nm">{it.name}</span>
              <span className="torg-lim"><i style={{ width: `${pct}%` }} /></span>
              <span className="torg-room">{it.room <= 0 ? '🚫 лимит' : `сегодня: ${it.room}`}</span>
              {it.have > 0 && <span className="torg-have">в погребе {it.have}</span>}
            </button>
          )
        })}
      </div>

      <div className="torg-cap">🔨 Аукцион<span>скоро</span></div>
      <div className="torg-soon rise">Лоты между игроками — выставляй излишки, торгуйся за чужое. На подходе.</div>
      <div className="torg-cap">📈 Биржа<span>скоро</span></div>
      <div className="torg-soon rise">Котировки в реальном времени и сбыт оптом. На подходе.</div>

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
