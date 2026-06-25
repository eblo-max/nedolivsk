import { useState, useEffect, useRef } from 'react'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify, initData, pushBack, popBack } from '../telegram'
import { ResIcon, GoodIcon, fmt } from '../components/icons'
import Sheet from '../components/Sheet'

// ── типы (зеркало webapp _buildings_state/_building_detail/_production_state) ──
type BStatus = 'built' | 'building' | 'locked' | 'available'
interface BItem { id: string; emoji: string; name: string; status: BStatus; minutes: number; lock: string | null; producer: boolean }
interface BuildSlot { state: string; minutes: number; id: string | null; name: string | null }
interface BState { ok: boolean; level: number; gold: number; reputation: number; finished: string | null; build: BuildSlot; list: BItem[] }

interface Cost { key: string; name: string; emoji?: string; need: number; have: number; ok: boolean }
interface Detail {
  ok: boolean; id: string; emoji: string; name: string; desc: string; unlocks: string; image: string
  built: boolean; build_hours: number; cost: Cost[]; can_build: boolean; afford: boolean
  lock: { kind: string; text: string; minutes?: number } | null
}
interface OutItem { key: string; name: string; emoji?: string; good: boolean; qty: number }
interface Recipe { key: string; tier?: number; name: string; emoji?: string; good: boolean; out_qty: number; time: string; inputs: Cost[] }
interface Batch { state: string; minutes: number; total?: number; out: OutItem | null }
interface Brewery { phase: string; minutes: number; tier: number; next_tier: number; can_age: boolean; mature_chance: number }
interface ProdState {
  ok: boolean; id: string; emoji: string; name: string; desc: string; image: string; level: number
  kind: 'grind' | 'recipe' | 'brewery'; to: 'inventory' | 'cellar'
  recipes: Recipe[]; stock: OutItem[]; batch: Batch; brewery?: Brewery; flavor?: string | null
}

const art = (id: string) => `${import.meta.env.BASE_URL}buildings/${id}.webp`
const stars = (t?: number) => '★'.repeat(t || 0)
function hm(m: number): string {
  if (m <= 0) return 'готово'
  const h = Math.floor(m / 60), mm = m % 60
  return h ? `${h} ч ${mm ? mm + ' мин' : ''}`.trim() : `${mm} мин`
}

const ST_LABEL: Record<BStatus, string> = { built: '✓ работает', building: '🏗 строится', locked: '🔒', available: 'можно строить' }

// иконка выхода/склада: товар → GoodIcon, сырьё/полуфабрикат → ResIcon
function OutIcon({ it }: { it: { key: string; good: boolean; emoji?: string } }) {
  return it.good ? <GoodIcon k={it.key} /> : <ResIcon k={it.key} emoji={it.emoji} />
}

// детерминированный прогресс партии (есть total из бэка)
function ProdBar({ minutes, total }: { minutes: number; total?: number }) {
  const pct = total && total > 0 ? Math.max(5, Math.min(100, Math.round(((total - minutes) / total) * 100))) : 60
  return <div className="prodbar"><i style={{ width: `${pct}%` }} /></div>
}

const SAMPLE: BState = {
  ok: true, level: 3, gold: 1840, reputation: 55, finished: null,
  build: { state: 'active', minutes: 74, id: 'kitchen', name: 'Кухня' },
  list: [
    { id: 'mill', emoji: '🌾', name: 'Мельница', status: 'built', minutes: 0, lock: null, producer: true },
    { id: 'brewery', emoji: '🍺', name: 'Пивоварня', status: 'built', minutes: 0, lock: null, producer: true },
    { id: 'meadery', emoji: '🍶', name: 'Медоварня', status: 'available', minutes: 0, lock: null, producer: true },
    { id: 'kitchen', emoji: '🍖', name: 'Кухня', status: 'building', minutes: 74, lock: null, producer: true },
    { id: 'winery', emoji: '🍷', name: 'Винокурня', status: 'locked', minutes: 0, lock: 'Репутация 80 · у тебя 55', producer: true },
    { id: 'smelter', emoji: '🔩', name: 'Горн', status: 'built', minutes: 0, lock: null, producer: true },
    { id: 'bakery', emoji: '🥖', name: 'Пекарня', status: 'available', minutes: 0, lock: null, producer: true },
    { id: 'smokehouse', emoji: '💨', name: 'Коптильня', status: 'available', minutes: 0, lock: null, producer: true },
    { id: 'dairy', emoji: '🧀', name: 'Сыроварня', status: 'locked', minutes: 0, lock: 'Репутация 50 · у тебя 55', producer: true },
  ],
}

export default function Buildings() {
  const { data, loading, error, set, reload } = useApi<BState>('buildings', SAMPLE)
  const [view, setView] = useState<'list' | 'prod'>('list')
  const [prod, setProd] = useState<ProdState | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200) }

  // нативная «назад» из производства → к списку
  useEffect(() => {
    if (view !== 'prod') return
    const cb = () => setView('list')
    pushBack(cb)
    return () => popBack(cb)
  }, [view])

  // реалтайм таймеров: тихо обновляем, пока ничего не открыто/не идёт действие
  const guard = useRef({ busy, detail: !!detail, view, pid: prod?.id })
  guard.current = { busy, detail: !!detail, view, pid: prod?.id }
  useEffect(() => {
    const refresh = async () => {
      const g = guard.current
      if (document.visibilityState !== 'visible' || g.busy || g.detail) return
      if (g.view === 'prod' && g.pid) {
        try { setProd(await api<ProdState>('building', { id: g.pid })) } catch { /* */ }
      } else if (g.view === 'list') reload()
    }
    const iv = setInterval(refresh, 20000)
    document.addEventListener('visibilitychange', refresh)
    return () => { clearInterval(iv); document.removeEventListener('visibilitychange', refresh) }
  }, [reload])

  // достройка завершилась (ленивое finalize на сервере) — празднуем как бот
  const shownFin = useRef<string | null>(null)
  useEffect(() => {
    const f = data?.finished
    if (f && shownFin.current !== f) { shownFin.current = f; hapticNotify('success'); flash(`🏗 ${f} достроена!`) }
    if (!f) shownFin.current = null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.finished])

  async function openBuilding(b: BItem) {
    if (b.status === 'building') { flash(`Строится — ещё ${hm(b.minutes)}`); return }
    haptic('light')
    try {
      const r = await api<Detail | ProdState>('building', { id: b.id })
      if ((r as ProdState).kind) { setProd(r as ProdState); setView('prod') }
      else setDetail(r as Detail)
    } catch { flash('Не открылось') }
  }

  async function build(id: string) {
    if (busy) return
    setBusy(true); haptic('medium')
    try {
      const r = await api<{ name: string; hours: number; buildings: BState }>('build_start', { id })
      set(r.buildings); hapticNotify('success')
      flash(`Заложили: ${r.name} · ${r.hours} ч`); setDetail(null)
    } catch (e) {
      hapticNotify('warning')
      const code = (e as { code?: string })?.code
      flash(code === 'not_enough' ? 'Не хватает на стройку'
        : code === 'busy' ? 'Артель занята другой стройкой'
        : code === 'requires' ? 'Сначала построй, что требуется'
        : code === 'reputation' ? 'Репутация низковата'
        : code === 'built' ? 'Уже построено' : 'Не вышло')
    } finally { setBusy(false) }
  }

  async function startRecipe(r: Recipe) {
    if (busy || !prod) return
    setBusy(true); haptic('medium')
    try {
      const body: Record<string, unknown> = { building: prod.id }
      if (prod.kind === 'brewery') body.tier = r.tier
      else body.recipe = r.key
      const res = await api<{ production: ProdState }>('prod_start', body)
      setProd(res.production); hapticNotify('success')
      flash({ mill: 'Закрутилось!', smelter: 'Закрутилось!', brewery: 'Заброжало!', meadery: 'Забулькало!',
        kitchen: 'На огонь!', winery: 'Поставили бродить!' }[prod.id] || 'Готовится!')
    } catch (e) {
      hapticNotify('warning')
      const code = (e as { code?: string })?.code
      flash(code === 'not_enough' ? 'Не хватает сырья' : code === 'busy' ? 'Уже работает — дождись' : 'Не вышло')
    } finally { setBusy(false) }
  }

  async function claim() {
    if (busy || !prod) return
    setBusy(true); haptic('medium')
    try {
      const res = await api<{ production: ProdState; toast: string }>('prod_claim', { building: prod.id })
      setProd(res.production); hapticNotify('success'); if (res.toast) flash(res.toast)
    } catch (e) {
      hapticNotify('warning')
      flash((e as { code?: string })?.code === 'not_ready' ? 'Ещё не готово' : 'Не вышло')
    } finally { setBusy(false) }
  }

  async function age() {
    if (busy || !prod) return
    setBusy(true); haptic('heavy')
    try {
      const res = await api<{ production: ProdState }>('brew_age', {})
      setProd(res.production); hapticNotify('success'); flash('Поставили на выдержку — не зевай!')
    } catch { hapticNotify('warning'); flash('Выдержка сейчас невозможна') }
    finally { setBusy(false) }
  }

  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  if (error && error !== 'no_tavern' && initData()) return (
    <div className="center" style={{ flex: 1, flexDirection: 'column', gap: 14, padding: 26, textAlign: 'center' }}>
      <div className="muted" style={{ fontStyle: 'italic' }}>Не удалось загрузить пристройки.</div>
      <button className="btn gold" style={{ maxWidth: 220 }} onClick={() => reload()}>Повторить</button>
    </div>
  )
  const d = data ?? SAMPLE

  // ── Экран производства ────────────────────────────────────────────────
  if (view === 'prod' && prod) return (
    <div className="scr">
      {toast && <div className="toast">{toast}</div>}
      <ProductionView prod={prod} busy={busy} onStart={startRecipe} onClaim={claim} onAge={age} onBack={() => setView('list')} />
    </div>
  )

  // ── Список пристроек ──────────────────────────────────────────────────
  return (
    <div className="scr">
      {toast && <div className="toast">{toast}</div>}
      <div className="bld-head">
        <h2>🏗 Пристройки</h2>
        <p className="muted">Каждая открывает своё производство. Деньги и сырьё — вперёд.</p>
      </div>

      {d.build.state !== 'none' && d.build.id && (
        <div className="bld-banner">
          <span className="bb-ic">🏗</span>
          <div className="bb-txt">
            <b>{d.build.name}</b>
            <span className="muted">{d.build.state === 'ready' ? 'достроена — открой, чтобы пустить в дело' : `строится — ещё ${hm(d.build.minutes)}`}</span>
          </div>
        </div>
      )}

      <div className="bld-grid">
        {d.list.map((b) => (
          <button key={b.id} className={`bld-tile st-${b.status}`} onClick={() => openBuilding(b)}>
            <img className="bt-art" src={art(b.id)} alt="" loading="lazy"
              onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
            <span className="bt-name">{b.emoji} {b.name}</span>
            <span className="bt-st">{b.status === 'building' ? `🏗 ${hm(b.minutes)}` : ST_LABEL[b.status]}</span>
            {b.status === 'locked' && b.lock && <span className="bt-lock">{b.lock}</span>}
          </button>
        ))}
      </div>

      {detail && (
        <Sheet icon={undefined} title={`${detail.emoji} ${detail.name}`} onClose={() => setDetail(null)}>
          <BuildDetail detail={detail} busy={busy} onBuild={() => build(detail.id)} />
        </Sheet>
      )}
    </div>
  )
}

// ── Деталь непостроенного здания (bottom-sheet) ──────────────────────────
function BuildDetail({ detail, busy, onBuild }: { detail: Detail; busy: boolean; onBuild: () => void }) {
  return (
    <>
      <img className="bd-art" src={art(detail.image)} alt="" loading="lazy"
        onError={(e) => { e.currentTarget.style.display = 'none' }} />
      <p className="bd-desc">{detail.desc}</p>
      {detail.unlocks && <div className="sheet-row"><span>🔓 Откроет</span><b style={{ textAlign: 'right' }}>{detail.unlocks}</b></div>}

      {detail.built ? (
        <p className="muted" style={{ fontStyle: 'italic', marginTop: 12 }}>✓ Уже построено. Работает.</p>
      ) : detail.lock ? (
        <p className="bd-lock">🔒 {detail.lock.text}{detail.lock.minutes ? ` — ещё ${hm(detail.lock.minutes)}` : ''}.</p>
      ) : (
        <>
          <div className="sheet-row"><span>⏱ Стройка</span><b>{detail.build_hours} ч</b></div>
          <div className="sheet-sub" style={{ marginTop: 12 }}>СТОИМОСТЬ</div>
          <div className="sheet-list">
            {detail.cost.map((c, i) => (
              <div key={i} className="sheet-task">
                <ResIcon k={c.key} emoji={c.emoji} /><span className="l">{c.name}</span>
                <span className="r" style={{ color: c.ok ? 'var(--green)' : 'var(--crimson)' }}>{fmt(c.have)} / {fmt(c.need)}</span>
              </div>
            ))}
          </div>
          <button className="btn gold" style={{ marginTop: 14 }} disabled={busy || !detail.afford} onClick={onBuild}>
            {detail.afford ? `🏗 Заложить · ${detail.build_hours} ч` : 'Не хватает на стройку'}
          </button>
        </>
      )}
    </>
  )
}

// ── Экран производства ───────────────────────────────────────────────────
function ProductionView({ prod, busy, onStart, onClaim, onAge, onBack }: {
  prod: ProdState; busy: boolean
  onStart: (r: Recipe) => void; onClaim: () => void; onAge: () => void; onBack: () => void
}) {
  const bw = prod.brewery
  const phase = bw?.phase
  const idle = prod.kind === 'brewery' ? phase === 'empty' : prod.batch.state === 'none'
  const ready = prod.kind === 'brewery' ? ['ready', 'ripe', 'overripe'].includes(phase || '') : prod.batch.state === 'ready'
  const active = !idle && !ready
  const warn = phase === 'ripe' || phase === 'overripe'        // выдержка перекисает — срочно
  const stockLabel = prod.to === 'inventory' ? 'На складе' : 'В погребе'

  // статусная строка
  let status = ''
  if (prod.kind === 'brewery') {
    const t = bw!.tier
    status = phase === 'fermenting' ? `⏳ Бродит ${stars(t)} — ещё ${hm(bw!.minutes)}`
      : phase === 'ready' ? `🍺 ${stars(t)} готов — разливай${bw!.can_age ? ' или рискни выдержать' : ''}!`
      : phase === 'aging' ? `🛢 Выдержка ${stars(t)} → ${stars(bw!.next_tier)} — ещё ${hm(bw!.minutes)}`
      : phase === 'ripe' ? `⏰ Выдержка дошла! Разлей за ${hm(bw!.minutes)} — иначе перекиснет`
      : phase === 'overripe' ? '⚠️ Перекисает! Разливай немедля — ярус упадёт'
      : '😴 Чаны пусты — выбери, что варить'
  } else {
    status = active ? `⏳ Готовится${prod.batch.out ? ' ' + prod.batch.out.name : ''} — ещё ${hm(prod.batch.minutes)}`
      : ready ? '📦 Готово — забирай!'
      : '😴 Простаивает — выбери, что делать'
  }

  return (
    <>
      <button className="lnk-back" onClick={onBack}>← Пристройки</button>
      <div className="prod-hero">
        <img src={art(prod.image)} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = 'none' }} />
        <div className="ph-cap"><b>{prod.emoji} {prod.name}</b><span className="muted">{prod.desc}</span></div>
      </div>

      <div className="prod-stock">{stockLabel}: {prod.stock.map((s) => (
        <span key={s.key} className="ps-chip"><OutIcon it={s} />{fmt(s.qty)}</span>
      ))}</div>

      <div className={`prod-status ${warn ? 'wn' : ready ? 'rd' : active ? 'ac' : ''}`}>{status}</div>

      {active && (
        <div className="prod-batch">
          <ProdBar minutes={prod.kind === 'brewery' ? bw!.minutes : prod.batch.minutes} total={prod.batch.total} />
          {prod.batch.out && <div className="pb-out"><OutIcon it={prod.batch.out} />×{prod.batch.out.qty}</div>}
        </div>
      )}

      {ready && (
        <div className="prod-claim">
          {prod.kind === 'brewery' ? (
            <>
              <button className="btn green" disabled={busy} onClick={onClaim}>🍺 Разлить в погреб{prod.batch.out ? ` · ${prod.batch.out.qty}` : ''}</button>
              {bw!.can_age && (
                <button className="btn danger" disabled={busy} onClick={onAge}>🛢 Выдержать — риск +ярус ({bw!.mature_chance}%)</button>
              )}
            </>
          ) : (
            <button className="btn green" disabled={busy} onClick={onClaim}>
              {prod.to === 'inventory' ? '📦 Забрать на склад' : '🍽 Забрать в погреб'}{prod.batch.out ? ` · ${prod.batch.out.qty}` : ''}
            </button>
          )}
        </div>
      )}

      {idle && (
        <div className="recipe-list">
          {prod.recipes.map((r) => (
            <RecipeCard key={r.key} r={r} busy={busy} onStart={() => onStart(r)} />
          ))}
        </div>
      )}

      {prod.flavor && <p className="prod-flavor">{prod.flavor}</p>}
    </>
  )
}

function RecipeCard({ r, busy, onStart }: { r: Recipe; busy: boolean; onStart: () => void }) {
  const afford = r.inputs.every((i) => i.ok)
  return (
    <div className="recipe-card">
      <div className="rc-head">
        <OutIcon it={r} />
        <span className="rc-name">{r.name}</span>
        <span className="rc-meta">×{r.out_qty} · {r.time}</span>
      </div>
      <div className="rc-inputs">
        {r.inputs.map((i, k) => (
          <span key={k} className="rc-in" style={{ color: i.ok ? 'var(--dim)' : 'var(--crimson)' }}>
            <ResIcon k={i.key} emoji={i.emoji} size={16} />{fmt(i.have)}/{fmt(i.need)}
          </span>
        ))}
      </div>
      <button className="btn gold sm" disabled={busy || !afford} onClick={onStart}>
        {afford ? 'Запустить' : 'Не хватает сырья'}
      </button>
    </div>
  )
}
