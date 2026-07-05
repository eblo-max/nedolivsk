import { useState, useEffect, useRef, type CSSProperties } from 'react'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { ResIcon, GoodIcon, fmt } from '../components/icons'
import Sheet from '../components/Sheet'
import CoachTour, { useFirstVisitTour } from './CoachTour'
import ReputationSheet from './ReputationSheet'

interface Slot { slot: string; slot_name: string; id?: string; name?: string; tier?: number; sprite?: string; trophy?: boolean
  plus?: number; sharpen?: { next: number; cost: number; chance: number; gain?: string } }
interface Craft { state: string; name?: string; tier?: number; minutes?: number; sprite?: string }
interface HealOpt { key: string; name: string; emoji: string; hp: number; qty: number }
interface StashItem { entry: string; id: string; name: string; slot: string; slot_name: string; tier: number; plus: number; sprite: string; trophy: boolean; gain: Record<string, number> }
interface PBadge { key: string; emoji: string; short: string; style?: string; tier?: string; shown: boolean }
interface Prestige { titles: PBadge[]; facades: PBadge[]; has: boolean }
interface CharState {
  ok: boolean; name: string; worn: number; slots_total: number
  hp: { cur: number; max: number; regen: number }
  damage: number; crit: number; armor: number; luck: number; vylazka: number
  equipment: Slot[]; bonuses: { label: string; val: string }[]
  orc: { damage: number; crit: number; armor: number; luck: number; vitality?: number; income: number } | null
  craft: Craft
  heal: { can: boolean; full: boolean; options: HealOpt[] }
  stash?: StashItem[]
  prestige?: Prestige
}
interface ForgeCost { key: string; name: string; emoji?: string; need: number; have: number; ok: boolean }
interface ForgeItem {
  id: string; name: string; slot_name: string; sprite: string; desc: string
  cur: number; next: number; maxed: boolean; trophy: boolean
  gains_cur: string | null; gains_next: string; cost: ForgeCost[]; hours: number; afford: boolean
}
interface ForgeState { ok: boolean; pouch: Record<string, number>; items: ForgeItem[]; craft: { state: string; minutes: number } }

const stars = (t?: number) => '★'.repeat(t || 0)
const GICO: Record<string, string> = { damage: '⚔', crit: '💥', armor: '🛡', luck: '🍀', vitality: '❤' }
const gainStr = (g: Record<string, number>) =>
  Object.entries(g).map(([k, v]) => `+${v}${GICO[k] || k}${k === 'crit' ? '%' : ''}`).join(' ')
const TIER_NAME: Record<number, string> = { 1: 'обычный', 2: 'добротный', 3: 'мастерский' }
const sprite = (s?: string) => `${import.meta.env.BASE_URL}items/${s}.png`

// заглушка для предметов без арта (напр. орочий сет) — чтобы не было битых картинок
const NO_ART = 'data:image/svg+xml;utf8,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect x="9" y="9" width="30" height="30" rx="6" fill="#2a1c0d" stroke="#9c7838" stroke-width="2"/><path d="M19 19l10 10M29 19l-10 10" stroke="#c2965a" stroke-width="2.4" stroke-linecap="round"/></svg>')
function ItemImg({ s, className, style }: { s?: string; className?: string; style?: CSSProperties }) {
  return <img className={className} style={style} src={s ? sprite(s) : NO_ART} alt="" loading="lazy"
    onError={(e) => { if (e.currentTarget.src !== NO_ART) e.currentTarget.src = NO_ART }} />
}

// анимированный герой: крутим APNG только когда он в кадре и апп активен,
// иначе подменяем статичным кадром — экономия батареи/CPU на слабых
function AnimHero() {
  const ref = useRef<HTMLImageElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const base = import.meta.env.BASE_URL
    const anim = `${base}character/hero.png`, still = `${base}character/hero_static.png`
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    let onScreen = true
    const apply = () => { el.src = onScreen && document.visibilityState === 'visible' && !reduce ? anim : still }
    const io = new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; apply() }, { threshold: 0.05 })
    io.observe(el)
    document.addEventListener('visibilitychange', apply)
    return () => { io.disconnect(); document.removeEventListener('visibilitychange', apply) }
  }, [])
  return <img ref={ref} className="doll-hero" src={`${import.meta.env.BASE_URL}character/hero.png`} alt="Хозяин" />
}

// раскладка слотов вокруг фигуры: левая колонка | герой | правая колонка, снизу — ряд
const COL_L = ['head', 'chest', 'left_hand', 'belt']
const COL_R = ['weapon', 'right_hand', 'amulet', 'talisman']
const ROW_B = ['legs', 'boots', 'bag']

const SAMPLE: CharState = {
  ok: true, name: 'ХОЗЯИН', worn: 3, slots_total: 11,
  hp: { cur: 78, max: 100, regen: 44 }, damage: 25, crit: 12, armor: 18, luck: 8, vylazka: 16,
  equipment: [
    { slot: 'head', slot_name: 'Голова', id: 'leather_cap', name: 'Шапка трактирщика фарта +2', tier: 2, sprite: 'shapka', plus: 2, sharpen: { next: 3, cost: 195, chance: 90 } },
    { slot: 'chest', slot_name: 'Грудь', id: 'fartuk', name: 'Фартук трактирщика', tier: 1, sprite: 'bronya', plus: 0, sharpen: { next: 1, cost: 30, chance: 100 } },
    { slot: 'left_hand', slot_name: 'Левая рука' },
    { slot: 'right_hand', slot_name: 'Правая рука', id: 'master_axe', name: 'Топор хозяйский', tier: 1, sprite: 'master_axe' },
    { slot: 'weapon', slot_name: 'Оружие' }, { slot: 'belt', slot_name: 'Пояс' },
    { slot: 'legs', slot_name: 'Ноги' }, { slot: 'boots', slot_name: 'Сапоги' },
    { slot: 'amulet', slot_name: 'Амулет' }, { slot: 'talisman', slot_name: 'Талисман' },
    { slot: 'bag', slot_name: 'Сумка' },
  ],
  bonuses: [{ label: 'Доход', val: '+15%' }, { label: 'Добыча', val: '+5%' }],
  orc: null, craft: { state: 'none' },
  heal: { can: true, full: false, options: [
    { key: 'roast', name: 'Жаркое', emoji: '🍖', hp: 12, qty: 4 },
    { key: 'ale1', name: 'Эль', emoji: '🍺', hp: 4, qty: 12 },
  ] },
  stash: [
    { entry: 'kovsh:2', id: 'kovsh', name: 'Ковш боевой ★★', slot: 'weapon', slot_name: 'Оружие', tier: 2, plus: 0, sprite: 'oruzhie', trophy: false, gain: { damage: 20, crit: 9 } },
    { entry: 'fang_cleaver:1', id: 'fang_cleaver', name: 'Клычный тесак', slot: 'weapon', slot_name: 'Оружие', tier: 1, plus: 0, sprite: 'fang_cleaver', trophy: false, gain: { damage: 22, crit: 8 } },
    { entry: 'wolf_totem:1', id: 'wolf_totem', name: 'Тотем зверолова', slot: 'amulet', slot_name: 'Амулет', tier: 1, plus: 0, sprite: 'wolf_totem', trophy: false, gain: { crit: 3, luck: 6, vitality: 5 } },
  ],
  prestige: {
    has: true,
    titles: [
      { key: 'keeper', emoji: '🛡', short: 'Хранитель Твердыни', style: 'gold', shown: false },
      { key: 'spark', emoji: '⚡', short: 'Искра Артели', style: 'neon', shown: true },
      { key: 'legend', emoji: '👑', short: 'Вечный Зодчий', style: 'holo', shown: false },
    ],
    facades: [
      { key: 'carved', emoji: '🪵', short: 'Резной фасад', tier: 'bronze', shown: false },
      { key: 'blazing', emoji: '🔥', short: 'Пылающий герб', tier: 'legendary', shown: true },
    ],
  },
}

const CHAR_TOUR = [
  { sel: '[data-tut="doll"]', emoji: '🧍', title: 'Твой герой',
    body: 'Слоты по бокам — снаряжение: оружие, броня, амулеты. Что надел, то и видно на кукле. Пустые слоты стоит заполнить — голым в бой лучше не соваться.', place: 'bottom' as const },
  { sel: '[data-tut="stats"]', emoji: '⚔', title: 'Характеристики',
    body: 'Урон, крит, броня, живучесть (❤ здоровье) и удача. Они решают исход боя на охоте и в рейдах. Снаряга их растит — чем лучше вещи, тем сильнее ты.', place: 'top' as const },
  { sel: '[data-tut="forge-btn"]', emoji: '⚒', title: 'Кузница и заточка',
    body: 'Тут куёшь новые вещи из сырья, а надетые — точишь. Заточка заметно усиливает вещь (кнопка в детали вещи). Первая ковка — со скидкой, начни с неё.', place: 'top' as const },
]

export default function Character() {
  const charTour = useFirstVisitTour('character')
  const { data, loading, error, set, reload } = useApi<CharState>('character', SAMPLE)
  const [view, setView] = useState<'doll' | 'inv' | 'forge'>('doll')
  const [forge, setForge] = useState<ForgeState | null>(null)
  const [pick, setPick] = useState<ForgeItem | null>(null)
  const [pickSlot, setPickSlot] = useState<Slot | null>(null)
  const [healOpen, setHealOpen] = useState(false)
  const [repOpen, setRepOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200) }

  // реалтайм: тихо обновляем живые данные (HP/реген/таймер ковки) — периодически
  // и при возврате в приложение; пауза во время действия/открытой панели
  const guard = useRef({ busy, pick, healOpen })
  guard.current = { busy, pick, healOpen }
  useEffect(() => {
    const refresh = () => {
      const g = guard.current
      if (document.visibilityState === 'visible' && !g.busy && !g.pick && !g.healOpen) reload()
    }
    const iv = setInterval(refresh, 20000)
    document.addEventListener('visibilitychange', refresh)
    return () => { clearInterval(iv); document.removeEventListener('visibilitychange', refresh) }
  }, [reload])

  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  // в проде сбой загрузки — честная ошибка, а не подмена заглушкой
  if (error && error !== 'no_tavern' && !import.meta.env.DEV) return (
    <div className="center" style={{ flex: 1, flexDirection: 'column', gap: 14, padding: 26, textAlign: 'center' }}>
      <div className="muted" style={{ fontStyle: 'italic' }}>Не удалось загрузить персонажа.</div>
      <button className="btn gold" style={{ maxWidth: 220 }} onClick={() => reload()}>Повторить</button>
    </div>
  )
  const c = data ?? SAMPLE

  async function openForge() {
    haptic('light'); setView('forge')
    try { const r = await api<ForgeState>('forge'); setForge(r) }
    catch { setForge(FORGE_SAMPLE) }
  }
  // тап по надетой вещи на кукле → деталь ПОВЕРХ Персонажа (закрытие вернёт на куклу)
  async function openItem(id: string) {
    haptic('light')
    let f = forge
    if (!f) { try { f = await api<ForgeState>('forge') } catch { f = FORGE_SAMPLE } setForge(f) }
    setPickSlot(c.equipment.find((x) => x.id === id) ?? null)
    setPick(f.items.find((x) => x.id === id) ?? null)
  }
  async function sharpen(slot: string) {
    if (busy) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ success: boolean; name: string; gain?: string }>('sharpen', { slot })
      if (r.success) { hapticNotify('success'); flash(`⚒ ${r.name}${r.gain ? ` · ${r.gain}` : ''}`) }
      else { hapticNotify('warning'); flash('Сорвалась! Золото осталось у кузнеца') }
      setPick(null); setPickSlot(null); reload()
    } catch (e) {
      hapticNotify('warning')
      const code = (e as { code?: string })?.code
      flash(code === 'gold' ? 'Не хватает золота' : code === 'max' ? 'Острее не бывает' : 'Не вышло')
    } finally { setBusy(false) }
  }
  async function claim() {
    if (busy) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ character: CharState; forge: ForgeState; item: string; tier: number }>('craft_claim')
      set(r.character); setForge(r.forge); hapticNotify('success'); flash(`${r.item} ${stars(r.tier)} — твоё!`); setView('doll')
    } catch { hapticNotify('warning'); flash('Ещё не готово') }
    finally { setBusy(false) }
  }
  async function heal(key: string) {
    if (busy) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ character: CharState; healed: number }>('heal', { key })
      set(r.character); hapticNotify('success'); flash(`+${r.healed} ❤`)
    } catch { hapticNotify('warning'); flash('Лечиться нечем') }
    finally { setBusy(false) }
  }
  async function equip(entry: string) {
    if (busy) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ character: CharState }>('gear/equip', { entry })
      set(r.character); hapticNotify('success'); flash('Надето')
    } catch { hapticNotify('warning'); flash('Не вышло надеть') }
    finally { setBusy(false) }
  }
  async function unequip(slot: string) {
    if (busy) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ character: CharState }>('gear/unequip', { slot })
      set(r.character); hapticNotify('success'); flash('Снято в сток')
    } catch { hapticNotify('warning'); flash('Слот пуст') }
    finally { setBusy(false) }
  }
  async function pickPrestige(kind: 'title' | 'facade', key: string) {
    if (busy) return
    haptic('light'); setBusy(true)
    try {
      const r = await api<{ prestige: Prestige }>('artel/prestige', { kind, key })
      set({ ...c, prestige: r.prestige }); hapticNotify('success')
    } catch { hapticNotify('warning') }
    finally { setBusy(false) }
  }
  async function make(item: ForgeItem) {
    if (busy) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ character: CharState; forge: ForgeState; item: string; tier: number; hours: number }>('forge_make', { item_id: item.id })
      set(r.character); setForge(r.forge); hapticNotify('success')
      flash(`Мастер взялся: ${r.item} ${stars(r.tier)} · ${r.hours} ч`); setPick(null); setView('doll')
    } catch (e) {
      hapticNotify('warning')
      const code = (e as { code?: string })?.code
      flash(code === 'busy' ? 'Мастер занят заказом' : code === 'not_enough' ? 'Не хватает на ковку' : code === 'max_tier' ? 'Лучше не выкуют' : 'Не вышло')
    } finally { setBusy(false) }
  }

  const craftBanner = (st: Craft) => {
    if (st.state === 'ready') return (
      <button className="btn gold rise" disabled={busy} onClick={claim} style={{ marginBottom: 2 }}>
        🎁 Забрать готовую вещь{st.name ? ` · ${st.name} ${stars(st.tier)}` : ''}
      </button>
    )
    if (st.state === 'active') return (
      <div className="card rise"><div className="card-b" style={{ flexDirection: 'row', alignItems: 'center', gap: 11 }}>
        {st.sprite && <ItemImg className="ti-img" style={{ width: 34, height: 34 }} s={st.sprite} />}
        <div style={{ flex: 1 }}>
          <div style={{ fontFamily: 'var(--disp)', fontSize: 13, color: 'var(--brass)', letterSpacing: 1 }}>⚒ МАСТЕР КУЁТ</div>
          <div className="muted" style={{ fontSize: 13 }}>{st.name} {stars(st.tier)} — ещё {Math.floor((st.minutes || 0) / 60)} ч {(st.minutes || 0) % 60} мин</div>
        </div>
      </div></div>
    )
    return null
  }

  // ── КУЗНИЦА ──
  if (view === 'forge') {
    const f = forge
    return (
      <>
        <div className="hero rise" style={{ paddingTop: 2 }}>
          <div className="nm" style={{ fontSize: 22 }}>⚒ КУЗНИЦА</div>
          <div className="flavor">«Мастер плюёт на ладони и косится на твоё золото. Один заказ за раз, деньги вперёд.»</div>
        </div>
        {f && (
          <div className="chips rise" style={{ justifyContent: 'center' }}>
            {Object.entries(f.pouch).map(([k, v]) => v > 0 || k === 'gold'
              ? <span key={k} className="chip"><ResIcon k={k} /> <b style={{ fontFamily: 'var(--num)' }}>{fmt(v)}</b></span> : null)}
          </div>
        )}
        {f && craftBanner(c.craft)}
        {!f ? <div className="center" style={{ padding: 30 }}><div className="spin" /></div> : (
          <div className="card rise"><div className="card-b" style={{ gap: 8 }}>
            {f.items.map((it) => (
              <button key={it.id} className="forge-row" onClick={() => { haptic('light'); setPick(it) }}>
                <ItemImg className="fr-img" s={it.sprite} />
                <span className="fr-txt">
                  <b>{it.trophy ? '🏆 ' : ''}{it.name} <span className="stars">{stars(it.cur)}</span></b>
                  <small>{it.slot_name}{it.gains_cur ? ` · ${it.gains_cur}` : ''}</small>
                </span>
                <span className="act-chev">›</span>
              </button>
            ))}
          </div></div>
        )}
        <button className="btn rise" onClick={() => { haptic('light'); setView('doll') }}>← Персонаж</button>
        {pick && <ItemSheet item={pick} busy={busy} craftState={c.craft.state} onMake={make} onClose={() => setPick(null)} />}
        {toast && <div className="toast">{toast}</div>}
      </>
    )
  }

  // ── ИНВЕНТАРЬ (сток снаряги + выбор звания/фасада) ──
  if (view === 'inv') {
    const equipped = c.equipment.filter((s) => s.id)
    const stash = c.stash ?? []
    const pr = c.prestige
    return (
      <>
        <div className="hero rise" style={{ paddingTop: 2 }}>
          <div className="nm" style={{ fontSize: 22 }}>🎒 ИНВЕНТАРЬ</div>
          <div className="flavor">«Что надел — то и в бой. Остальное лежит в мешке, ждёт своего часа.»</div>
        </div>

        <div className="inv-sec rise">
          <div className="inv-h">🎽 Надето <small>{equipped.length}/{c.slots_total}</small></div>
          <div className="inv-list">
            {equipped.length === 0 && <div className="inv-empty">Голышом. Надень что-нибудь из стока или скуй в кузнице.</div>}
            {equipped.map((s) => (
              <div key={s.slot} className="inv-row">
                <ItemImg className="inv-img" s={s.sprite} />
                <span className="inv-txt"><b>{s.trophy ? '🏆 ' : ''}{s.name} <span className="stars">{stars(s.tier)}</span></b><small>{s.slot_name}</small></span>
                <button className="inv-btn off" disabled={busy} onClick={() => unequip(s.slot)}>Снять</button>
              </div>
            ))}
          </div>
        </div>

        <div className="inv-sec rise" style={{ animationDelay: '.04s' }}>
          <div className="inv-h">📦 Сток <small>{stash.length}</small></div>
          <div className="inv-list">
            {stash.length === 0 && <div className="inv-empty">Сток пуст. Скуёшь новую вещь в занятый слот — старая ляжет сюда, не пропадёт.</div>}
            {stash.map((s) => (
              <div key={s.entry} className="inv-row">
                <ItemImg className="inv-img" s={s.sprite} />
                <span className="inv-txt"><b>{s.trophy ? '🏆 ' : ''}{s.name} <span className="stars">{stars(s.tier)}</span></b>
                  <small>{s.slot_name}{Object.keys(s.gain).length ? ` · ${gainStr(s.gain)}` : ''}</small></span>
                <button className="inv-btn on" disabled={busy} onClick={() => equip(s.entry)}>Надеть</button>
              </div>
            ))}
          </div>
        </div>

        {pr && pr.has && pr.titles.length > 0 && (
          <div className="inv-sec rise" style={{ animationDelay: '.08s' }}>
            <div className="inv-h">🏛 Звание <small>у имени</small></div>
            <div className="inv-badges">
              {pr.titles.map((t) => (
                <button key={t.key} className={`inv-badge st-${t.style || 'gold'}${t.shown ? ' sel' : ''}`}
                  disabled={busy} onClick={() => pickPrestige('title', t.key)}>{t.emoji} {t.short}</button>
              ))}
              <button className={`inv-badge plain${pr.titles.every((t) => !t.shown) ? ' sel' : ''}`}
                disabled={busy} onClick={() => pickPrestige('title', '')}>авто · высший</button>
            </div>
          </div>
        )}
        {pr && pr.has && pr.facades.length > 0 && (
          <div className="inv-sec rise" style={{ animationDelay: '.1s' }}>
            <div className="inv-h">🪧 Фасад <small>вывески</small></div>
            <div className="inv-badges">
              {pr.facades.map((f) => (
                <button key={f.key} className={`inv-badge rar-${f.tier || 'gold'}${f.shown ? ' sel' : ''}`}
                  disabled={busy} onClick={() => pickPrestige('facade', f.key)}>{f.emoji} {f.short}</button>
              ))}
              <button className={`inv-badge plain${pr.facades.every((f) => !f.shown) ? ' sel' : ''}`}
                disabled={busy} onClick={() => pickPrestige('facade', '')}>без фасада</button>
            </div>
          </div>
        )}

        <button className="btn rise" onClick={() => { haptic('light'); setView('doll') }}>← Персонаж</button>
        {toast && <div className="toast">{toast}</div>}
      </>
    )
  }

  // ── ПЕРСОНАЖ (кукла) ──
  return (
    <>
      {charTour.show && view === 'doll' && (
        <CoachTour steps={CHAR_TOUR} onDone={charTour.finish} endLabel="Понятно" />
      )}
      <div className="hero rise" style={{ paddingBottom: 0 }}>
        <div className="nm">{c.name}</div>
        <div className="meta"><span className="region">Хозяин кабака</span>
          <span className="region"><img className="meta-ic" src={`${import.meta.env.BASE_URL}stat/gear.png`} alt="" /> надето {c.worn}/{c.slots_total}</span></div>
        <div className="flavor" style={{ margin: '6px 14px 0', fontSize: 13.5 }}>«Морда кирпичом, руки в мозолях.»</div>
      </div>

      {/* кукла: герой (анимированный) парит в воздухе, слоты по бокам — без рамки */}
      <div className="doll rise" data-tut="doll">
        <div className="doll-col">{COL_L.map((k) => <SlotBox key={k} s={bySlot(c, k)} onTap={openItem} onEmpty={openForge} />)}</div>
        <div className="doll-fig"><AnimHero /></div>
        <div className="doll-col">{COL_R.map((k) => <SlotBox key={k} s={bySlot(c, k)} onTap={openItem} onEmpty={openForge} />)}</div>
        <div className="doll-bottom">{ROW_B.map((k) => <SlotBox key={k} s={bySlot(c, k)} onTap={openItem} onEmpty={openForge} />)}</div>
      </div>

      {craftBanner(c.craft)}

      {/* боевые — плавающая лента, без рамки */}
      <div className="statband rise" data-tut="stats" style={{ animationDelay: '.04s' }}>
        <div className="cap">БОЕВЫЕ</div>
        <div className="stat-hp">
          <span className="shp-ic">❤</span>
          <HpBar cur={c.hp.cur} max={c.hp.max} />
          <span className="shp-val">{c.hp.cur}/{c.hp.max}{c.hp.cur < c.hp.max ? ` · ${Math.floor(c.hp.regen / 60)}ч ${c.hp.regen % 60}м` : ''}</span>
        </div>
        {c.heal.can && (
          <button className="heal-btn" onClick={() => { haptic('light'); setHealOpen(true) }}>
            🍖 Подлечиться{c.heal.options.length ? '' : ' — нечем'}
          </button>
        )}
        <div className="stat-ribbon">
          <span className="si"><b>⚔</b>{c.damage}</span>
          <span className="si"><b>💥</b>{c.crit}%</span>
          <span className="si"><b>🛡</b>{c.armor}</span>
          <span className="si"><img className="ric" src={`${import.meta.env.BASE_URL}stat/luck.png`} alt="" />{c.luck}<small> · {c.vylazka}%</small></span>
        </div>
      </div>

      {c.bonuses.length > 0 && (
        <div className="statband rise" style={{ animationDelay: '.08s' }}>
          <div className="cap">ХОЗЯЙСТВО</div>
          <div className="stat-econ">
            {c.bonuses.map((b, i) => <span key={i} className="se">{b.label} <b>{b.val}</b></span>)}
          </div>
        </div>
      )}

      {c.orc && (
        <div className="stat-orc rise" style={{ animationDelay: '.1s' }}>
          <b>🪓 СЕТ ОРДЫ</b> +{c.orc.damage} урон · +{c.orc.crit}% крит · +{c.orc.armor} броня · +{c.orc.luck} удача{c.orc.vitality ? ` · +${c.orc.vitality} ❤` : ''} · +{c.orc.income}% доход
        </div>
      )}

      <div className="flavor rise" style={{ margin: '8px 14px 4px', fontSize: 13.5, animationDelay: '.14s' }}>«Голый трактирщик — смешной трактирщик. Загляни в кузницу.»</div>
      <div className="char-cta rise" style={{ animationDelay: '.16s' }}>
        <button className="btn gold" data-tut="forge-btn" onClick={openForge}>⚒ В кузницу</button>
        <button className="btn" onClick={() => { haptic('light'); setView('inv') }}>🎒 Инвентарь</button>
        <button className="btn" onClick={() => { haptic('light'); setRepOpen(true) }}>🤝 Репутация</button>
      </div>
      {pick && <ItemSheet item={pick} worn={pickSlot} busy={busy} craftState={c.craft.state} onMake={make} onSharpen={sharpen} onClose={() => { setPick(null); setPickSlot(null) }} />}
      {healOpen && <HealSheet full={c.heal.full} options={c.heal.options} busy={busy} onHeal={heal} onClose={() => setHealOpen(false)} />}
      {repOpen && <ReputationSheet onClose={() => setRepOpen(false)} />}
      {toast && <div className="toast">{toast}</div>}
    </>
  )
}

function HealSheet({ full, options, busy, onHeal, onClose }: {
  full: boolean; options: HealOpt[]; busy: boolean; onHeal: (key: string) => void; onClose: () => void
}) {
  return (
    <Sheet title="🍖 ПОДЛЕЧИТЬСЯ" onClose={onClose}>
      <p className="sheet-desc">«Что съешь — в погреб не вернётся. Жаркое сытнее эля.»</p>
      {full
        ? <p className="muted" style={{ fontStyle: 'italic', marginTop: 8 }}>Сыт и здоров — лечиться незачем.</p>
        : options.length === 0
          ? <p className="muted" style={{ fontStyle: 'italic', marginTop: 8 }}>В погребе пусто — свари жаркое на кухне или налей дешёвого эля.</p>
          : (
            <div className="sheet-list">
              {options.map((o) => (
                <button key={o.key} className="forge-row" disabled={busy} onClick={() => onHeal(o.key)}>
                  <GoodIcon k={o.key} />
                  <span className="fr-txt"><b>{o.name} <span style={{ color: 'var(--green)' }}>+{o.hp} ❤</span></b>
                    <small>в погребе {o.qty}</small></span>
                  <span className="act-chev">›</span>
                </button>
              ))}
            </div>
          )}
    </Sheet>
  )
}

function ItemSheet({ item, worn, busy, craftState, onMake, onSharpen, onClose }: {
  item: ForgeItem; worn?: Slot | null; busy: boolean; craftState: string
  onMake: (i: ForgeItem) => void; onSharpen?: (slot: string) => void; onClose: () => void
}) {
  const canForge = !item.trophy && !item.maxed
  return (
    <Sheet icon={sprite(item.sprite)} title={(worn?.name || item.name).toUpperCase()} onClose={onClose}>
      <div className="item-hero">
        <ItemImg s={item.sprite} />
        <div>
          <div className="ih-name">{worn?.name || item.name} <span className="stars">{stars(item.trophy || item.maxed ? item.cur : item.next)}</span></div>
          <div className="muted" style={{ fontSize: 13 }}>{item.slot_name}{item.cur > 0 && !item.maxed ? ` · перековка ${stars(item.cur)} → ${stars(item.next)} (${TIER_NAME[item.next]})` : !item.maxed ? ` · ${TIER_NAME[item.next]}` : ''}</div>
        </div>
      </div>
      <p className="sheet-desc">«{item.desc}»</p>

      <div className="sheet-row"><span>{item.maxed ? 'Даёт' : 'Будет давать'}</span>
        <b style={{ color: 'var(--gold-2)', textAlign: 'right' }}>{item.gains_next || '—'}</b></div>
      {!item.maxed && <div className="sheet-row"><span>Ковать</span><b>{item.hours} ч</b></div>}

      {canForge && item.cost.length > 0 && (
        <>
          <div className="sheet-sub" style={{ marginTop: 12 }}>ЦЕНА</div>
          <div className="sheet-list">
            {item.cost.map((c, i) => (
              <div key={i} className="sheet-task">
                <ResIcon k={c.key} emoji={c.emoji} /><span className="l">{c.name}</span>
                <span className="r" style={{ color: c.ok ? 'var(--green)' : 'var(--crimson)' }}>{fmt(c.have)} / {fmt(c.need)}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {worn?.sharpen && onSharpen && (
        <button className="btn" style={{ marginTop: 12 }} disabled={busy}
          onClick={() => onSharpen(worn.slot)}>
          ⚒ Заточить до +{worn.sharpen.next} — {worn.sharpen.cost} 🪙{worn.sharpen.chance < 100 ? ` · шанс ${worn.sharpen.chance}%` : ''}
          {worn.sharpen.gain && <small style={{ display: 'block', opacity: .85 }}>даст {worn.sharpen.gain}</small>}
        </button>
      )}
      {worn && (worn.plus ?? 0) >= 5 && (
        <p className="muted" style={{ fontStyle: 'italic', marginTop: 10 }}>Заточена до предела — острее не бывает.</p>
      )}
      {item.trophy
        ? <p className="muted" style={{ fontStyle: 'italic', marginTop: 12 }}>🏆 Трофей с босса — в кузнице не куётся. Старший ярус только дропом.</p>
        : item.maxed
          ? <p className="muted" style={{ fontStyle: 'italic', marginTop: 12 }}>Мастерская работа — лучше уже не выкуют.</p>
          : <button className="btn gold" style={{ marginTop: 14 }} disabled={busy || !item.afford || craftState !== 'none'}
              onClick={() => onMake(item)}>
              {craftState !== 'none' ? 'Мастер занят' : item.afford ? `⚒ Сковать ${stars(item.next)}` : 'Не хватает ресурсов'}
            </button>}
    </Sheet>
  )
}

// чистый HP-бар: заливка плавно анимируется от 0 при заходе (без бликов и точек)
function HpBar({ cur, max }: { cur: number; max: number }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, Math.round((cur / max) * 100))) : 0
  const [w, setW] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setW(pct)))
    return () => cancelAnimationFrame(id)
  }, [pct])
  return (
    <div className="hpbar">
      <div className="hpbar-fill" style={{ width: `${w}%` }} />
    </div>
  )
}

const bySlot = (c: CharState, k: string): Slot =>
  c.equipment.find((s) => s.slot === k) ?? { slot: k, slot_name: k }

function SlotBox({ s, onTap, onEmpty }: { s: Slot; onTap: (id: string) => void; onEmpty: () => void }) {
  if (s.id) return (
    <button className={`slot t${s.tier || 1}`} aria-label={s.name} title={s.name} onClick={() => onTap(s.id!)}>
      <ItemImg s={s.sprite} />
      {(s.tier || 1) > 1 && <span className="slot-t">{stars(s.tier)}</span>}
    </button>
  )
  return <button className="slot empty" aria-label={s.slot_name} title={`${s.slot_name} — пусто`} onClick={onEmpty} />
}

const FORGE_SAMPLE: ForgeState = {
  ok: true, pouch: { gold: 1340, wood: 60, grain: 80, hops: 45, ingot: 12 },
  craft: { state: 'none', minutes: 0 },
  items: [
    { id: 'leather_cap', name: 'Шапка трактирщика', slot_name: 'Голова', sprite: 'shapka', desc: 'Скрывает похмелье и лысину.', cur: 2, next: 3, maxed: false, trophy: false, gains_cur: '+10% доход · 🛡4', gains_next: '+15% доход · 🛡6', hours: 6, afford: true, cost: [{ key: 'gold', name: 'Золото', need: 7200, have: 1340, ok: false }, { key: 'grain', name: 'Зерно', need: 720, have: 80, ok: false }] },
    { id: 'kovsh', name: 'Ковш боевой', slot_name: 'Оружие', sprite: 'oruzhie', desc: 'Черпает эль, проламывает черепа.', cur: 0, next: 1, maxed: false, trophy: false, gains_cur: null, gains_next: '+10% добыча · ⚔14 · 💥7%', hours: 6, afford: true, cost: [{ key: 'gold', name: 'Золото', need: 1650, have: 1340, ok: false }, { key: 'ingot', name: 'Слиток', need: 18, have: 12, ok: false }] },
    { id: 'rat_crown', name: 'Корона Крысиного Короля', slot_name: 'Голова', sprite: 'rat_crown', desc: 'Крысы кланялись — теперь кланяйся ты.', cur: 1, next: 1, maxed: true, trophy: true, gains_cur: '+3% доход · 🛡6 · 🍀4', gains_next: '+3% доход · 🛡6 · 🍀4', hours: 0, afford: false, cost: [] },
  ],
}
