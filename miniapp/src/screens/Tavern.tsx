import { useState } from 'react'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'

interface Activity { icon?: string; text: string; sub?: string; badge?: 'ready' | 'wait'; progress?: number; gold?: boolean }
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
    { icon: '⛏', text: 'Бригады в пути: 1 из 2', sub: 'возврат ~14 мин' },
    { icon: '🏭', text: 'Пристройки: 1 готовы — забирай', badge: 'ready' },
    { icon: '🎁', text: 'Бонус дня готов', sub: 'забери и активируй', badge: 'ready' },
    { icon: '🔨', text: 'Перестройка до ур. 3', sub: '60% — копим ресурсы', progress: 0.6, gold: true },
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
  const { data, loading, set } = useApi<TavernState>('state', SAMPLE)
  const [toast, setToast] = useState('')
  const [busy, setBusy] = useState(false)
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200) }

  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  const t = data ?? SAMPLE

  async function collect() {
    if (busy || t.income_ready <= 0) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ collected: number; state: TavernState }>('collect')
      set(r.state); hapticNotify('success')
      flash(r.collected > 0 ? `+${fmt(r.collected)} 🪙 в казну` : 'Касса пуста')
    } catch { flash('Касса не открылась — попробуй ещё') }
    finally { setBusy(false) }
  }
  async function upgrade() {
    if (busy) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<{ level: number; state: TavernState }>('upgrade')
      set(r.state); hapticNotify('success'); flash(`Таверна выросла до ур. ${r.level}!`)
    } catch (e) {
      hapticNotify('warning')
      const code = (e as { code?: string })?.code
      flash(code === 'not_enough' ? 'Не хватает на перестройку' : code === 'max_level' ? 'Выше строить некуда' : 'Артель не вышла')
    } finally { setBusy(false) }
  }

  return (
    <>
      <Ticker items={t.world} />

      <div className="hero rise">
        <div className="nm">{t.name}</div>
        <div className="meta">
          <span className="lvl">★ УРОВЕНЬ {t.level}</span>
          <span className="region">📍 {t.region}</span>
          <span className="region">⭐ {t.reputation} молвы</span>
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
        <div className="card-b">{t.now.map((a, i) => <ActivityRow key={i} a={a} />)}</div>
      </div>

      {/* заведение */}
      <div className="card rise" style={{ animationDelay: '.12s' }}>
        <div className="card-h"><span className="he">🏰</span>ЗАВЕДЕНИЕ</div>
        <div className="grid2">
          <Tile icon="👥" v={t.capacity} l="Места" />
          <Tile icon="✨" v={t.comfort} l="Уют" />
          <Tile icon="🍀" v={`${t.luck_pct}%`} l="Удача" />
          <Tile icon="🎒" v={`${t.gear_worn}/${t.gear_slots}`} l="Снаряга" />
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
            <button className="btn" disabled={busy} onClick={upgrade}>⬆ Улучшить до уровня {t.level + 1}</button>
          </div>
        </div>
      )}

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

function ActivityRow({ a }: { a: Activity }) {
  return (
    <div className="act">
      <div className="top">
        {a.icon && <span className="ai">{a.icon}</span>}
        <span className="txt">{a.text}{a.sub && <small>{a.sub}</small>}</span>
        {a.badge && <span className={`badge ${a.badge}`}>{a.badge === 'ready' ? 'ГОТОВО' : 'ждём'}</span>}
      </div>
      {a.progress != null && <div className={`bar${a.gold ? ' g' : ''}`}><i style={{ width: `${Math.round(a.progress * 100)}%` }} /></div>}
    </div>
  )
}

function Tile({ icon, v, l }: { icon: string; v: string | number; l: string }) {
  return <div className="tile"><span className="ti">{icon}</span><div><div className="tv">{v}</div><div className="tl">{l}</div></div></div>
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

// иконки ресурсов: miniapp/public/res/<ключ>.png (золото/слиток — тоже иконки)
const RES_HAS = new Set([
  'gold', 'ingot', 'wood', 'grain', 'hops', 'stone', 'ore', 'clay',
  'honey', 'milk', 'berries', 'fish', 'game', 'herbs', 'salt', 'water',
])
function ResIcon({ k, emoji, size }: { k: string; emoji?: string; size?: number }) {
  if (RES_HAS.has(k)) {
    const st = size ? { width: size, height: size } : undefined
    return <img className="ric" style={st} src={`${import.meta.env.BASE_URL}res/${k}.png`} alt="" loading="lazy" />
  }
  return <span className="ric-e">{emoji ?? '•'}</span>
}

// иконки товаров: miniapp/public/goods/<file>.png
const GOOD_ICON: Record<string, string> = {
  ale1: 'ale', ale2: 'ale', ale3: 'ale', mead: 'mead', sbiten: 'sbiten', wine: 'wine',
  roast: 'roast', bread: 'bread', pie: 'pie', cured: 'cured', smoked_fish: 'smoked_fish',
  cheese: 'cheese', butter: 'butter',
}
function GoodIcon({ k }: { k: string }) {
  const f = GOOD_ICON[k]
  if (f) return <img className="ric" src={`${import.meta.env.BASE_URL}goods/${f}.png`} alt="" loading="lazy" />
  return <span className="ric-e">🍽</span>
}

const fmt = (n: number) => (n >= 10000 ? `${(n / 1000).toFixed(1)}к` : `${n}`)
