import { useState, useRef, useEffect } from 'react'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { ResIcon, GoodIcon, fmt } from '../components/icons'
import Onboarding from './Onboarding'
import ActionSheet from './ActionSheet'

interface Activity { icon?: string; text: string; sub?: string; badge?: 'ready' | 'wait'; progress?: number; gold?: boolean; action?: string }
interface ResLine { key: string; name: string; amount: number }
interface CellarLine { key: string; name: string; qty: number }
interface TavernState {
  ok: boolean
  name: string; level: number; region: string; flavor: string
  gold: number; income_rate: number; income_ready: number; reputation: number
  capacity: number; comfort: number; luck_pct: number; gear_worn: number; gear_slots: number
  now: Activity[]
  storage: ResLine[]; cellar: CellarLine[]
  world: string[]
  next_upgrade?: Record<string, number> | null; upgrade_pct?: number | null; maxed?: boolean
}

// образец для оффлайн-превью (форма 1:1 как у /api/state)
const SAMPLE: TavernState = {
  ok: true, name: 'Кривая Кружка', level: 2, region: 'Северная глушь',
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
}

export default function Tavern() {
  const { data, loading, error, set, reload } = useApi<TavernState>('state', SAMPLE)
  const [toast, setToast] = useState('')
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState(false)
  const [sheet, setSheet] = useState<string | null>(null)
  const panelCache = useRef<Record<string, unknown>>({})
  const toastTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const flash = (m: string) => {
    setToast(m); clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(''), 2200)
  }

  // вернулись в приложение — тихо обновляем состояние (таймеры/доход не висят устаревшими)
  useEffect(() => {
    const onVis = () => { if (document.visibilityState === 'visible' && !sheet) reload() }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [reload, sheet])

  // ещё нет таверны — стартовый экран (создание игрока + таверны)
  if (error === 'no_tavern' && !created)
    return <Onboarding onCreated={(st) => { set(st as TavernState); setCreated(true) }} />
  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  const t = data ?? SAMPLE

  async function collect() {
    if (busy || t.income_ready <= 0) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ collected: number; state: TavernState; retail?: boolean }>('collect')
      set(r.state); hapticNotify('success')
      flash(r.collected > 0 ? `+${fmt(r.collected)} 🪙 в казну` : 'Касса пуста')
      if (r.retail) setTimeout(() => setSheet('retail'), 350)   // гости ждут заказ — панель сбыта
    } catch { flash('Касса не открылась — попробуй ещё') }
    finally { setBusy(false) }
  }
  function openSheet(a: Activity) {
    if (!a.action) return
    haptic('light'); setSheet(a.action)
  }

  return (
    <>
      <Ticker items={t.world} />

      <div className="hero rise">
        <div className="nm">{t.name}</div>
        <div className="meta">
          <span className="lvl">★ УРОВЕНЬ {t.level}</span>
          <span className="region">📍 {t.region}</span>
          <span className="region">⭐ {t.reputation} репутации</span>
        </div>
        <div className="orn"><b>✦</b></div>
        <div className="flavor">«{t.flavor}»</div>
      </div>

      {/* доход */}
      <div className="card rise" style={{ animationDelay: '.04s' }}>
        <div className="card-h"><span className="he">💰</span>ДОХОД<span className="cnt">+{t.income_rate}/ч</span></div>
        <div className="card-b">
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, fontFamily: 'var(--num)' }}>
            <ResIcon k="gold" size={28} />
            <span style={{ fontSize: 24, fontWeight: 700, color: 'var(--gold-2)', fontVariantNumeric: 'tabular-nums' }}>{fmt(t.gold)}</span>
            <span className="muted" style={{ fontFamily: 'var(--text)', fontSize: 14 }}>в мошне</span>
          </div>
          <button className="btn gold" disabled={busy || t.income_ready <= 0} onClick={collect}>
            {t.income_ready > 0 ? `Собрать выручку  +${fmt(t.income_ready)} 🪙` : 'Касса пуста — гости копят жажду'}
          </button>
        </div>
      </div>

      {/* сейчас */}
      <div className="card rise" style={{ animationDelay: '.08s' }}>
        <div className="card-h"><span className="he">⚡</span>СЕЙЧАС</div>
        <div className="card-b">{t.now.map((a, i) => <ActivityRow key={i} a={a} onAct={openSheet} />)}</div>
      </div>

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

