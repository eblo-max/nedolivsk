import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { haptic } from '../telegram'

interface Row { place: number; name: string; id?: number; owner: string; level: number; loc: string; gdp: number; rep: number; mine: boolean }
interface Rating { rows: Row[]; me: Row | null; total_gdp: number; total: number }

const fmt = (n: number) => n.toLocaleString('ru-RU').replace(/,/g, ' ')
const initial = (s: string) => (s.trim()[0] || '?').toUpperCase()

/** Аватар игрока: фото из ТГ-профиля (/avatar/<id>), при ошибке/без фото — инициал. */
function Avatar({ id, name, rank, sm }: { id?: number; name: string; rank: number; sm?: boolean }) {
  const [bad, setBad] = useState(false)
  return (
    <div className={`lb-ava${sm ? ' sm' : ''}`} data-r={rank}>
      {id && !bad
        ? <img className="lb-ava-img" src={`/avatar/${id}`} alt="" loading="lazy" onError={() => setBad(true)} />
        : initial(name)}
    </div>
  )
}

type MetricKey = 'gdp' | 'rep' | 'level'
const METRICS: { key: MetricKey; label: string; icon: string; val: (r: Row) => number; fmt: (n: number) => string }[] = [
  { key: 'gdp', label: 'ВВП', icon: '💰', val: (r) => r.gdp, fmt },
  { key: 'rep', label: 'Слава', icon: '⭐', val: (r) => r.rep, fmt },
  { key: 'level', label: 'Уровень', icon: '🏰', val: (r) => r.level, fmt: (n) => `ур. ${n}` },
]

// Демо ТОЛЬКО в dev-превью (import.meta.env.DEV). В прод-сборке вырезается.
const DEV = import.meta.env.DEV
const DEMO: Rating = {
  total: 11, total_gdp: 9740, me: null,
  rows: [
    { place: 1, name: 'Кривая Кружка', id: 1, owner: 'Барон', level: 7, loc: 'Изумрудная Чарка', gdp: 1340, rep: 27, mine: true },
    { place: 2, name: 'Пьяный Гусь', id: 2, owner: 'Прохор', level: 6, loc: 'Зелёный Змий', gdp: 1180, rep: 31, mine: false },
    { place: 3, name: 'Косая Бочка', id: 3, owner: 'Фёкла', level: 6, loc: 'Сухой Закон', gdp: 1020, rep: 18, mine: false },
    { place: 4, name: 'Тёплый Подвал', id: 4, owner: 'Гаврила', level: 5, loc: 'Рассольник', gdp: 880, rep: 22, mine: false },
    { place: 5, name: 'Сухое Горло', id: 5, owner: 'Тихон', level: 5, loc: 'Похмельные Дюны', gdp: 760, rep: 12, mine: false },
    { place: 6, name: 'Бычий Глаз', id: 6, owner: 'Марфа', level: 4, loc: 'Чекушкины Холмы', gdp: 640, rep: 15, mine: false },
    { place: 7, name: 'Хмельной Кот', id: 7, owner: 'Степан', level: 4, loc: 'Бражные Поля', gdp: 520, rep: 9, mine: false },
    { place: 8, name: 'Дно Бутылки', id: 8, owner: 'Аграфена', level: 3, loc: 'Старый Запой', gdp: 410, rep: 7, mine: false },
  ],
}

export default function RatingSheet({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Rating | null>(null)
  const [metric, setMetric] = useState<MetricKey>('gdp')

  useEffect(() => {
    api<Rating>('rating').then(setData)
      .catch(() => setData(DEV ? DEMO : { rows: [], me: null, total_gdp: 0, total: 0 }))
  }, [])

  const m = METRICS.find((x) => x.key === metric)!
  const sorted = useMemo(
    () => (data ? [...data.rows].sort((a, b) => m.val(b) - m.val(a)) : []),
    [data, m])
  const max = sorted.length ? m.val(sorted[0]) || 1 : 1
  const top3 = sorted.slice(0, 3)
  const rest = sorted.slice(3)
  const order = [top3[1], top3[0], top3[2]]   // визуально: 2 · 1 · 3
  const meRow = data?.me && !data.rows.some((r) => r.mine) ? data.me : null

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

        {data === null ? (
          <div className="center" style={{ padding: '52px 0' }}><div className="spin" /></div>
        ) : sorted.length === 0 ? (
          <p className="chron-empty">«В Недоливске пока ни одного кабака. Город трезвенников, тоска.»</p>
        ) : (
          <div className="lb-scroll">
            <div className="lb-podium">
              {order.map((r, i) => {
                if (!r) return <div key={i} className="lb-pod ghost" />
                const rank = sorted.indexOf(r) + 1
                return (
                  <div key={r.name + r.owner} className={`lb-pod r${rank}${r.mine ? ' mine' : ''}`}>
                    {rank === 1 && <div className="lb-crown">👑</div>}
                    <Avatar id={r.id} name={r.name} rank={rank} />
                    <div className="lb-pname">{r.name}</div>
                    <div className="lb-pval">{m.fmt(m.val(r))}</div>
                    <div className="lb-ped"><span>{rank}</span></div>
                  </div>
                )
              })}
            </div>

            <div className="lb-list">
              {rest.map((r) => {
                const rank = sorted.indexOf(r) + 1
                const pct = Math.max(7, Math.round((m.val(r) / max) * 100))
                return (
                  <div key={r.name + r.owner} className={`lb-row${r.mine ? ' mine' : ''}`}
                    style={{ animationDelay: `${Math.min(rank, 14) * 0.035}s` }}>
                    <div className="lb-rank">{rank}</div>
                    <Avatar id={r.id} name={r.name} rank={rank} sm />
                    <div className="lb-info">
                      <div className="lb-name">{r.name}{r.mine && <span className="lb-you">ты</span>}</div>
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
                  <div className="lb-row mine">
                    <div className="lb-rank">{meRow.place}</div>
                    <Avatar id={meRow.id} name={meRow.name} rank={99} sm />
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
      </div>
    </div>
  )
}
