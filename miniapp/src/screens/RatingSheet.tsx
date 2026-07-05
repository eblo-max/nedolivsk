import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { haptic } from '../telegram'

type MetricKey = 'gdp' | 'rep' | 'level'
interface Row { place: number; name: string; id?: number; ava?: string; owner: string; level: number; loc: string; gdp: number; rep: number; cap?: number; comfort?: number; builds?: number; mine: boolean; trend?: number | null; atitle?: { emoji: string; short: string } | null }

/** Артель-звание зодчего у имени (за вклад в чудеса города). */
function ATitle({ a }: { a?: { emoji: string; short: string } | null }) {
  if (!a) return null
  return <span className="lb-atitle" title="Звание за вклад в чудеса города">{a.emoji} {a.short}</span>
}
interface Board { rows: Row[]; me: Row | null }
interface Rating { boards: Record<MetricKey, Board>; total_gdp: number; total: number }

const TITLES: Record<MetricKey, string> = { gdp: '👑 Богатейший кабак', rep: '⭐ Самый славный', level: '🏰 Высочайший кабак' }

const fmt = (n: number) => n.toLocaleString('ru-RU').replace(/,/g, ' ')
const initial = (s: string) => (s.trim()[0] || '?').toUpperCase()

const METRICS: { key: MetricKey; label: string; icon: string; val: (r: Row) => number; fmt: (n: number) => string }[] = [
  { key: 'gdp', label: 'ВВП', icon: '💰', val: (r) => r.gdp, fmt },
  { key: 'rep', label: 'Слава', icon: '⭐', val: (r) => r.rep, fmt },
  { key: 'level', label: 'Уровень', icon: '🏰', val: (r) => r.level, fmt: (n) => `ур. ${n}` },
]

/** Тренд места в реальном времени: ▲N поднялся, ▼N опустился, = на месте, новичок/нет базы — пусто. */
function Trend({ t }: { t?: number | null }) {
  if (t == null) return null
  if (t === 0) return <span className="lb-trend same">=</span>
  const up = t > 0
  return <span className={`lb-trend ${up ? 'up' : 'down'}`}>{up ? '▲' : '▼'}{Math.abs(t)}</span>
}

/** Аватар игрока: фото из ТГ-профиля по подписанной ссылке (/avatar/<uid>.<sig>),
 *  при ошибке/без фото — инициал. */
function Avatar({ ava, name, rank, sm }: { ava?: string; name: string; rank: number; sm?: boolean }) {
  const [bad, setBad] = useState(false)
  return (
    <div className={`lb-ava${sm ? ' sm' : ''}`} data-r={rank}>
      {ava && !bad
        ? <img className="lb-ava-img" src={`/avatar/${ava}`} alt="" loading="lazy" onError={() => setBad(true)} />
        : initial(name)}
    </div>
  )
}

/** Мини-профиль таверны: титулы лидера, статы, места во всех трёх досках. */
function TavernProfile({ r, boards, onClose }: { r: Row; boards: Record<MetricKey, Board>; onClose: () => void }) {
  const placeIn = (k: MetricKey): string => {
    const b = boards[k]
    const hit = b.rows.find((x) => x.id === r.id) || (b.me?.id === r.id ? b.me : null)
    return hit ? `#${hit.place}` : '50+'
  }
  const titles = (Object.keys(TITLES) as MetricKey[]).filter((k) => boards[k].rows[0]?.id === r.id)
  return (
    <div className="tp-backdrop" onClick={(e) => { e.stopPropagation(); onClose() }}>
      <div className="tp-card" onClick={(e) => e.stopPropagation()}>
        <Avatar ava={r.ava} name={r.name} rank={titles.length ? 1 : 99} />
        <div className="tp-name">{r.name}{r.mine && <span className="lb-you">ты</span>}</div>
        {r.atitle && <div className="tp-atitle">{r.atitle.emoji} {r.atitle.short}</div>}
        <div className="tp-owner">хозяин: {r.owner} · 📍 {r.loc}</div>
        {titles.length > 0 && (
          <div className="tp-titles">{titles.map((k) => <div key={k} className="tp-title">{TITLES[k]}</div>)}</div>
        )}
        <div className="tp-grid">
          <span>⚜️ ур. {r.level}</span><span>⭐ {r.rep}</span>
          {r.cap != null && <span>👥 {r.cap}</span>}
          {r.comfort != null && <span>☕ {r.comfort}</span>}
          {r.builds != null && <span>🏛 {r.builds}</span>}
          <span>💰 {fmt(r.gdp)}</span>
        </div>
        <div className="tp-places">
          {METRICS.map((x) => (
            <div key={x.key} className="tp-place"><i>{x.icon} {x.label}</i><b>{placeIn(x.key)}</b></div>
          ))}
        </div>
        <button className="btn gold" style={{ marginTop: 12, width: '100%' }}
          onClick={() => { haptic('light'); onClose() }}>← Назад к доске</button>
      </div>
    </div>
  )
}

// Демо ТОЛЬКО в dev-превью (import.meta.env.DEV). В прод-сборке вырезается.
const DEV = import.meta.env.DEV
const DEMO_ROWS: Omit<Row, 'place' | 'mine'>[] = [
  { name: 'Кривая Кружка', id: 1, owner: 'Барон', level: 7, loc: 'Изумрудная Чарка', gdp: 1340, rep: 27, cap: 26, comfort: 14, builds: 6, atitle: { emoji: '🏛', short: 'Столп общины' } },
  { name: 'Пьяный Гусь', id: 2, owner: 'Прохор', level: 6, loc: 'Зелёный Змий', gdp: 1180, rep: 31, cap: 22, comfort: 11, builds: 5, atitle: { emoji: '🔨', short: 'Зодчий' } },
  { name: 'Косая Бочка', id: 3, owner: 'Фёкла', level: 6, loc: 'Сухой Закон', gdp: 1020, rep: 18 },
  { name: 'Тёплый Подвал', id: 4, owner: 'Гаврила', level: 5, loc: 'Рассольник', gdp: 880, rep: 22 },
  { name: 'Сухое Горло', id: 5, owner: 'Тихон', level: 5, loc: 'Похмельные Дюны', gdp: 760, rep: 12, atitle: { emoji: '🧱', short: 'Каменщик' } },
  { name: 'Бычий Глаз', id: 6, owner: 'Марфа', level: 4, loc: 'Чекушкины Холмы', gdp: 640, rep: 15 },
  { name: 'Хмельной Кот', id: 7, owner: 'Степан', level: 4, loc: 'Бражные Поля', gdp: 520, rep: 9 },
  { name: 'Дно Бутылки', id: 8, owner: 'Аграфена', level: 3, loc: 'Старый Запой', gdp: 410, rep: 7 },
]
const DEMO_TREND = [1, -1, 0, 2, -2, 1, 0, -1]   // демо-стрелки для превью
function demoBoard(key: MetricKey): Board {
  const ranked = [...DEMO_ROWS].sort((a, b) => (b[key] as number) - (a[key] as number) || a.name.localeCompare(b.name))
  return { rows: ranked.map((e, i) => ({ ...e, place: i + 1, mine: e.id === 1, trend: DEMO_TREND[i] ?? 0 })), me: null }
}
const DEMO: Rating = {
  total: 11, total_gdp: 9740,
  boards: { gdp: demoBoard('gdp'), rep: demoBoard('rep'), level: demoBoard('level') },
}
/** Скелетон доски на время загрузки: контур подиума + строки с шиммером. */
function Skeleton() {
  return (
    <div className="lb-scroll" aria-hidden>
      <div className="lb-podium">
        {[44, 56, 44].map((s, i) => (
          <div key={i} className="lb-pod">
            <div className="skel skel-circle" style={{ width: s, height: s }} />
            <div className="skel skel-line" style={{ width: 64, marginTop: 8 }} />
          </div>
        ))}
      </div>
      <div className="lb-list">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="lb-row" style={{ pointerEvents: 'none' }}>
            <div className="skel skel-circle" style={{ width: 38, height: 38 }} />
            <div className="lb-info">
              <div className="skel skel-line" style={{ width: `${62 - i * 6}%` }} />
              <div className="skel skel-line" style={{ width: '38%', height: 8, marginTop: 6 }} />
            </div>
            <div className="skel skel-line" style={{ width: 42 }} />
          </div>
        ))}
      </div>
    </div>
  )
}

export default function RatingSheet({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Rating | null>(null)
  const [err, setErr] = useState(false)
  const [metric, setMetric] = useState<MetricKey>('gdp')
  const [profile, setProfile] = useState<Row | null>(null)   // мини-профиль таверны (тап по строке)

  const load = useCallback(() => {
    setErr(false); setData(null)
    api<Rating>('rating').then(setData)
      .catch(() => { if (DEV) setData(DEMO); else setErr(true) })   // прод: честная ошибка + ретрай
  }, [])
  useEffect(load, [load])

  const m = METRICS.find((x) => x.key === metric)!
  const board = data ? data.boards[metric] : null
  const rows = board?.rows ?? []
  const max = rows.length ? m.val(rows[0]) || 1 : 1
  const top3 = rows.slice(0, 3)
  const rest = rows.slice(3)
  const order = [top3[1], top3[0], top3[2]]   // визуально: 2 · 1 · 3
  const meRow = board?.me ?? null

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="chron-sheet lb-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="lb-top">
          <div className="lb-title">🏆 Доска почёта</div>
          <div className="lb-chips">
            <span className="lb-chip">🏰 {data?.total ?? '—'}</span>
            <span className="lb-chip gold">💰 {data ? fmt(data.total_gdp) : '—'}</span>
          </div>
        </div>

        <div className="lb-tabs">
          {METRICS.map((x) => (
            <button key={x.key} className={`lb-tab${x.key === metric ? ' on' : ''}`}
              onClick={() => { haptic('light'); setMetric(x.key) }}>
              <span className="lb-tab-ic">{x.icon}</span>{x.label}
            </button>
          ))}
        </div>

        {err ? (
          <div className="lb-err">
            <p className="chron-empty">«Гонец с доской почёта увяз в грязи — вести не дошли.»</p>
            <button className="btn" onClick={() => { haptic('light'); load() }}>↻ Попробовать ещё раз</button>
          </div>
        ) : data === null ? (
          <Skeleton />
        ) : rows.length === 0 ? (
          <p className="chron-empty">«В Недоливске пока ни одного кабака. Город трезвенников, тоска.»</p>
        ) : (
          <div className="lb-scroll">
            <div className="lb-podium">
              {order.map((r, i) => {
                if (!r) return <div key={i} className="lb-pod ghost" />
                return (
                  <div key={r.id ?? r.name + r.owner} className={`lb-pod r${r.place}${r.mine ? ' mine' : ''}`}
                    onClick={() => { haptic('light'); setProfile(r) }}>
                    {r.place === 1 && <div className="lb-crown">👑</div>}
                    <Avatar ava={r.ava} name={r.name} rank={r.place} />
                    <div className="lb-pname">{r.name}</div>
                    {r.atitle && <div className="lb-patitle">{r.atitle.emoji} {r.atitle.short}</div>}
                    <div className="lb-pval">{m.fmt(m.val(r))}</div>
                    <Trend t={r.trend} />
                    <div className="lb-ped"><span>{r.place}</span></div>
                  </div>
                )
              })}
            </div>

            <div className="lb-list">
              {rest.map((r) => {
                const pct = Math.max(7, Math.round((m.val(r) / max) * 100))
                return (
                  <div key={r.id ?? r.name + r.owner} className={`lb-row${r.mine ? ' mine' : ''}`}
                    style={{ animationDelay: `${Math.min(r.place, 14) * 0.035}s` }}
                    onClick={() => { haptic('light'); setProfile(r) }}>
                    <div className="lb-rank">{r.place}<Trend t={r.trend} /></div>
                    <Avatar ava={r.ava} name={r.name} rank={r.place} sm />
                    <div className="lb-info">
                      <div className="lb-name">{r.name}{r.mine && <span className="lb-you">ты</span>}<ATitle a={r.atitle} /></div>
                      <div className="lb-meta">📍 {r.loc} · {r.owner}</div>
                      <div className="lb-bar"><i style={{ width: `${pct}%` }} /></div>
                    </div>
                    <div className="lb-val">{m.fmt(m.val(r))}</div>
                  </div>
                )
              })}
              {meRow && (
                <>
                  <div className="lb-gap">↓ твоё место ↓</div>
                  <div className="lb-row mine" onClick={() => { haptic('light'); setProfile(meRow) }}>
                    <div className="lb-rank">{meRow.place}<Trend t={meRow.trend} /></div>
                    <Avatar ava={meRow.ava} name={meRow.name} rank={99} sm />
                    <div className="lb-info">
                      <div className="lb-name">{meRow.name}<span className="lb-you">ты</span></div>
                      <div className="lb-meta">📍 {meRow.loc} · {meRow.owner}</div>
                    </div>
                    <div className="lb-val">{m.fmt(m.val(meRow))}</div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
        <button className="btn gold chron-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
        {profile && data && (
          <TavernProfile r={profile} boards={data.boards} onClose={() => setProfile(null)} />
        )}
      </div>
    </div>
  )
}
