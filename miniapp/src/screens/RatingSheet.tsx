import { useEffect, useState } from 'react'
import { api } from '../api'
import { haptic } from '../telegram'

interface Row { place: number; name: string; owner: string; level: number; loc: string; gdp: number; rep: number; mine: boolean }
interface Rating { rows: Row[]; me: Row | null; total_gdp: number; total: number }

const MEDAL: Record<number, string> = { 1: '👑', 2: '🥈', 3: '🥉' }
const fmt = (n: number) => n.toLocaleString('ru-RU').replace(/,/g, ' ')

// Демо ТОЛЬКО в dev-превью (import.meta.env.DEV). В прод-сборке вырезается.
const DEV = import.meta.env.DEV
const DEMO: Rating = {
  total: 7, total_gdp: 8120,
  rows: [
    { place: 1, name: 'Кривая Кружка', owner: 'Барон', level: 7, loc: 'Изумрудная Чарка', gdp: 1340, rep: 27, mine: true },
    { place: 2, name: 'Пьяный Гусь', owner: 'Прохор', level: 6, loc: 'Зелёный Змий', gdp: 980, rep: 19, mine: false },
    { place: 3, name: 'Косая Бочка', owner: 'Фёкла', level: 5, loc: 'Сухой Закон', gdp: 760, rep: 14, mine: false },
    { place: 4, name: 'Тёплый Подвал', owner: 'Гаврила', level: 4, loc: 'Рассольник', gdp: 540, rep: 9, mine: false },
  ],
  me: null,
}

function RowView({ r }: { r: Row }) {
  return (
    <div className={`chron-row rt-row${r.mine ? ' rt-mine' : ''}`}>
      <span className="rt-place">{MEDAL[r.place] || `${r.place}.`}</span>
      <div className="chron-body">
        <p className="chron-text"><b>{r.name}</b> <span className="rt-loc">📍 {r.loc}</span></p>
        <span className="chron-ago">ур.{r.level} · 💰 ВВП {fmt(r.gdp)} · ⭐ {r.rep} · {r.owner}{r.mine ? ' · ты' : ''}</span>
      </div>
    </div>
  )
}

/** Доска почёта — топ таверн Недоливска по ВВП. Тянется с /api/rating. */
export default function RatingSheet({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<Rating | null>(null)
  useEffect(() => {
    api<Rating>('rating').then((r) => setData(r))
      .catch(() => setData(DEV ? DEMO : { rows: [], me: null, total_gdp: 0, total: 0 }))
  }, [])
  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="chron-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="chron-head">🏆 Топ таверн Недоливска</div>
        {data === null ? (
          <div className="center" style={{ padding: '34px 0' }}><div className="spin" /></div>
        ) : data.rows.length === 0 ? (
          <p className="chron-empty">«В Недоливске пока ни одного кабака. Город трезвенников, тоска.»</p>
        ) : (
          <>
            <p className="rt-sub">Кабаков в городе: <b>{data.total}</b> · ВВП города: <b>{fmt(data.total_gdp)}</b> 🪙</p>
            <div className="chron-list">
              {data.rows.map((r) => <RowView key={r.place} r={r} />)}
              {data.me && (
                <>
                  <div className="rt-gap">· · ·</div>
                  <RowView r={data.me} />
                </>
              )}
            </div>
            {!data.me && !data.rows.some((r) => r.mine) && (
              <p className="rt-foot">Не нашёл себя? Так и запишем: пьёшь больше, чем зарабатываешь.</p>
            )}
          </>
        )}
        <button className="btn gold chron-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
