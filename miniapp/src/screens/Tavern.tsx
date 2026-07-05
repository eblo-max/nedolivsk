import { useState, useRef, useEffect, lazy, Suspense } from 'react'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify, takeStartParam } from '../telegram'
import { ResIcon, GoodIcon, fmt } from '../components/icons'
import Onboarding from './Onboarding'
import ActionSheet from './ActionSheet'
import MusicToggle from '../components/MusicToggle'
import type { StoryData } from './StoryVisitor'
import type { TradeData } from './TradeSheet'
import AnimEmoji from '../components/AnimEmoji'

// Шторки открываются по клику — ленивые чанки, чтобы не тащить их в стартовый
// бандл Таверны (RaidSheet со спрайт-боёвкой — самый тяжёлый).
const StoryVisitor = lazy(() => import('./StoryVisitor'))
const TradeSheet = lazy(() => import('./TradeSheet'))
const ChronicleSheet = lazy(() => import('./ChronicleSheet'))
const RatingSheet = lazy(() => import('./RatingSheet'))
const ReferralSheet = lazy(() => import('./ReferralSheet'))
const RaidSheet = lazy(() => import('./RaidSheet'))
const InvasionSheet = lazy(() => import('./InvasionSheet'))
const NotificationsSheet = lazy(() => import('./NotificationsSheet'))
const GuideSheet = lazy(() => import('./GuideSheet'))
const WonderSheet = lazy(() => import('./WonderSheet'))
const ArtelSheet = lazy(() => import('./ArtelSheet'))

interface Activity { icon?: string; text: string; sub?: string; badge?: 'ready' | 'wait'; progress?: number; gold?: boolean; action?: string }
interface ResLine { key: string; name: string; amount: number }
interface CellarLine { key: string; name: string; qty: number }
interface WEffect { text: string; good: boolean }
interface WorldEvent { id: string; emoji: string; name: string; blurb: string; good?: string | null; good_name?: string | null; effects: WEffect[] }
interface CityFaction { id: string; name: string; power: number }
interface CityData { mood: number; mood_label: string; situation: { emoji: string; label: string } | null; factions: CityFaction[] }
interface RaidSummary {
  id: number; name: string; emoji: string; sprite: string
  status: 'gathering' | 'active' | 'dead' | 'expired'; me_registered: boolean
  n: number; left?: number; hp_pct?: number; phase?: number
}
interface TavernState {
  ok: boolean
  name: string; level: number; region: string; flavor: string
  gold: number; income_rate: number; income_ready: number; reputation: number
  capacity: number; comfort: number; luck_pct: number; gear_worn: number; gear_slots: number
  now: Activity[]
  storage: ResLine[]; cellar: CellarLine[]
  world: string[]
  next_upgrade?: Record<string, number> | null; upgrade_pct?: number | null; maxed?: boolean
  story?: StoryData | null
  world_event?: WorldEvent | null
  city?: CityData | null
  fgoal?: { fac: string; text: string; emblem?: string; title?: string; task?: string; done: number; target: number; pct: number; feast: boolean } | null
  trade?: TradeData | null
  raid?: RaidSummary | null
  admin?: boolean
  notif_unread?: number
}

// образец для оффлайн-превью (форма 1:1 как у /api/state)
const SAMPLE: TavernState = {
  ok: true, name: 'Кривая Кружка', level: 2, region: 'Изумрудная Чарка',
  flavor: 'Свечи оплыли, эль выдохся, но гости всё прут — знать, иначе некуда.',
  gold: 1340, income_rate: 18, income_ready: 126, reputation: 27,
  capacity: 24, comfort: 12, luck_pct: 8, gear_worn: 1, gear_slots: 11,
  now: [
    { icon: '🍺', text: 'Гости ждут заказ', sub: 'выкупят товар из погреба', badge: 'ready', action: 'retail' },
    { icon: '🎁', text: 'Бонус дня готов', sub: 'забери и активируй', badge: 'ready', action: 'bonus' },
    { icon: '📜', text: 'Грамота новосёла', sub: 'награда ждёт', badge: 'ready', action: 'newbie' },
    { icon: '⛏', text: 'Бригады вернулись (1)', sub: 'забирай добычу', badge: 'ready', action: 'expedition' },
    { icon: '🏭', text: 'Пристройки: 1 готовы', sub: 'забери в разделе', badge: 'ready' },
  ],
  storage: [
    { key: 'wood', name: 'Дерево', amount: 60 }, { key: 'grain', name: 'Зерно', amount: 80 },
    { key: 'hops', name: 'Хмель', amount: 45 }, { key: 'ore', name: 'Руда', amount: 30 },
  ],
  cellar: [
    { key: 'ale1', name: 'Эль', qty: 12 }, { key: 'roast', name: 'Жаркое', qty: 4 },
    { key: 'pie', name: 'Пирог', qty: 3 },
  ],
  world: ['🍂 Осень — спрос обычный', '🪓 Орда орков точит топоры на севере', '🏛 В городе тихо'],
  next_upgrade: { gold: 715, wood: 220, grain: 180, hops: 120 }, upgrade_pct: 60,
  world_event: { id: 'fashion', emoji: '🔥', name: 'Ажиотаж', blurb: 'Весь Недоливск помешался на одном товаре — он в цене, налетай!', good: 'butter', good_name: 'Масло', effects: [{ text: 'Масло ×1.5', good: true }] },
  fgoal: { fac: 'merchants', text: '', emblem: '⚜️', title: 'Большой торг', task: 'Наторгуйте 75000 🪙 всем городом — купцы, гости, аукцион', done: 41300, target: 75000, pct: 55, feast: false },
  city: { mood: 18, mood_label: '🙂 доброе', situation: { emoji: '💰', label: 'Купеческий бум' }, factions: [{ id: 'merchants', name: 'Купеческая лига', power: 42 }, { id: 'thieves', name: 'Воровская гильдия', power: 20 }, { id: 'watch', name: 'Стража', power: -15 }] },
  raid: null, admin: true,   // DEV: нет живого рейда → видно админ-кнопку «Призвать босса»
  notif_unread: 3,
}

export default function Tavern() {
  const { data, loading, error, set, reload } = useApi<TavernState>('state', SAMPLE)
  const [toast, setToast] = useState('')
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState(false)
  const [sheet, setSheet] = useState<string | null>(null)
  const [storyOpen, setStoryOpen] = useState(false)
  const [chronOpen, setChronOpen] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)
  const [ratingOpen, setRatingOpen] = useState(false)   // доска почёта (топ таверн)
  const [refOpen, setRefOpen] = useState(false)
  const [raidOpen, setRaidOpen] = useState(false)       // экран рейд-босса
  const [invOpen, setInvOpen] = useState(false)         // панель сбора орды («в строй»)
  const [notifOpen, setNotifOpen] = useState(false)     // лента уведомлений
  const [wonderOpen, setWonderOpen] = useState(false)   // общая стройка «Чудо города»
  const [artelOpen, setArtelOpen] = useState(false)     // Лавка Артели (сток зодаров)
  const storySeen = useRef<string | null>(null)        // авто-показ визитёра один раз на его id
  const [trade, setTrade] = useState<TradeData | null>(null)   // заезжий купец (торг)
  const tradeShut = useRef(false)                       // купца закрыли вручную — не нудить повторно
  const panelCache = useRef<Record<string, unknown>>({})
  const toastTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const flash = (m: string) => {
    setToast(m); clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(''), 2200)
  }

  // дип-линк из анонса/тизера (?startapp=raid|notif) — сразу открыть нужный экран
  useEffect(() => {
    const sp = takeStartParam()
    if (sp === 'raid') setRaidOpen(true)
    else if (sp === 'orda') setInvOpen(true)
    else if (sp === 'notif') setNotifOpen(true)
  }, [])

  // Орда собирается → панель «В строй» всплывает ВСЕМ (один раз на нашествие,
  // если ещё не записан) — чтобы не искать её на карте.
  useEffect(() => {
    let cancel = false
    api<{ active?: boolean; id?: number; registered?: boolean }>('invasion/state', {})
      .then((r) => {
        if (cancel || !r.active || r.registered) return
        if (String(r.id) !== localStorage.getItem('orda-seen')) {
          localStorage.setItem('orda-seen', String(r.id)); setInvOpen(true)
        }
      }).catch(() => { /* нет орды — тихо */ })
    return () => { cancel = true }
  }, [])

  // вернулись в приложение — тихо обновляем состояние (таймеры/доход не висят устаревшими)
  useEffect(() => {
    const onVis = () => { if (document.visibilityState === 'visible' && !sheet) reload() }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [reload, sheet])

  // внезапный визитёр объявился — авто-показ один раз (повторно — через карточку «Сейчас»)
  useEffect(() => {
    const sid = data?.story?.id
    if (sid && storySeen.current !== sid) { storySeen.current = sid; setStoryOpen(true) }
  }, [data?.story?.id])

  // заезжий купец висит (не дорешали) — поднять торг; закрыли вручную — не нудить, пока не уйдёт
  useEffect(() => {
    const off = data?.trade
    if (off && !trade && !tradeShut.current) setTrade(off)
    if (!off) tradeShut.current = false
  }, [data?.trade, trade])

  // ещё нет таверны — стартовый экран (создание игрока + таверны)
  if (error === 'no_tavern' && !created)
    return <Onboarding onCreated={(st) => { set(st as TavernState); setCreated(true) }} />
  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  // в проде сбой загрузки (auth/timeout/сеть/пустой initData) — честная ошибка, НЕ
  // показываем демо-таверну: иначе игрок видел бы чужую «Кривую Кружку» вместо своей.
  if (error && error !== 'no_tavern' && !import.meta.env.DEV) return (
    <div className="center" style={{ flex: 1, flexDirection: 'column', gap: 14, padding: 26, textAlign: 'center' }}>
      <div className="muted" style={{ fontStyle: 'italic' }}>
        {error === 'auth' ? 'Сессия устарела — закрой и открой приложение заново.' : 'Не удалось загрузить таверну.'}
      </div>
      <button className="btn gold" style={{ maxWidth: 220 }} onClick={() => reload()}>Повторить</button>
    </div>
  )
  const t = data ?? SAMPLE

  async function collect() {
    if (busy || t.income_ready <= 0) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ collected: number; state: TavernState; retail?: boolean; trade?: TradeData | null }>('collect')
      set(r.state); hapticNotify('success')
      flash(r.collected > 0 ? `+${fmt(r.collected)} 🪙 в казну` : 'Касса пуста')
      if (r.retail) setTimeout(() => setSheet('retail'), 350)        // гости ждут заказ — панель сбыта
      else if (r.trade) setTimeout(() => { tradeShut.current = false; setTrade(r.trade!) }, 350)  // заглянул купец
    } catch { flash('Касса не открылась — попробуй ещё') }
    finally { setBusy(false) }
  }
  function openSheet(a: Activity) {
    if (!a.action) return
    haptic('light')
    if (a.action === 'story') { setStoryOpen(true); return }
    setSheet(a.action)
  }

  return (
    <>
      <Ticker items={t.world} />

      <div className="hero rise">
        <MusicToggle />
        <button className="nf-bell" data-tut="notif" aria-label="Уведомления"
          onClick={() => { haptic('light'); setNotifOpen(true) }}>
          🔔{(t.notif_unread ?? 0) > 0 &&
            <span className="nf-badge">{(t.notif_unread ?? 0) > 99 ? '99+' : t.notif_unread}</span>}
        </button>
        <div className="nm">{t.name}</div>
        <div className="meta">
          <span className="lvl">★ УРОВЕНЬ {t.level}</span>
          <span className="region">📍 {t.region}</span>
          <span className="region">⭐ {t.reputation} репутации</span>
        </div>
        <div className="orn"><b>✦</b></div>
        <div className="flavor">«{t.flavor}»</div>
      </div>

      {/* мировое событие — компактный баннер с нативным анимированным эмодзи */}
      {t.world_event && (
        <div className="we-banner rise" style={{ animationDelay: '.02s' }} title={t.world_event.blurb}>
          <div className="we-emo"><AnimEmoji id={t.world_event.id} fallback={t.world_event.emoji} size={40} /></div>
          <div className="we-body">
            <div className="we-name">{t.world_event.name}</div>
            {t.world_event.effects.length > 0 && (
              <div className="we-effs">
                {t.world_event.effects.map((e, i) => (
                  <span key={i} className={`we-eff ${e.good ? 'pos' : 'neg'}`}>{e.text}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* рейд-босс — срочный CTA (виден, только пока тварь жива) */}
      {t.raid && (t.raid.status === 'gathering' || t.raid.status === 'active') && (
        <button className={`raid-cta rise ${t.raid.status}`} style={{ animationDelay: '.03s' }}
          onClick={() => { haptic('medium'); setRaidOpen(true) }}>
          <span className="raid-cta-emo">{t.raid.emoji}</span>
          <span className="raid-cta-body">
            <b>⚔️ {t.raid.name}</b>
            <small>
              {t.raid.status === 'gathering'
                ? `Сбор войска · в строю ${t.raid.n}${t.raid.me_registered ? ' · ты в строю' : ''}`
                : `БИТВА! осталось ${t.raid.hp_pct ?? 0}% HP${(t.raid.phase ?? 1) >= 3 ? ' · 🔥 бешенство' : (t.raid.phase ?? 1) === 2 ? ' · 🔥 разъярён' : ''}`}
            </small>
          </span>
          <span className="raid-cta-go">{t.raid.status === 'active' ? 'В БОЙ' : t.raid.me_registered ? 'ОТКРЫТЬ' : 'В СТРОЙ'} ›</span>
        </button>
      )}

      {/* админ: призвать босса (видно, только когда живого рейда нет) */}
      {t.admin && !(t.raid && (t.raid.status === 'gathering' || t.raid.status === 'active')) && (
        <button className="raid-cta rise summon" style={{ animationDelay: '.03s' }}
          onClick={() => { haptic('medium'); setRaidOpen(true) }}>
          <span className="raid-cta-emo">⚔️</span>
          <span className="raid-cta-body"><b>Призвать рейд-босса</b><small>админ · сбор 20 мин + анонс в чаты и ЛС</small></span>
          <span className="raid-cta-go">ПРИЗВАТЬ ›</span>
        </button>
      )}

      {/* доход */}
      <div className="card rise" style={{ animationDelay: '.04s' }}>
        <div className="card-h"><span className="he">💰</span>ДОХОД<span className="cnt">+{t.income_rate}/ч</span></div>
        <div className="card-b">
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, fontFamily: 'var(--num)' }}>
            <ResIcon k="gold" size={28} />
            <span style={{ fontSize: 24, fontWeight: 700, color: 'var(--gold-2)', fontVariantNumeric: 'tabular-nums' }}>{fmt(t.gold)}</span>
            <span className="muted" style={{ fontFamily: 'var(--text)', fontSize: 14 }}>в мошне</span>
          </div>
          <button className="btn gold" data-tut="collect" disabled={busy || t.income_ready <= 0} onClick={collect}>
            {t.income_ready > 0 ? `Собрать выручку  +${fmt(t.income_ready)} 🪙` : 'Касса пуста — гости копят жажду'}
          </button>
        </div>
      </div>

      {/* сейчас */}
      <div className="card rise" style={{ animationDelay: '.08s' }}>
        <div className="card-h"><span className="he">⚡</span>СЕЙЧАС</div>
        <div className="card-b">{t.now.map((a, i) => <ActivityRow key={i} a={a} onAct={openSheet} />)}</div>
      </div>

      {/* город: настроение + фракции + ситуация */}
      {t.city && (
        <div className="card rise" style={{ animationDelay: '.1s' }}>
          <div className="card-h" data-tut="city"><span className="he">🏛</span>ГОРОД<span className="cnt">{t.city.mood_label}</span></div>
          <div className="card-b">
            {t.city.situation && (
              <div className="city-sit">{t.city.situation.emoji} <b>{t.city.situation.label}</b> — в самом разгаре</div>
            )}
            {t.city.factions.length > 0 ? (
              <div className="city-facs">
                {t.city.factions.map((f) => (
                  <div key={f.id} className="city-fac">
                    <span className="cf-name">{f.name}</span>
                    <span className="cf-bar"><i className={f.power >= 0 ? 'up' : 'dn'} style={{ width: `${Math.min(100, Math.abs(f.power))}%` }} /></span>
                    <span className="cf-val">{f.power > 0 ? '+' : ''}{f.power}</span>
                  </div>
                ))}
              </div>
            ) : <div className="muted" style={{ fontStyle: 'italic', fontFamily: 'var(--text)' }}>Тишь да гладь — фракции дремлют. Пока.</div>}
            {t.fgoal && <FGoalBanner g={t.fgoal} />}
            <button className="chron-open" onClick={() => { haptic('light'); setChronOpen(true) }}>📜 Летопись города →</button>
            <button className="chron-open" onClick={() => { haptic('light'); setRatingOpen(true) }}>🏆 Топ таверн →</button>
          {t.admin && <button className="chron-open" onClick={() => { haptic('light'); setWonderOpen(true) }}>🏛 Стройка города → <span style={{ opacity: .6, fontSize: 11 }}>(обкатка, только тебе)</span></button>}
          </div>
        </div>
      )}

      {/* зазывала (рефералка) — компактный вход */}
      <button className="zz-cta rise" style={{ animationDelay: '.11s' }} onClick={() => { haptic('light'); setRefOpen(true) }}>
        <span className="zz-cta-emo">🍻</span>
        <span className="zz-cta-body">
          <b>Зазывала</b>
          <small>Зови друзей — золото и репутация обоим</small>
        </span>
        <span className="zz-cta-chev">›</span>
      </button>

      {/* обучение — та же форма, меньше и синяя */}
      <button className="zz-cta gd rise" style={{ animationDelay: '.115s' }} onClick={() => { haptic('light'); setGuideOpen(true) }}>
        <span className="zz-cta-emo">📖</span>
        <span className="zz-cta-body">
          <b>Как играть</b>
          <small>обучение и справочник</small>
        </span>
        <span className="zz-cta-chev">›</span>
      </button>

      {/* заведение */}
      <div className="card rise" style={{ animationDelay: '.12s' }}>
        <div className="card-h"><span className="he">🏰</span>ЗАВЕДЕНИЕ</div>
        <div className="grid2">
          <Tile icon="👥" v={t.capacity} l="Места" />
          <Tile icon="✨" v={t.comfort} l="Уют" />
          <Tile img="stat/luck.png" v={`${t.luck_pct}%`} l="Удача" />
          <Tile img="stat/gear.png" v={`${t.gear_worn}/${t.gear_slots}`} l="Снаряга" />
        </div>
      </div>

      {/* склад */}
      <div className="card rise" style={{ animationDelay: '.16s' }}>
        <div className="card-h"><span className="he">📦</span>СКЛАД</div>
        {t.storage.length
          ? <div className="grid2">{t.storage.map((r) => <ResCell key={r.key} r={r} />)}</div>
          : <div className="card-b"><span className="muted" style={{ fontStyle: 'italic' }}>Склад пуст — гони бригады за добром</span></div>}
      </div>

      {/* погреб */}
      <div className="card rise" style={{ animationDelay: '.2s' }}>
        <div className="card-h"><span className="he">🛢</span>ПОГРЕБ
          <span className="cnt">{t.cellar.reduce((s, p) => s + p.qty, 0)} порций</span></div>
        <div className="chips">
          {t.cellar.length
            ? t.cellar.map((p, i) => (
                <span key={i} className="chip"><GoodIcon k={p.key} /> {p.name} <b style={{ fontFamily: 'var(--num)' }}>×{p.qty}</b></span>
              ))
            : <span className="muted" style={{ fontStyle: 'italic', padding: '2px 0' }}>Пусто — гони товар на продажу</span>}
        </div>
      </div>

      {/* перестройка */}
      {!t.maxed && t.next_upgrade && (
        <div className="card rise" style={{ animationDelay: '.24s' }}>
          <div className="card-h"><span className="he">🔨</span>ПЕРЕСТРОЙКА
            {t.upgrade_pct != null && <span className="cnt">{t.upgrade_pct}%</span>}</div>
          <div className="card-b">
            <div className="grid2" style={{ padding: 0 }}>
              {Object.entries(t.next_upgrade).map(([k, v]) => (
                <CostTile key={k} k={k} need={v} have={k === 'gold' ? t.gold : (t.storage.find((s) => s.key === k)?.amount ?? 0)} />
              ))}
            </div>
            <button className="btn" disabled={busy} onClick={() => { haptic('light'); setSheet('upgrade') }}>⬆ Улучшить до уровня {t.level + 1}</button>
          </div>
        </div>
      )}

      {sheet && <ActionSheet kind={sheet} initial={panelCache.current[sheet]}
        onCache={(k, d) => { panelCache.current[k] = d }}
        onState={(s) => set(s as TavernState)} onClose={() => setSheet(null)} flash={flash} />}
      <Suspense fallback={null}>
        {storyOpen && t.story && (
          <StoryVisitor story={t.story}
            onResolved={(s) => { if (s) set(s as TavernState); setStoryOpen(false); reload() }}
            onClose={() => setStoryOpen(false)} />
        )}
        {trade && (
          <TradeSheet offer={trade}
            onState={(s) => set(s as TavernState)}
            onClose={() => { tradeShut.current = true; setTrade(null) }} />
        )}
        {chronOpen && <ChronicleSheet onClose={() => setChronOpen(false)} />}
        {guideOpen && <GuideSheet onClose={() => setGuideOpen(false)} />}
        {ratingOpen && <RatingSheet onClose={() => setRatingOpen(false)} />}
        {wonderOpen && <WonderSheet onClose={() => { setWonderOpen(false); reload() }}
          onOpenArtel={() => { setWonderOpen(false); setArtelOpen(true) }} />}
        {artelOpen && <ArtelSheet onClose={() => setArtelOpen(false)} />}
        {refOpen && <ReferralSheet onClose={() => setRefOpen(false)} />}
        {raidOpen && <RaidSheet onClose={() => { setRaidOpen(false); reload() }} onGold={() => reload()} />}
        {invOpen && <InvasionSheet onClose={() => { setInvOpen(false); reload() }} />}
        {notifOpen && <NotificationsSheet admin={t.admin} onClose={() => { setNotifOpen(false); reload() }} />}
      </Suspense>
      {toast && <div className="toast">{toast}</div>}
    </>
  )
}

function Ticker({ items }: { items: string[] }) {
  const seq = items.length ? [...items, ...items] : ['Тишь да гладь в Недоливске…']
  return (
    <div className="ticker">
      <div className="lbl">📜 ВЕСТИ</div>
      <div className="vp"><div className="ticker-track">
        {seq.map((w, i) => <span className="it" key={i}>{w}</span>)}
      </div></div>
    </div>
  )
}

const ACT_ICON: Record<string, string> = {
  '⛏': 'pickaxe', '🔨': 'hammer', '🏗': 'hammer',
  '🎁': 'bonus', '📜': 'scroll', '🏭': 'forge', '🍺': 'beer',
}

function ActivityRow({ a, onAct }: { a: Activity; onAct: (a: Activity) => void }) {
  const img = a.icon ? ACT_ICON[a.icon] : undefined
  const go = !!a.action
  return (
    <div className={`act${go ? ' act-go' : ''}`}
      onClick={go ? () => onAct(a) : undefined} role={go ? 'button' : undefined}>
      <div className="top">
        {img
          ? <img className="ai-img" src={`${import.meta.env.BASE_URL}act/${img}.png`} alt="" loading="lazy" />
          : a.icon && <span className="ai">{a.icon}</span>}
        <span className="txt">{a.text}{a.sub && <small>{a.sub}</small>}</span>
        {a.badge && <span className={`badge ${a.badge}`}>{a.badge === 'ready' ? 'ГОТОВО' : 'ждём'}</span>}
        <span className="act-chev" aria-hidden>{go ? '›' : ''}</span>
      </div>
      {a.progress != null && <div className={`bar${a.gold ? ' g' : ''}`}><i style={{ width: `${Math.round(a.progress * 100)}%` }} /></div>}
    </div>
  )
}

function Tile({ icon, img, v, l }: { icon?: string; img?: string; v: string | number; l: string }) {
  return (
    <div className="tile">
      {img
        ? <img className="ti-img" src={`${import.meta.env.BASE_URL}${img}`} alt="" loading="lazy" />
        : <span className="ti">{icon}</span>}
      <div><div className="tv">{v}</div><div className="tl">{l}</div></div>
    </div>
  )
}

function ResCell({ r }: { r: ResLine }) {
  return (
    <div className="tile" style={{ padding: '8px 10px' }}>
      <ResIcon k={r.key} />
      <div><div className="tv" style={{ fontSize: 15 }}>{fmt(r.amount)}</div><div className="tl">{r.name}</div></div>
    </div>
  )
}

function CostTile({ k, need, have }: { k: string; need: number; have: number }) {
  const NAME: Record<string, string> = { gold: 'Золото', wood: 'Дерево', grain: 'Зерно', hops: 'Хмель', stone: 'Камень', ore: 'Руда', clay: 'Глина', ingot: 'Слиток' }
  const ok = have >= need
  return (
    <div className="tile" style={{ padding: '8px 10px' }}>
      <ResIcon k={k} />
      <div>
        <div className="tv" style={{ fontSize: 14, color: ok ? 'var(--green)' : 'var(--crimson)' }}>{fmt(have)}/{fmt(need)}</div>
        <div className="tl">{NAME[k] ?? k}</div>
      </div>
    </div>
  )
}

// ЦЕЛЬ НЕДЕЛИ — ультрасовременный квест-баннер: кольцо-прогресс вокруг эмблемы
// (conic), аврора фракционного цвета, угольки, вехи 25/50/75, докрутка счётчика.
function FGoalBanner({ g }: { g: NonNullable<TavernState['fgoal']> }) {
  const [num, setNum] = useState(0)
  useEffect(() => {
    let raf = 0
    const t0 = performance.now()
    const to = g.done
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / 900)
      setNum(Math.round(to * (1 - Math.pow(1 - k, 3))))
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [g.done])
  const pct = Math.max(g.pct, 2)
  return (
    <div className={`fgoal f-${g.fac}${g.feast ? ' feast' : ''}`}
      style={{ ['--p' as string]: `${pct}%` } as React.CSSProperties}>
      <div className="fg-aura" aria-hidden />
      <div className="fg-embers" aria-hidden><i /><i /><i /></div>
      <div className="fg-head">
        <span className="fg-badge">Цель недели</span>
        <span className="fg-reward">🍺 сутки пира · сбыт +15%</span>
      </div>
      <div className="fg-main">
        <span className="fg-ring"><b className="fg-emblem">{g.emblem || '⚜️'}</b></span>
        <div className="fg-tx">
          <b className="fg-title">{g.feast ? 'Город гуляет!' : (g.title || 'Цель недели')}</b>
          <span className="fg-task">{g.feast ? 'Цель взята — сутки сбыт гостям +15%. Наливай!' : g.task}</span>
        </div>
        <span className="fg-pct">{g.pct}<small>%</small></span>
      </div>
      <div className="fg-bar">
        <s className="fg-mk" style={{ left: '25%' }} /><s className="fg-mk" style={{ left: '50%' }} /><s className="fg-mk" style={{ left: '75%' }} />
        <i style={{ width: `${pct}%` }} />
      </div>
      <div className="fg-foot">
        <span className="fg-cnt">{num.toLocaleString('ru-RU')} <em>/ {g.target.toLocaleString('ru-RU')}</em></span>
        <span className="fg-live">город копит</span>
      </div>
    </div>
  )
}
