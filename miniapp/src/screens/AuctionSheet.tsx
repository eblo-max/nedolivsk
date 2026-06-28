import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { GoodIcon, ResIcon, fmt } from '../components/icons'
import AnimEmoji from '../components/AnimEmoji'

interface AucNpc { name: string; emoji: string; avatar: number | null }
interface AucHist { unit: number; name: string; emoji: string; avatar: number | null }
interface AucGood { key: string; name: string; emoji: string; stock: number; fv: number }
interface AucTier { mult: number; label: string }
interface AucResult { sold: boolean; good: string; name: string; emoji: string; qty: number; unit?: number; gold?: number; winner?: AucNpc | null }
interface AucState {
  ok: boolean; open: boolean; gold?: number; active?: boolean
  good?: string; name?: string; emoji?: string; qty?: number; reserve?: number
  top_bid?: number | null; bidder?: AucNpc | null; bids?: number; ends_at?: string
  mins_left?: number; history?: AucHist[]; duration_h?: number
  goods?: AucGood[]; tiers?: AucTier[]; presets?: number[]; qty_max?: number
  result?: AucResult | null; admin?: boolean
}

const npcSrc = (a: number | null) => a ? `${import.meta.env.BASE_URL}npc/${a}.png` : ''

/** Гонг (Web Audio): низкий тон + неравномерные обертоны с долгим затуханием. */
function gong(strong = false) {
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    const ac = new AC(); const t = ac.currentTime
    const v = strong ? 1.3 : 1
    const hit = (f: number, g: number, dur: number) => {
      const o = ac.createOscillator(), ga = ac.createGain()
      o.type = 'sine'; o.frequency.value = f
      ga.gain.setValueAtTime(0, t); ga.gain.linearRampToValueAtTime(g * v, t + 0.008)
      ga.gain.exponentialRampToValueAtTime(0.0008, t + dur)
      o.connect(ga); ga.connect(ac.destination); o.start(t); o.stop(t + dur)
    }
    hit(91, 0.22, 1.9); hit(182, 0.24, 1.6); hit(274, 0.14, 1.3); hit(437, 0.07, 1.0)
    setTimeout(() => ac.close(), 2200)
  } catch { /* без звука — не критично */ }
}

function Face({ n, size = 26 }: { n: { emoji: string; avatar: number | null }; size?: number }) {
  const [bad, setBad] = useState(false)
  if (n.avatar && !bad) return <img className="auc-face" style={{ width: size, height: size }} src={npcSrc(n.avatar)} alt="" onError={() => setBad(true)} />
  return <span className="auc-face auc-face-emo" style={{ width: size, height: size, fontSize: size * 0.62 }}>{n.emoji}</span>
}

/** Живой обратный отсчёт из ISO ends_at — тикает каждую секунду. */
function Countdown({ ends }: { ends: string }) {
  const [, tick] = useState(0)
  useEffect(() => { const i = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(i) }, [])
  const left = Math.max(0, Math.floor((new Date(ends).getTime() - Date.now()) / 1000))
  const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = left % 60
  const pad = (x: number) => String(x).padStart(2, '0')
  return <span className={`auc-clock${left < 600 ? ' hot' : ''}`}>{h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`}</span>
}

export default function AuctionSheet({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<AucState | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const [step, setStep] = useState<'good' | 'set'>('good')
  const [pick, setPick] = useState<AucGood | null>(null)
  const [qty, setQty] = useState(0)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200) }
  const [bidFlash, setBidFlash] = useState(false)   // вспышка при новой ставке горожанина
  const prevBids = useRef<number | null>(null)      // сколько ставок было в прошлый опрос
  const resGong = useRef(false)                      // гонг финала отбили (раз)

  const load = (silent = false) => api<AucState>('auction').then((r) => { setD(r); void silent }).catch(() => setD({ ok: true, open: false }))
  useEffect(() => { load() }, [])
  // живой лот — тихо подтягиваем новые ставки горожан
  const active = !!d?.active
  useEffect(() => {
    if (!active) return
    const i = setInterval(() => load(true), 6000)
    return () => clearInterval(i)
  }, [active])

  // новая ставка пришла — гонг, вибро, вспышка лота и свежей строки ленты
  useEffect(() => {
    if (!active) { prevBids.current = null; return }
    const b = d?.bids ?? 0
    if (prevBids.current !== null && b > prevBids.current) {
      gong(false); haptic('medium')
      setBidFlash(true); setTimeout(() => setBidFlash(false), 1500)
    }
    prevBids.current = b
  }, [d?.bids, active])

  // финал торгов появился — тяжёлый гонг один раз (продано/не взяли)
  useEffect(() => {
    if (d?.result && !d.active) {
      if (!resGong.current) { resGong.current = true; gong(true); hapticNotify(d.result.sold ? 'success' : 'warning') }
    } else { resGong.current = false }
  }, [d?.result, d?.active])

  async function dismissResult() {
    if (busy) return
    setBusy(true); haptic('light')
    try { await api('auction/seen') } catch { /* всё равно перезагрузим */ }
    setBusy(false); resGong.current = false; await load()
  }

  async function create(tier: number) {
    if (busy || !pick || qty <= 0) return
    setBusy(true); haptic('medium')
    try {
      const r = await api<AucState>('auction/create', { good: pick.key, qty, tier })
      setD(r); hapticNotify('success'); flash('Лот выставлен — жди покупателей!')
      setStep('good'); setPick(null); setQty(0)
    } catch (e) {
      const c = (e as { code?: string })?.code
      flash(c === 'busy' ? 'Лот уже на торгах' : c === 'empty' ? 'Товара нет' : 'Не вышло')
      hapticNotify('warning')
    } finally { setBusy(false) }
  }
  async function cancel() {
    if (busy) return
    setBusy(true); haptic('medium')
    try { const r = await api<AucState>('auction/cancel'); setD(r); hapticNotify('success'); flash('Лот снят, товар вернулся в погреб') }
    catch { flash('Не вышло'); hapticNotify('warning') }
    finally { setBusy(false) }
  }
  // ── ТЕСТ (только админ): прогнать все экраны, не дожидаясь горожан/таймера ──
  async function seedBids() {
    if (busy) return
    setBusy(true); haptic('medium')
    try { const r = await api<AucState>('auction/seed'); prevBids.current = null; setD(r); flash('🧪 ставки подброшены') }
    catch { flash('Не вышло'); hapticNotify('warning') }
    finally { setBusy(false) }
  }
  async function settleNow() {
    if (busy) return
    setBusy(true); haptic('medium')
    try { const r = await api<AucState>('auction/settle_now'); setD(r); flash('🧪 торги закрыты') }
    catch { flash('Не вышло'); hapticNotify('warning') }
    finally { setBusy(false) }
  }

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="auc-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="auc-head">🔨 Аукцион Недоливска</div>
        {toast && <div className="toast">{toast}</div>}

        {d === null ? <div className="center" style={{ padding: '40px 0' }}><div className="spin" /></div>
          : !d.open ? (
            <div className="auc-lock">
              <div className="auc-lock-emo">🔨</div>
              <div className="auc-lock-h">Аукцион скоро откроется</div>
              <p className="auc-lock-txt">«Глашатай уже драит молоток, горожане сходятся к помосту. Вот-вот ударим в гонг — выставляй товар и снимай сливки.»</p>
            </div>
          ) : d.active ? (
            // ── ЖИВОЙ ЛОТ — аукционный зал ──
            <div className={`auc-hall${bidFlash ? ' bidflash' : ''}`}>
              <div className="auc-stage">
                <div className="auc-halo" />
                <span className="auc-qty-badge">×{d.qty}</span>
                <div className="auc-item"><GoodIcon k={d.good!} size={96} /></div>
                <div className="auc-podium" />
                <div className="auc-lot-name">{d.name}</div>
              </div>

              <div className={`auc-bidbox${bidFlash ? ' hot' : ''}`}>
                {d.top_bid ? (
                  <>
                    <div className="auc-bid-lbl">текущая ставка</div>
                    <div className="auc-bid-v"><ResIcon k="gold" size={22} />{fmt(d.top_bid)}<small>/шт</small></div>
                    {d.bidder && <div className="auc-bid-who"><Face n={d.bidder} size={20} />{d.bidder.name}</div>}
                    <div className="auc-bid-tot">куш: {fmt(d.top_bid * (d.qty || 1))} 🪙</div>
                  </>
                ) : (
                  <>
                    <div className="auc-bid-lbl">резерв · ставок нет</div>
                    <div className="auc-bid-v"><ResIcon k="gold" size={22} />{fmt(d.reserve || 0)}<small>/шт</small></div>
                    <div className="auc-bid-tot muted">ждём покупателей…</div>
                  </>
                )}
              </div>

              <div className="auc-meta">
                <span className="auc-timer">⏳ <Countdown ends={d.ends_at!} /></span>
                <span className="auc-heat"><AnimEmoji id="fire" fallback="🔥" size={18} /> {d.bids || 0} ставок</span>
              </div>

              {d.history && d.history.length > 0 && (
                <div className="auc-feed">
                  <div className="auc-feed-h">📣 Ход торгов</div>
                  {d.history.map((h, i) => (
                    <div key={i} className={`auc-feed-row${bidFlash && i === d.history!.length - 1 ? ' fresh' : ''}`} style={{ animationDelay: `${i * 0.05}s` }}>
                      <Face n={h} size={24} />
                      <span className="auc-feed-nm">{h.name}</span>
                      <span className="auc-feed-bid"><ResIcon k="gold" size={12} />{h.unit}</span>
                    </div>
                  ))}
                </div>
              )}

              <button className="btn auc-cancel" disabled={busy} onClick={cancel}>✋ Снять лот</button>
              <p className="auc-hint">Торги идут сами — горожане набегают. Закроются по таймеру, золото упадёт в казну.</p>

              {d.admin && (
                <div className="auc-test">
                  <span className="auc-test-h">🧪 тест-режим (только ты)</span>
                  <div className="auc-test-row">
                    <button className="auc-test-b" disabled={busy} onClick={seedBids}>🎲 ставки</button>
                    <button className="auc-test-b" disabled={busy} onClick={settleNow}>⏱ завершить</button>
                  </div>
                </div>
              )}
            </div>
          ) : d.result ? (
            // ── ФИНАЛ ТОРГОВ — продано / не взяли ──
            <div className={`auc-fin ${d.result.sold ? 'won' : 'lost'}`}>
              {d.result.sold && <div className="auc-rays" />}
              <div className="auc-fin-stamp">{d.result.sold ? 'ПРОДАНО' : 'НЕ ВЗЯЛИ'}</div>
              <div className="auc-fin-stage">
                {d.result.sold && <div className="auc-fin-halo" />}
                <span className="auc-qty-badge">×{d.result.qty}</span>
                <div className="auc-fin-item"><GoodIcon k={d.result.good} size={96} /></div>
                <div className="auc-podium" />
              </div>
              <div className="auc-fin-name">{d.result.name}</div>

              {d.result.sold ? (
                <>
                  {d.result.winner && (
                    <div className="auc-fin-who"><Face n={d.result.winner} size={30} /><span>забрал <b>{d.result.winner.name}</b></span></div>
                  )}
                  <div className="auc-fin-gold"><ResIcon k="gold" size={30} />+{fmt(d.result.gold || 0)}</div>
                  <div className="auc-fin-sub">по {fmt(d.result.unit || 0)} 🪙/шт · золото уже в казне</div>
                </>
              ) : (
                <div className="auc-fin-sub lost">Ставок не дотянуло до резерва — товар вернулся в погреб. Сбрось цену и выставь снова.</div>
              )}

              <button className="btn auc-fin-ok" disabled={busy} onClick={dismissResult}>{d.result.sold ? '🍺 Принять куш' : '← К торгам'}</button>
            </div>
          ) : (
            // ── НЕТ ЛОТА — витрина выставления ──
            <div className="auc-make">
              {step === 'good' ? (
                (d.goods && d.goods.length > 0) ? (
                  <>
                    <p className="auc-sub">Выставь товар из погреба — горожане сами набегут перебивать цену.</p>
                    <div className="auc-goods">
                      {d.goods.map((g) => (
                        <button key={g.key} className="auc-gtile" onClick={() => { haptic('light'); setPick(g); setQty(Math.min(d.presets?.[0] ?? 5, g.stock)); setStep('set') }}>
                          <GoodIcon k={g.key} size={34} />
                          <span className="auc-gnm">{g.name}</span>
                          <span className="auc-gstock">×{g.stock}</span>
                          <span className="auc-gfv"><ResIcon k="gold" size={11} />{g.fv}</span>
                        </button>
                      ))}
                    </div>
                  </>
                ) : <p className="auc-empty">«В погребе хоть шаром покати — свари товар на пристройках, тогда и торгуй.»</p>
              ) : pick && (
                <div className="auc-cfg">
                  <button className="auc-back" onClick={() => { setStep('good'); setPick(null) }}>‹ другой товар</button>
                  <div className="auc-cfg-good"><GoodIcon k={pick.key} size={40} /><div><b>{pick.name}</b><small>в погребе {pick.stock} · рынок {pick.fv} 🪙/шт</small></div></div>

                  <div className="auc-cap">Объём лота</div>
                  <div className="auc-qtys">
                    {(d.presets || []).filter((q) => q <= pick.stock).map((q) => (
                      <button key={q} className={`auc-qty${qty === q ? ' on' : ''}`} onClick={() => { haptic('light'); setQty(q) }}>{q}</button>
                    ))}
                    {pick.stock < (d.presets?.[0] ?? 5) && <button className={`auc-qty${qty === pick.stock ? ' on' : ''}`} onClick={() => setQty(pick.stock)}>{pick.stock}</button>}
                  </div>

                  <div className="auc-cap">Резервная цена · за {qty} шт</div>
                  <div className="auc-tiers">
                    {(d.tiers || []).map((t, i) => {
                      const unit = Math.max(1, Math.round(pick.fv * t.mult))
                      return (
                        <button key={i} className="auc-tier" disabled={busy || qty <= 0} onClick={() => create(i)}>
                          <span className="auc-tier-lbl">{t.label}</span>
                          <span className="auc-tier-unit">{unit} 🪙/шт</span>
                          <span className="auc-tier-tot">куш ≈ {fmt(unit * qty)} 🪙</span>
                        </button>
                      )
                    })}
                  </div>
                  <p className="auc-hint">Лот висит {d.duration_h} ч. Заломишь цену — могут и не взять; не возьмут — товар вернётся.</p>
                </div>
              )}
            </div>
          )}

        <button className="btn auc-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
