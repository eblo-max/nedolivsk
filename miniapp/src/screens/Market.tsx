import { useEffect, useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify, openTgLink } from '../telegram'
import { ResIcon, fmt } from '../components/icons'
import Sheet from '../components/Sheet'
import AuctionSheet from './AuctionSheet'
import BourseSheet from './BourseSheet'

interface ShopItem { key: string; name: string; emoji: string; price: number; room: number; limit: number; max: number; have: number }
interface TorgState { ok: boolean; open: boolean; gold?: number; limit?: number; shop?: ShopItem[] }

const MERCHANT = `${import.meta.env.BASE_URL}npc/15.png`   // аватар скупщика

// превью-демо лавки (только import.meta.env.DEV): на localhost нет Telegram-подписи,
// сервер закрывает Торг — но в DEV открываем витрину, чтобы прощёлкать Торг/Аукцион.
// В прод-сборке (DEV=false) недостижимо. См. [[miniapp-no-sample-in-prod]].
const DEMO_TORG: TorgState = { ok: true, open: true, gold: 4810, limit: 150, shop: [
  { key: 'wood', name: 'Дрова', emoji: '🪵', price: 8, room: 150, limit: 150, max: 99, have: 0 },
  { key: 'grain', name: 'Зерно', emoji: '🌾', price: 10, room: 120, limit: 150, max: 99, have: 12 },
  { key: 'hops', name: 'Хмель', emoji: '🌿', price: 12, room: 150, limit: 150, max: 99, have: 0 },
  { key: 'stone', name: 'Камень', emoji: '🪨', price: 9, room: 80, limit: 150, max: 99, have: 5 },
  { key: 'ore', name: 'Руда', emoji: '⛏', price: 14, room: 0, limit: 150, max: 0, have: 0 },
  { key: 'clay', name: 'Глина', emoji: '🧱', price: 7, room: 150, limit: 150, max: 99, have: 0 },
] }

/** Торг: лавка скупщика (купить сырьё за золото). Закрыт для всех (ставни + замок),
 * кроме админа/флага TORG_OPEN — гейт серверный. Аукцион и биржа — «скоро». */
export default function Market() {
  const [d, setD] = useState<TorgState | null>(null)
  const [pick, setPick] = useState<ShopItem | null>(null)
  const [aucOpen, setAucOpen] = useState(false)
  const [brsOpen, setBrsOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const [avOk, setAvOk] = useState(true)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2000) }

  const load = () => api<TorgState>('torg')
    .then((r) => setD(r.open || !import.meta.env.DEV ? r : DEMO_TORG))   // DEV: закрыт сервером → демо-витрина
    .catch(() => setD(import.meta.env.DEV ? DEMO_TORG : { ok: true, open: false }))
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

      {/* купеческий баннер — современная hero-плашка */}
      <div className="torg-head rise">
        <div className="torg-head-row">
          <div className="torg-portrait">
            {avOk ? <img src={MERCHANT} alt="" onError={() => setAvOk(false)} /> : <span className="torg-mav-emo">⚖️</span>}
            <span className="torg-status" />
          </div>
          <div className="torg-hero-id">
            <div className="torg-hero-name">Скупщик</div>
            <div className="torg-hero-role">бродячий купец · сырьё за золото</div>
          </div>
        </div>
        <p className="torg-quote"><span className="torg-q">“</span>Сырьё любое — плати золотом и бери сразу. Дорого, да без ожидания бригад.</p>
      </div>

      {/* лавка — ящики с товаром */}
      <div className="torg-cap">🛒 Лавка скупщика<span className="torg-coin"><ResIcon k="gold" size={13} />{fmt(d.gold ?? 0)}</span></div>
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

      <div className="torg-cap">🔨 Аукцион</div>
      <button className="torg-act rise" onClick={() => { haptic('light'); setAucOpen(true) }}>
        <span className="torg-act-emo">🏷️</span>
        <span className="torg-act-body"><b>Выставить лот</b><small>горожане сами набегут перебивать цену</small></span>
        <span className="torg-act-chev">›</span>
      </button>
      <div className="torg-cap">📈 Биржа</div>
      <button className="torg-act rise" onClick={() => { haptic('light'); setBrsOpen(true) }}>
        <span className="torg-act-emo">⚖️</span>
        <span className="torg-act-body"><b>Открыть биржу</b><small>котировки и сбыт оптом между игроками</small></span>
        <span className="torg-act-chev">›</span>
      </button>

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
      {aucOpen && <AuctionSheet onClose={() => setAucOpen(false)} />}
      {brsOpen && <BourseSheet onClose={() => setBrsOpen(false)} />}
    </div>
  )
}
