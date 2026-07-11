import { useState, useEffect, useRef, useCallback } from 'react'
import { useApi } from '../hooks'
import { api, errText } from '../api'
import { haptic, hapticNotify, pushBack, popBack } from '../telegram'
import { ResIcon, GoodIcon, fmt } from '../components/icons'
import Sheet from '../components/Sheet'
import CoachTour, { useFirstVisitTour } from './CoachTour'
import SecretKitchen, { type ExperimentDTO } from './SecretKitchen'

// ── типы (зеркало webapp _buildings_state/_building_detail/_production_state) ──
type BStatus = 'built' | 'building' | 'locked' | 'available'
interface BItem { id: string; emoji: string; name: string; status: BStatus; minutes: number; lock: string | null; producer: boolean; prod: { state: string; minutes: number } | null }
interface BuildSlot { state: string; minutes: number; id: string | null; name: string | null }
interface BState { ok: boolean; level: number; gold: number; reputation: number; finished: string | null; build: BuildSlot; list: BItem[] }

interface Cost { key: string; name: string; emoji?: string; need: number; have: number; ok: boolean }
interface Produce { key: string; good: boolean; name: string; emoji?: string; price: number | null; use: string | null }
interface Detail {
  ok: boolean; id: string; emoji: string; name: string; desc: string; unlocks: string; image: string
  built: boolean; build_hours: number; cost: Cost[]; can_build: boolean; afford: boolean; level: number
  produces: Produce[]; requires: { id: string; emoji: string; name: string }[]; req_reputation: number
  lock: { kind: string; text: string; minutes?: number } | null
}
interface OutItem { key: string; name: string; emoji?: string; good: boolean; qty: number }
interface Recipe { key: string; tier?: number; name: string; emoji?: string; good: boolean; out_qty: number; time: string; inputs: Cost[] }
interface Batch { state: string; minutes: number; total?: number; ends_at?: number | null; out: OutItem | null }
interface Brewery { phase: string; minutes: number; tier: number; next_tier: number; can_age: boolean; mature_chance: number }
interface ProdState {
  ok: boolean; id: string; emoji: string; name: string; desc: string; image: string; level: number
  kind: 'grind' | 'recipe' | 'brewery'; to: 'inventory' | 'cellar'
  recipes: Recipe[]; stock: OutItem[]; batch: Batch; brewery?: Brewery; flavor?: string | null
  experiment?: ExperimentDTO           // Кухня: «Тайная кухня» (ИИ-блюда)
}

const art = (id: string) => `${import.meta.env.BASE_URL}buildings/${id}.webp`
const stars = (t?: number) => '★'.repeat(t || 0)
function hm(m: number): string {
  if (m <= 0) return 'готово'
  const h = Math.floor(m / 60), mm = m % 60
  return h ? `${h} ч ${mm ? mm + ' мин' : ''}`.trim() : `${mm} мин`
}
// живой отсчёт: секунды показываем только под часом (не «паникуем» на долгих)
function live(secs: number): string {
  if (secs <= 0) return 'вот-вот'
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60
  if (h > 0) return `${h} ч ${m} мин`
  if (m > 0) return `${m} мин ${String(s).padStart(2, '0')} с`
  return `${s} с`
}

// тикающий остаток до ends_at (эпоха, сек). null — нет активного отсчёта.
function useLiveSecs(endsAt?: number | null): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!endsAt) return
    const tick = () => setNow(Date.now())
    const iv = setInterval(tick, 1000)
    const onVis = () => { if (document.visibilityState === 'visible') tick() }
    document.addEventListener('visibilitychange', onVis)
    return () => { clearInterval(iv); document.removeEventListener('visibilitychange', onVis) }
  }, [endsAt])
  if (!endsAt) return null
  return Math.max(0, Math.ceil((endsAt * 1000 - now) / 1000))
}

// статус-строка 1:1 с production_screen бота (по зданию/фазе), время — живое
function statusOf(prod: ProdState, rem: string): string {
  const bw = prod.brewery, id = prod.id
  if (prod.kind === 'brewery' && bw) {
    const t = stars(bw.tier)
    switch (bw.phase) {
      case 'fermenting': return `⏳ Бродит ${t} — ещё ${rem}`
      case 'ready': return `🍺 ${t} готов — разливай${bw.can_age ? ' или выдержи (риск +ярус)' : ''}!`
      case 'aging': return `🛢 Выдержка ${t} → ${stars(bw.next_tier)} — ещё ${rem}`
      case 'ripe': return `⏰ Выдержка дошла! Разлей за ${rem} — иначе перекиснет`
      case 'overripe': return '⚠️ Перекисает! Разливай немедля — ярус упадёт'
      default: return '😴 Чаны пусты — выбери, что варить'
    }
  }
  if (prod.batch.state === 'active') {
    if (id === 'kitchen') return `⏳ На вертеле — ещё ${rem}`
    if (id === 'winery') return `⏳ Бродит — ещё ${rem}`
    if (prod.kind === 'grind') return `⏳ Работает — ещё ${rem}`
    return `⏳ Готовится${prod.batch.out ? ' ' + prod.batch.out.name : ''} — ещё ${rem}`
  }
  if (prod.batch.state === 'ready') {
    if (prod.kind === 'grind') return '📦 Готово — забирай на склад!'
    if (id === 'kitchen') return '🍖 Жаркое готово — в кладовую!'
    if (id === 'winery') return '🍷 Вино готово — разливай в погреб!'
    if (id === 'meadery') return '🍶 Готово — разливай в погреб!'
    return '🍽 Готово — забирай в погреб!'
  }
  if (prod.kind === 'grind') return '😴 Простаивает — выбери, что молоть.'
  if (id === 'kitchen') return '😴 Очаг остыл — поставь готовить.'
  if (id === 'winery') return '😴 Бочки пусты — поставь вино.'
  if (id === 'meadery') return '😴 Котлы остыли — выбери, что варить.'
  return '😴 Простаивает — выбери, что готовить.'
}

// органичная россыпь домиков по двору (центр-X% / y px) — раскиданы свободно,
// но с гарантированным зазором; глубина (z) = по y, дорожки вьются между ними
const YARD: Record<string, { cx: number; y: number }> = {
  mill: { cx: 24, y: 8 }, brewery: { cx: 63, y: 30 },
  meadery: { cx: 42, y: 120 }, winery: { cx: 78, y: 150 },
  kitchen: { cx: 15, y: 200 }, smelter: { cx: 50, y: 250 },
  smokehouse: { cx: 74, y: 330 }, bakery: { cx: 22, y: 350 },
  dairy: { cx: 48, y: 440 },
}
const STAGE_W = 360                                   // эталонная ширина сцены (масштабируется под экран)
const YARD_H = 440 + 122                               // низ домика(74)+имя+статус(~46) с запасом
// дорожки-тропинки сквозь центры домиков (y+36 — центр арта)
const YARD_PATHS = ['M24 44 L63 66 L42 156 L78 186 L50 286 L74 366 L48 476',
                    'M42 156 L15 236 L22 386 L48 476']
// озеленение двора: немного природы по пустым местам (за домиками, тапы не ловит)
const YARD_DECO: { src: string; cx: number; y: number; w: number }[] = [
  { src: 'wheat1', cx: 41, y: 30, w: 28 }, { src: 'scarecrow', cx: 9, y: 70, w: 36 },
  { src: 'flow2', cx: 63, y: 128, w: 26 }, { src: 'mush', cx: 33, y: 214, w: 22 },
  { src: 'flow1', cx: 30, y: 470, w: 26 },
]
const deco = (s: string) => `${import.meta.env.BASE_URL}yard/${s}.webp`

const hmc = (m: number) => { const h = Math.floor(m / 60), mm = m % 60; return h ? `${h}ч${mm}м` : `${mm}м` }

// статус строкой под именем домика (чисто, ничего не налезает на арт). Приоритет: готово
function yardFlag(b: BItem): { cls: string; text: string } {
  if (b.status === 'building') return { cls: 'work', text: `стройка · ${hmc(b.minutes)}` }
  if (b.status === 'locked') return { cls: 'lock', text: 'заперто' }
  if (b.status === 'available') return { cls: 'avail', text: 'построить' }
  const ps = b.prod?.state
  if (ps === 'ready') return { cls: 'rdy', text: 'готово к сбору' }
  if (ps === 'active') return { cls: 'work', text: `ещё ${hmc(b.prod!.minutes)}` }
  return { cls: 'idle', text: 'свободна' }
}

// иконка выхода/склада: товар → GoodIcon, сырьё/полуфабрикат → ResIcon
function OutIcon({ it }: { it: { key: string; good: boolean; emoji?: string } }) {
  return it.good ? <GoodIcon k={it.key} /> : <ResIcon k={it.key} emoji={it.emoji} />
}

// детерминированный прогресс партии (живые секунды vs total-минуты из бэка)
function ProdBar({ secs, totalMin }: { secs: number; totalMin?: number }) {
  const tot = (totalMin || 0) * 60
  const pct = tot > 0 ? Math.max(5, Math.min(100, Math.round(((tot - secs) / tot) * 100))) : 60
  return <div className="prodbar"><i style={{ width: `${pct}%` }} /></div>
}

const SAMPLE: BState = {
  ok: true, level: 3, gold: 1840, reputation: 55, finished: null,
  build: { state: 'active', minutes: 74, id: 'kitchen', name: 'Кухня' },
  list: [
    { id: 'mill', emoji: '🌾', name: 'Мельница', status: 'built', minutes: 0, lock: null, producer: true, prod: { state: 'active', minutes: 22 } },
    { id: 'brewery', emoji: '🍺', name: 'Пивоварня', status: 'built', minutes: 0, lock: null, producer: true, prod: { state: 'ready', minutes: 0 } },
    { id: 'meadery', emoji: '🍶', name: 'Медоварня', status: 'available', minutes: 0, lock: null, producer: true, prod: null },
    { id: 'kitchen', emoji: '🍖', name: 'Кухня', status: 'building', minutes: 74, lock: null, producer: true, prod: null },
    { id: 'winery', emoji: '🍷', name: 'Винокурня', status: 'locked', minutes: 0, lock: 'Репутация 80 · у тебя 55', producer: true, prod: null },
    { id: 'smelter', emoji: '🔩', name: 'Горн', status: 'built', minutes: 0, lock: null, producer: true, prod: { state: 'none', minutes: 0 } },
    { id: 'bakery', emoji: '🥖', name: 'Пекарня', status: 'available', minutes: 0, lock: null, producer: true, prod: null },
    { id: 'smokehouse', emoji: '💨', name: 'Коптильня', status: 'available', minutes: 0, lock: null, producer: true, prod: null },
    { id: 'dairy', emoji: '🧀', name: 'Сыроварня', status: 'locked', minutes: 0, lock: 'Репутация 50 · у тебя 55', producer: true, prod: null },
  ],
}

// DEV-сэмпл детали Кухни с «Тайной кухней» — ТОЛЬКО для превью без бэкенда
// (используется под гейтом import.meta.env.DEV, в прод не попадает).
const SAMPLE_KITCHEN: ProdState = {
  ok: true, id: 'kitchen', emoji: '🍖', name: 'Кухня', desc: '', image: 'kitchen', level: 3,
  kind: 'recipe', to: 'cellar', flavor: 'Сытые гости платят за еду сверх выпивки.',
  recipes: [{ key: 'kebab', name: 'Шашлык', emoji: '🍢', good: true, out_qty: 36, time: '9 ч',
    inputs: [{ key: 'game', name: 'Дичь', emoji: '🥩', need: 12, have: 15, ok: true }, { key: 'herbs', name: 'Травы', emoji: '🌶️', need: 6, have: 9, ok: true }] }],
  stock: [{ key: 'kebab', name: 'Шашлык', emoji: '🍢', good: true, qty: 12 }],
  batch: { state: 'none', minutes: 0, out: null },
  experiment: {
    palette: [
      { key: 'grain', name: 'Зерно', emoji: '🌾', have: 40, value: 2.5, tags: ['hearty'] },
      { key: 'hops', name: 'Хмель', emoji: '🌿', have: 18, value: 4, tags: ['fermented'] },
      { key: 'water', name: 'Вода', emoji: '💧', have: 99, value: 1, tags: ['plain'] },
      { key: 'honey', name: 'Мёд', emoji: '🍯', have: 12, value: 6, tags: ['sweet'] },
      { key: 'berries', name: 'Ягоды', emoji: '🍒', have: 22, value: 3, tags: ['sweet'] },
      { key: 'game', name: 'Дичь', emoji: '🥩', have: 15, value: 6.5, tags: ['fatty'] },
      { key: 'herbs', name: 'Травы', emoji: '🌶️', have: 9, value: 4.5, tags: ['spicy'] },
      { key: 'salt', name: 'Соль', emoji: '🧂', have: 14, value: 5, tags: ['savory'] },
      { key: 'fish', name: 'Рыба', emoji: '🐟', have: 3, value: 4, tags: ['savory'] },
      { key: 'milk', name: 'Молоко', emoji: '🥛', have: 10, value: 3, tags: ['fatty'] },
      { key: 'malt', name: 'Солод', emoji: '🧺', have: 6, value: 3.1, tags: ['hearty'] },
      { key: 'flour', name: 'Мука', emoji: '🧺', have: 5, value: 3.1, tags: ['hearty'] },
    ],
    cost_each: 5, output: 3, min: 2, max: 4, cooldown: 60, cooldown_left: 0, ai: false,
    budget_base: 3, budget_k: 0.7, budget_floor: 4, budget_cap: 20, roll_pct: 0.18,
    tiers: [[9, 'Обычный'], [14, 'Необычный'], [20, 'Редкий'], [9999, 'Экзотический']],
    cookbook: [
      { key: 'tr_d1', name: 'Огневая солянка «У плахи»', lore: 'Наперчено так, что палач слезу пустил.', label: '+9 урона', qty: 2 },
      { key: 'tr_d2', name: 'Похмельный взвар деда Пафнутия', lore: 'С одной кружки в глазах двоится, а рука тверда.', label: '+7% крита, +6 ❤', qty: 0 },
    ],
  },
}

const BUILD_TOUR = [
  { sel: '[data-tut="yard"]', emoji: '🏗', title: 'Твой двор',
    body: 'Здесь стоят производства. Каждое здание делает свой товар: пивоварня — эль, кухня — жаркое, винокурня — вино. Товар потом продаёшь в Торге.', place: 'top' as const },
  { sel: '[data-tut="yard"]', emoji: '🔨', title: 'Как построить',
    body: 'Тапни по зданию — увидишь, что оно даёт, во сколько золота и сырья обойдётся и сколько строится. Плотники берут плату вперёд. Одна стройка за раз.', place: 'top' as const },
  { emoji: '🍺', title: 'И запусти партию',
    body: 'Построил — запускай партию товара. Через время забери готовое (значок «к сбору») и неси на продажу. Так и капает доход помимо кассы таверны.' },
]

export default function Buildings() {
  const buildTour = useFirstVisitTour('buildings')
  const { data, loading, error, set, reload } = useApi<BState>('buildings', SAMPLE)
  const [view, setView] = useState<'list' | 'prod'>('list')
  const [prod, setProd] = useState<ProdState | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [ageOpen, setAgeOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200) }

  // двор — единый масштаб: сцена 360px ужимается/растягивается под ширину экрана,
  // чтобы раскладка была одинаковой на всех устройствах (320…480+). callback-ref:
  // сработает ровно когда двор появится (а не на стадии loading), cleanup — React 19.
  const fitYard = useCallback((el: HTMLDivElement | null) => {
    if (!el) return
    const fit = () => {
      const s = el.clientWidth / STAGE_W
      el.style.setProperty('--ys', String(s))
      el.style.height = `${Math.round(YARD_H * s)}px`
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // нативная «назад» из производства → к списку
  useEffect(() => {
    if (view !== 'prod') return
    const cb = () => setView('list')
    pushBack(cb)
    return () => popBack(cb)
  }, [view])

  // реалтайм таймеров: тихо обновляем, пока ничего не открыто/не идёт действие
  const guard = useRef({ busy, modal: !!detail || ageOpen, view, pid: prod?.id })
  guard.current = { busy, modal: !!detail || ageOpen, view, pid: prod?.id }
  useEffect(() => {
    const refresh = async () => {
      const g = guard.current
      if (document.visibilityState !== 'visible' || g.busy || g.modal) return
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
    haptic('light')
    try {
      const r = await api<Detail | ProdState>('building', { id: b.id })
      if ((r as ProdState).kind) { setProd(r as ProdState); setView('prod') }
      else setDetail(r as Detail)
    } catch {
      if (import.meta.env.DEV && b.id === 'kitchen') { setProd(SAMPLE_KITCHEN); setView('prod'); return }
      flash('Не открылось')
    }
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
        : code === 'built' ? 'Уже построено' : errText(e))
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
      flash(errText(e))
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
      flash(errText(e))
    } finally { setBusy(false) }
  }

  async function age() {
    if (busy || !prod) return
    setBusy(true); haptic('heavy')
    try {
      const res = await api<{ production: ProdState }>('brew_age', {})
      setProd(res.production); hapticNotify('success'); flash('Поставили на выдержку — не зевай!')
    } catch { hapticNotify('warning'); flash('Выдержка сейчас невозможна') }
    finally { setBusy(false); setAgeOpen(false) }
  }

  // живой таймер дотикал — подтянуть свежий стейт производства
  async function refetchProd() {
    if (!prod) return
    try { setProd(await api<ProdState>('building', { id: prod.id })) } catch { /* */ }
  }

  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  if (error && error !== 'no_tavern' && !import.meta.env.DEV) return (
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
      <ProductionView prod={prod} busy={busy} onStart={startRecipe} onClaim={claim}
        onAge={() => { haptic('medium'); setAgeOpen(true) }} onExpire={refetchProd} onBack={() => setView('list')}
        onExperiment={(dto) => setProd((p) => (p ? { ...p, experiment: dto } : p))} onFlash={flash} />
      {ageOpen && prod.brewery && (
        <Sheet title="🛢 Выдержка эля" onClose={() => setAgeOpen(false)}>
          <p className="bd-desc">Поставить {stars(prod.brewery.tier)} на выдержку — азартная затея.</p>
          <div className="sheet-row"><span>Шанс поднять ярус</span><b style={{ color: 'var(--green)' }}>{prod.brewery.mature_chance}% → {stars(prod.brewery.next_tier)}</b></div>
          <div className="sheet-row"><span>Иначе</span><b style={{ color: 'var(--crimson)' }}>осядет на ярус ниже, может скиснуть</b></div>
          <p className="muted" style={{ fontStyle: 'italic', margin: '10px 0 2px', textAlign: 'center' }}>Передержишь после созревания — бочка перекиснет вусмерть.</p>
          <button className="btn danger" style={{ marginTop: 12 }} disabled={busy} onClick={age}>🛢 Рискнуть — на выдержку</button>
          <button className="btn" style={{ marginTop: 9 }} disabled={busy} onClick={() => setAgeOpen(false)}>Передумал, разолью</button>
        </Sheet>
      )}
    </div>
  )

  // ── Двор таверны (органичная россыпь домиков + дорожки) ───────────────
  const built = d.list.filter((b) => b.status === 'built').length
  const ready = d.list.filter((b) => b.prod?.state === 'ready').length
  const onBuild = d.build.state !== 'none' && d.build.name
  return (
    <div className="scr">
      {buildTour.show && d.list.length > 0 && (
        <CoachTour steps={BUILD_TOUR} onDone={buildTour.finish} endLabel="Понятно" />
      )}
      {toast && <div className="toast">{toast}</div>}
      <div className="hero rise" style={{ paddingBottom: 0 }}>
        <div className="nm">Двор таверны</div>
        <div className="meta">
          <span className="region">Уровень {d.level}</span>
          <span className="region">построено {built}/{d.list.length}</span>
          {ready > 0 && <span className="region">🔔 {ready} к сбору</span>}
          {onBuild && <span className="region">⏳ {d.build.name}: {hm(d.build.minutes)}</span>}
        </div>
        <div className="flavor" style={{ margin: '6px 14px 0', fontSize: 13.5 }}>«Каждая открывает своё производство. Деньги и сырьё — вперёд.»</div>
      </div>

      <div className="yard" data-tut="yard" ref={fitYard}>
        <div className="yard-stage" style={{ width: STAGE_W, height: YARD_H }}>
          <svg className="yard-paths" viewBox={`0 0 100 ${YARD_H}`} preserveAspectRatio="none" aria-hidden="true">
            {YARD_PATHS.map((dp, i) => <path key={i} d={dp} />)}
          </svg>
          {YARD_DECO.map((o, i) => (
            <img key={i} className="yd" src={deco(o.src)} alt="" aria-hidden="true" loading="lazy"
              style={{ left: `${o.cx}%`, top: o.y, width: o.w, zIndex: Math.round(o.y) - 1 }} />
          ))}
          {d.list.map((b) => {
            const p = YARD[b.id]; const f = yardFlag(b)
            return (
              <button key={b.id} className={`yb ${b.status === 'locked' ? 'off' : ''}`}
                style={{ left: `${p.cx}%`, top: p.y, zIndex: Math.round(p.y) }} onClick={() => openBuilding(b)}>
                <img src={art(b.id)} alt="" loading="lazy"
                  onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
                <span className="yb-name">{b.name}</span>
                <span className={`yb-st ${f.cls}`}>{f.text}</span>
              </button>
            )
          })}
        </div>
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

      {detail.produces.length > 0 && (
        <>
          <div className="cap">производит · ×{detail.level} с уровнем</div>
          <div className="chips">
            {detail.produces.map((p) => (
              <span key={p.key} className="chip-p">
                <OutIcon it={p} />{p.name}
                <em>{p.good ? <>{p.price}<ResIcon k="gold" size={12} /></> : p.use}</em>
              </span>
            ))}
          </div>
        </>
      )}

      <div className="kv-list">
        <div className="kv"><span>Стройка</span><b>{detail.build_hours} ч</b></div>
        {detail.requires.length > 0 && (
          <div className="kv"><span>На базе</span><b>{detail.requires.map((r) => r.name).join(', ')}</b></div>
        )}
        {detail.req_reputation > 0 && (
          <div className="kv"><span>Репутация</span><b>{detail.req_reputation}</b></div>
        )}
      </div>

      {detail.built ? (
        <p className="bd-note">Уже построено. Работает.</p>
      ) : detail.lock ? (
        <p className="bd-lock">{detail.lock.kind === 'self' || detail.lock.kind === 'busy' ? '🏗' : '🔒'} {detail.lock.text}{detail.lock.minutes ? ` — ещё ${hm(detail.lock.minutes)}` : ''}.</p>
      ) : (
        <>
          <div className="cap">стоимость</div>
          <div className="kv-list">
            {detail.cost.map((c, i) => (
              <div key={i} className="kv">
                <span><ResIcon k={c.key} emoji={c.emoji} size={17} />{c.name}</span>
                <b style={{ color: c.ok ? 'var(--green)' : 'var(--crimson)' }}>{fmt(c.have)} / {fmt(c.need)}</b>
              </div>
            ))}
          </div>
          <button className="btn gold" style={{ marginTop: 16 }} disabled={busy || !detail.can_build} onClick={onBuild}>
            Заложить · {detail.build_hours} ч
          </button>
        </>
      )}
    </>
  )
}

// ── Экран производства ───────────────────────────────────────────────────
function ProductionView({ prod, busy, onStart, onClaim, onAge, onExpire, onBack, onExperiment, onFlash }: {
  prod: ProdState; busy: boolean
  onStart: (r: Recipe) => void; onClaim: () => void; onAge: () => void; onExpire: () => void; onBack: () => void
  onExperiment: (dto: ExperimentDTO) => void; onFlash: (m: string) => void
}) {
  const bw = prod.brewery
  const phase = bw?.phase
  const idle = prod.kind === 'brewery' ? phase === 'empty' : prod.batch.state === 'none'
  const ready = prod.kind === 'brewery' ? ['ready', 'ripe', 'overripe'].includes(phase || '') : prod.batch.state === 'ready'
  const active = !idle && !ready
  const warn = phase === 'ripe' || phase === 'overripe'        // выдержка перекисает — срочно
  const stockLabel = prod.to === 'inventory' ? 'На складе' : 'В погребе'
  const canSecret = prod.id === 'kitchen' && !!prod.experiment  // Кухня: доступна «Тайная кухня»
  const [mode, setMode] = useState<'cook' | 'secret'>('cook')

  const endsAt = prod.batch.ends_at ?? null
  const liveSecs = useLiveSecs(endsAt)
  const rem = liveSecs != null ? live(liveSecs) : hm(prod.kind === 'brewery' ? bw?.minutes ?? 0 : prod.batch.minutes)
  const status = statusOf(prod, rem)

  // дотикал до нуля — один раз подтянуть свежий стейт (active→ready, ripe→overripe)
  const fired = useRef(false)
  useEffect(() => {
    if (liveSecs === 0 && endsAt && !fired.current) { fired.current = true; onExpire() }
    if (liveSecs && liveSecs > 0) fired.current = false
  }, [liveSecs, endsAt, onExpire])

  return (
    <>
      <button className="lnk-back" onClick={onBack}>‹ Пристройки</button>
      <div className="prod-hero">
        <img src={art(prod.image)} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = 'none' }} />
        <div className="ph-cap">
          <b>{prod.name}</b>
          <span className="ph-stock">{stockLabel} · {prod.stock.map((s, i) => (
            <span key={s.key} className="ph-q">{i > 0 && <i className="ph-sep" />}<OutIcon it={s} />{fmt(s.qty)}</span>
          ))}</span>
        </div>
      </div>

      {canSecret && (
        <div className="sk-seg" role="tablist">
          <button className={mode === 'cook' ? 'on' : ''} onClick={() => { haptic('light'); setMode('cook') }}>🍳 Готовка</button>
          <button className={mode === 'secret' ? 'on' : ''} onClick={() => { haptic('light'); setMode('secret') }}>⚗️ Тайная кухня</button>
        </div>
      )}

      {canSecret && mode === 'secret' ? (
        <SecretKitchen dto={prod.experiment!} onResult={onExperiment} onFlash={onFlash} />
      ) : (
        <>
          <div className={`prod-status ${warn ? 'wn' : ready ? 'rd' : active ? 'ac' : ''}`}>{status}</div>

          {active && (
            <div className="prod-batch">
              <ProdBar secs={liveSecs ?? (prod.kind === 'brewery' ? (bw?.minutes ?? 0) : prod.batch.minutes) * 60} totalMin={prod.batch.total} />
              {prod.batch.out && <div className="pb-out"><OutIcon it={prod.batch.out} />×{prod.batch.out.qty}</div>}
            </div>
          )}

          {ready && (
            <div className="prod-claim">
              {prod.kind === 'brewery' ? (
                <>
                  <button className="btn green" disabled={busy} onClick={onClaim}>Разлить в погреб{prod.batch.out ? ` · ${prod.batch.out.qty}` : ''}</button>
                  {bw!.can_age && (
                    <button className="btn danger" disabled={busy} onClick={onAge}>Выдержать — риск +ярус ({bw!.mature_chance}%)</button>
                  )}
                </>
              ) : (
                <button className="btn green" disabled={busy} onClick={onClaim}>
                  {prod.to === 'inventory' ? 'Забрать на склад' : 'Забрать в погреб'}{prod.batch.out ? ` · ${prod.batch.out.qty}` : ''}
                </button>
              )}
            </div>
          )}

          {idle && (
            <div className="rcp-list">
              {prod.recipes.map((r) => (
                <RecipeRow key={r.key} r={r} busy={busy} onStart={() => onStart(r)} />
              ))}
            </div>
          )}

          {prod.flavor && <p className="prod-flavor">{prod.flavor}</p>}
        </>
      )}
    </>
  )
}

function RecipeRow({ r, busy, onStart }: { r: Recipe; busy: boolean; onStart: () => void }) {
  const afford = r.inputs.every((i) => i.ok)
  return (
    <button className="rcp" disabled={busy || !afford} onClick={onStart}>
      <OutIcon it={r} />
      <div className="rcp-mid">
        <span className="rcp-name">{r.name} <em>×{r.out_qty}</em></span>
        <span className="rcp-in">{r.inputs.map((i, k) => (
          <span key={k} style={{ color: i.ok ? 'var(--dim)' : 'var(--crimson)' }}>
            {k > 0 && ' '}<ResIcon k={i.key} emoji={i.emoji} size={14} />{fmt(i.have)}/{fmt(i.need)}
          </span>
        ))}</span>
      </div>
      <span className="rcp-go">{afford ? <>{r.time}<i className="chev">›</i></> : 'мало'}</span>
    </button>
  )
}
