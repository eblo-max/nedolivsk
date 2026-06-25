import { useState, useEffect, useRef, type CSSProperties } from 'react'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify, initData } from '../telegram'
import { ResIcon, GoodIcon, fmt } from '../components/icons'
import Sheet from '../components/Sheet'

interface Slot { slot: string; slot_name: string; id?: string; name?: string; tier?: number; sprite?: string; trophy?: boolean }
interface Craft { state: string; name?: string; tier?: number; minutes?: number; sprite?: string }
interface HealOpt { key: string; name: string; emoji: string; hp: number; qty: number }
interface CharState {
  ok: boolean; name: string; worn: number; slots_total: number
  hp: { cur: number; max: number; regen: number }
  damage: number; crit: number; armor: number; luck: number; vylazka: number
  equipment: Slot[]; bonuses: { label: string; val: string }[]
  orc: { damage: number; crit: number; armor: number; luck: number; income: number } | null
  craft: Craft
  heal: { can: boolean; full: boolean; options: HealOpt[] }
}
interface ForgeCost { key: string; name: string; emoji?: string; need: number; have: number; ok: boolean }
interface ForgeItem {
  id: string; name: string; slot_name: string; sprite: string; desc: string
  cur: number; next: number; maxed: boolean; trophy: boolean
  gains_cur: string | null; gains_next: string; cost: ForgeCost[]; hours: number; afford: boolean
}
interface ForgeState { ok: boolean; pouch: Record<string, number>; items: ForgeItem[]; craft: { state: string; minutes: number } }

const stars = (t?: number) => '★'.repeat(t || 0)
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
    { slot: 'head', slot_name: 'Голова', id: 'leather_cap', name: 'Шапка трактирщика', tier: 2, sprite: 'shapka' },
    { slot: 'chest', slot_name: 'Грудь', id: 'fartuk', name: 'Фартук трактирщика', tier: 1, sprite: 'bronya' },
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
}

export default function Character() {
  const { data, loading, error, set, reload } = useApi<CharState>('character', SAMPLE)
  const [view, setView] = useState<'doll' | 'forge'>('doll')
  const [forge, setForge] = useState<ForgeState | null>(null)
  const [pick, setPick] = useState<ForgeItem | null>(null)
  const [healOpen, setHealOpen] = useState(false)
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
  // в реальном Telegram сбой загрузки — честная ошибка, а не подмена заглушкой
  if (error && error !== 'no_tavern' && initData()) return (
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
    setPick(f.items.find((x) => x.id === id) ?? null)
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

  // ── ПЕРСОНАЖ (кукла) ──
  return (
    <>
      <div className="hero rise" style={{ paddingBottom: 0 }}>
        <div className="nm">{c.name}</div>
        <div className="meta"><span className="region">Хозяин кабака</span>
          <span className="region"><img className="meta-ic" src={`${import.meta.env.BASE_URL}stat/gear.png`} alt="" /> надето {c.worn}/{c.slots_total}</span></div>
        <div className="flavor" style={{ margin: '6px 14px 0', fontSize: 13.5 }}>«Морда кирпичом, руки в мозолях.»</div>
      </div>

      {/* кукла: герой (анимированный) парит в воздухе, слоты по бокам — без рамки */}
      <div className="doll rise">
        <div className="doll-col">{COL_L.map((k) => <SlotBox key={k} s={bySlot(c, k)} onTap={openItem} onEmpty={openForge} />)}</div>
        <div className="doll-fig"><AnimHero /></div>
        <div className="doll-col">{COL_R.map((k) => <SlotBox key={k} s={bySlot(c, k)} onTap={openItem} onEmpty={openForge} />)}</div>
        <div className="doll-bottom">{ROW_B.map((k) => <SlotBox key={k} s={bySlot(c, k)} onTap={openItem} onEmpty={openForge} />)}</div>
      </div>

      {craftBanner(c.craft)}

      {/* боевые — плавающая лента, без рамки */}
      <div className="statband rise" style={{ animationDelay: '.04s' }}>
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
          <b>🪓 СЕТ ОРДЫ</b> +{c.orc.damage} урон · +{c.orc.crit}% крит · +{c.orc.armor} броня · +{c.orc.luck} удача · +{c.orc.income}% доход
        </div>
      )}

      <div className="flavor rise" style={{ margin: '8px 14px 4px', fontSize: 13.5, animationDelay: '.14s' }}>«Голый трактирщик — смешной трактирщик. Загляни в кузницу.»</div>
      <button className="btn gold rise" style={{ animationDelay: '.16s' }} onClick={openForge}>⚒ В кузницу</button>
      {pick && <ItemSheet item={pick} busy={busy} craftState={c.craft.state} onMake={make} onClose={() => setPick(null)} />}
      {healOpen && <HealSheet full={c.heal.full} options={c.heal.options} busy={busy} onHeal={heal} onClose={() => setHealOpen(false)} />}
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

function ItemSheet({ item, busy, craftState, onMake, onClose }: {
  item: ForgeItem; busy: boolean; craftState: string; onMake: (i: ForgeItem) => void; onClose: () => void
}) {
  const canForge = !item.trophy && !item.maxed
  return (
    <Sheet icon={sprite(item.sprite)} title={item.name.toUpperCase()} onClose={onClose}>
      <div className="item-hero">
        <ItemImg s={item.sprite} />
        <div>
          <div className="ih-name">{item.name} <span className="stars">{stars(item.trophy || item.maxed ? item.cur : item.next)}</span></div>
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
