import { useApi } from '../hooks'
import { haptic } from '../telegram'

interface Activity { icon: string; text: string; sub?: string; badge?: 'ready' | 'wait'; progress?: number; gold?: boolean }
interface ResLine { key: string; emoji: string; name: string; have: number; cap: number }
interface TavernState {
  ok: boolean
  name: string; level: number; region: string; flavor: string
  gold: number; income_rate: number; income_ready: number; reputation: number
  capacity: number; comfort: number; luck_pct: number; gear_worn: number; gear_slots: number
  now: Activity[]
  storage: ResLine[]; cellar: { emoji: string; name: string; qty: number }[]
  world: string[]
  next_upgrade?: Record<string, number>; upgrade_pct?: number | null; maxed?: boolean
}

// образец (вся инфа из текстового бота) — для оффлайн-превью; ждёт /api/state
const SAMPLE: TavernState = {
  ok: true, name: 'Кривая Кружка', level: 2, region: 'Северная глушь',
  flavor: 'Свечи оплыли, эль выдохся, но гости всё прут — знать, иначе некуда.',
  gold: 1340, income_rate: 18, income_ready: 126, reputation: 27,
  capacity: 24, comfort: 12, luck_pct: 8, gear_worn: 1, gear_slots: 11,
  now: [
    { icon: '⛏', text: 'Бригады в пути: 1 из 2', sub: 'Возврат через 14 мин', progress: 0.55 },
    { icon: '🏭', text: 'Пивоварня — варит эль', sub: 'Готово через 38 мин', progress: 0.3 },
    { icon: '🎁', text: 'Бонус дня готов', sub: 'Забери и активируй', badge: 'ready' },
    { icon: '🔨', text: 'Перестройка до ур. 3', sub: '60% — нужно ещё сырья', progress: 0.6, gold: true },
  ],
  storage: [
    { key: 'wood', emoji: '🪵', name: 'Дерево', have: 60, cap: 200 },
    { key: 'grain', emoji: '🌾', name: 'Зерно', have: 80, cap: 200 },
    { key: 'hops', emoji: '🌿', name: 'Хмель', have: 45, cap: 200 },
    { key: 'ingot', emoji: '🔩', name: 'Слиток', have: 6, cap: 50 },
  ],
  cellar: [
    { emoji: '🍺', name: 'Эль', qty: 12 },
    { emoji: '🍖', name: 'Жаркое', qty: 4 },
    { emoji: '🥧', name: 'Пирог', qty: 3 },
  ],
  world: [
    '🍂 Осень — спрос на горячее растёт',
    '🎪 Ярмарка ещё 2 ч — сбывай товар',
    '🌧 Ливень в долинах — вылазки медленнее',
    '🪓 Орда орков точит топоры на севере',
    '📈 Цены на хмель подскочили',
    '🐀 В подвалах кого-то завелось…',
  ],
  next_upgrade: { gold: 715, wood: 220, grain: 180, hops: 120 },
  upgrade_pct: 60,
}

export default function Tavern() {
  const { data, loading } = useApi<TavernState>('state', SAMPLE)
  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  const t = data ?? SAMPLE

  return (
    <>
      {/* ── бегущая строка вестей мира ── */}
      <Ticker items={t.world} />

      {/* ── идентичность ── */}
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

      {/* ── доход (главный CTA) ── */}
      <div className="card rise" style={{ animationDelay: '.04s' }}>
        <div className="card-h"><span className="he">💰</span>ДОХОД<span className="cnt">+{t.income_rate}/ч</span></div>
        <div className="card-b">
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, fontFamily: 'var(--num)' }}>
            <ResIcon k="gold" size={28} />
            <span style={{ fontSize: 24, fontWeight: 700, color: 'var(--gold-2)', fontVariantNumeric: 'tabular-nums' }}>{fmt(t.gold)}</span>
            <span className="muted" style={{ fontFamily: 'var(--text)', fontSize: 14 }}>в мошне</span>
          </div>
          <button className="btn gold" disabled={t.income_ready <= 0} onClick={() => haptic('medium')}>
            {t.income_ready > 0 ? `Собрать выручку  +${fmt(t.income_ready)} 🪙` : 'Касса пуста — гости копят жажду'}
          </button>
        </div>
      </div>

      {/* ── СЕЙЧАС ── */}
      <div className="card rise" style={{ animationDelay: '.08s' }}>
        <div className="card-h"><span className="he">⚡</span>СЕЙЧАС</div>
        <div className="card-b">
          {t.now.map((a, i) => <ActivityRow key={i} a={a} />)}
        </div>
      </div>

      {/* ── заведение (стат-сетка) ── */}
      <div className="card rise" style={{ animationDelay: '.12s' }}>
        <div className="card-h"><span className="he">🏰</span>ЗАВЕДЕНИЕ</div>
        <div className="grid2">
          <Tile icon="👥" v={t.capacity} l="Места" />
          <Tile icon="✨" v={t.comfort} l="Уют" />
          <Tile icon="🍀" v={`${t.luck_pct}%`} l="Удача" />
          <Tile icon="🎒" v={`${t.gear_worn}/${t.gear_slots}`} l="Снаряга" />
        </div>
      </div>

      {/* ── склад ── */}
      <div className="card rise" style={{ animationDelay: '.16s' }}>
        <div className="card-h"><span className="he">📦</span>СКЛАД</div>
        <div className="card-b">
          {t.storage.map((r) => <ResBar key={r.key} r={r} />)}
        </div>
      </div>

      {/* ── погреб ── */}
      <div className="card rise" style={{ animationDelay: '.2s' }}>
        <div className="card-h"><span className="he">🛢</span>ПОГРЕБ
          <span className="cnt">{t.cellar.reduce((s, p) => s + p.qty, 0)} порций</span></div>
        <div className="chips">
          {t.cellar.length
            ? t.cellar.map((p, i) => (
                <span key={i} className="chip">{p.emoji} {p.name} <b style={{ fontFamily: 'var(--num)' }}>×{p.qty}</b></span>
              ))
            : <span className="muted" style={{ fontStyle: 'italic', padding: '2px 0' }}>Пусто — гони товар на продажу</span>}
        </div>
      </div>

      {/* ── улучшить ── */}
      {!t.maxed && t.next_upgrade && (
        <div className="card rise" style={{ animationDelay: '.24s' }}>
          <div className="card-h"><span className="he">🔨</span>ПЕРЕСТРОЙКА
            {t.upgrade_pct != null && <span className="cnt">{t.upgrade_pct}%</span>}</div>
          <div className="card-b">
            <div className="grid2" style={{ padding: 0 }}>
              {Object.entries(t.next_upgrade).map(([k, v]) => (
                <CostTile key={k} k={k} need={v} have={k === 'gold' ? t.gold : (t.storage.find((s) => s.key === k)?.have ?? 0)} />
              ))}
            </div>
            <button className="btn" onClick={() => haptic('medium')}>⬆ Улучшить до уровня {t.level + 1}</button>
          </div>
        </div>
      )}

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
        <span className="ai">{a.icon}</span>
        <span className="txt">{a.text}{a.sub && <small>{a.sub}</small>}</span>
        {a.badge && <span className={`badge ${a.badge}`}>{a.badge === 'ready' ? 'ГОТОВО' : 'ждём'}</span>}
      </div>
      {a.progress != null && <div className={`bar${a.gold ? ' g' : ''}`}><i style={{ width: `${Math.round(a.progress * 100)}%` }} /></div>}
    </div>
  )
}

function Tile({ icon, v, l }: { icon: string; v: string | number; l: string }) {
  return (
    <div className="tile">
      <span className="ti">{icon}</span>
      <div><div className="tv">{v}</div><div className="tl">{l}</div></div>
    </div>
  )
}

function ResBar({ r }: { r: ResLine }) {
  const pct = Math.min(100, Math.round((r.have / (r.cap || 1)) * 100))
  const full = r.have >= r.cap
  return (
    <div className="res">
      <div className={`top${full ? ' full' : ''}`}>
        <ResIcon k={r.key} emoji={r.emoji} />
        <span className="rn">{r.name}</span>
        <span className="rv">{r.have}<span className="cap"> / {r.cap}</span></span>
      </div>
      <div className="bar g"><i style={{ width: `${pct}%`, background: full ? 'linear-gradient(90deg,#b3331f,#cf4a36)' : undefined }} /></div>
    </div>
  )
}

function CostTile({ k, need, have }: { k: string; need: number; have: number }) {
  const META: Record<string, [string, string]> = {
    gold: ['🪙', 'Золото'], wood: ['🪵', 'Дерево'], grain: ['🌾', 'Зерно'],
    hops: ['🌿', 'Хмель'], stone: ['🪨', 'Камень'], ore: ['⛏', 'Руда'], ingot: ['🔩', 'Слиток'],
  }
  const [e, n] = META[k] ?? ['•', k]
  const ok = have >= need
  return (
    <div className="tile" style={{ padding: '8px 10px' }}>
      <ResIcon k={k} emoji={e} />
      <div>
        <div className="tv" style={{ fontSize: 14, color: ok ? 'var(--green)' : 'var(--crimson)' }}>{have}/{need}</div>
        <div className="tl">{n}</div>
      </div>
    </div>
  )
}

// Иконки ресурсов лежат в miniapp/public/res/<ключ>.png (CraftPix-набор).
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

const fmt = (n: number) => (n >= 10000 ? `${(n / 1000).toFixed(1)}к` : `${n}`)
