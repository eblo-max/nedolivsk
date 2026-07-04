import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import { hapticNotify } from '../telegram'

// ── Модалка ИТОГОВ боя с Ордой (всплывает на карте сразу после победы/провала). ──
// Полная сводка: исход, слабость орды, длительность, и построчный отчёт по бойцам
// (урон/крит/блок/пал + награда). Данные — /api/invasion/result (та же симуляция).
interface Row {
  name: string; role: string; dmg: number; crit: number; blocked: number
  fell: boolean; gold: number; rep: number; trophy: string; mine: boolean
}
interface Trait { id: string; emoji: string; name: string; blurb: string }
interface Result {
  ok: boolean; available: boolean; won?: boolean; rounds?: number; n?: number
  orc_hp_left?: number; orc_hp_max?: number; rows?: Row[]
  trait?: Trait; rewards_enabled?: boolean; escal?: number
}

const ROLE_EMO: Record<string, string> = { tank: '🛡', archer: '⚔️', scout: '🔭', ratnik: '🗡' }

export default function InvasionResult({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<Result | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    let alive = true
    api<Result>('invasion/result', {})
      .then((r) => { if (!alive) return; setD(r); if (r.available) hapticNotify(r.won ? 'success' : 'error') })
      .catch(() => { if (alive) setErr(true) })
    return () => { alive = false }
  }, [])

  // нет свежего боя — закрываемся молча (не показываем пустое окно)
  useEffect(() => { if (d && !d.available) onClose() }, [d, onClose])

  const won = d?.won
  const rows = d?.rows || []
  const rewards = !!d?.rewards_enabled
  const ohm = d?.orc_hp_max || 0
  const ohl = d?.orc_hp_left || 0

  return createPortal(
    <div className="sv-backdrop" onClick={onClose}>
      <div className="chron-sheet" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
        {/* Шапка-исход */}
        <div style={{
          margin: '-2px -2px 10px', padding: '14px 12px', borderRadius: 14, textAlign: 'center',
          background: won ? 'linear-gradient(180deg,rgba(60,120,40,.35),rgba(30,50,20,.15))'
            : 'linear-gradient(180deg,rgba(120,40,30,.4),rgba(50,20,15,.15))',
          border: `1px solid ${won ? '#4a7a2a' : '#7a3a2a'}`, position: 'relative',
        }}>
          <button onClick={onClose} style={{ position: 'absolute', top: 6, right: 8, background: 'none',
            border: 'none', color: '#c9b48f', fontSize: 20, cursor: 'pointer', lineHeight: 1 }}>✕</button>
          <div style={{ fontSize: 34, lineHeight: 1 }}>{won ? '🏆' : '💀'}</div>
          <div style={{ fontSize: 19, fontWeight: 800, marginTop: 6,
            color: won ? '#a6e06a' : '#ff9a80' }}>
            {won ? 'ОРДА ПОВЕРЖЕНА' : 'ОРДА ПРОРВАЛАСЬ'}
          </div>
          <div style={{ fontSize: 12.5, color: '#c9b48f', marginTop: 3 }}>
            {won ? 'Недоливск выстоял — дружина возвращается домой.'
              : 'Строй пал. Уцелевшие отступают к тавернам.'}
          </div>
        </div>

        {err && <div style={{ padding: 20, textAlign: 'center', color: '#ff9a80' }}>
          Не удалось загрузить сводку — попробуй ещё раз.</div>}
        {!d && !err && <div style={{ padding: 24, textAlign: 'center', color: '#a99676' }}>Считаю итоги…</div>}

        {d?.available && (
          <div style={{ padding: '0 2px' }}>
            {/* Слабость орды */}
            {d.trait && (
              <div style={{ margin: '0 0 10px', padding: '8px 11px', borderRadius: 11,
                background: 'rgba(60,45,28,.4)', border: '1px solid #4a3420' }}>
                <span style={{ fontWeight: 700, color: '#ffcf9a' }}>{d.trait.emoji} {d.trait.name}</span>
                <span style={{ fontSize: 12, color: '#bfa775' }}> — {d.trait.blurb}</span>
              </div>
            )}

            {/* Сводка боя */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              {[
                ['Бойцов', String(d.n ?? rows.length)],
                ['Раундов', String(d.rounds ?? 0)],
                [won ? 'Орда' : 'HP орды', won ? 'убита' : `${ohm ? Math.round((ohl / ohm) * 100) : 0}%`],
              ].map(([k, v]) => (
                <div key={k} style={{ flex: 1, textAlign: 'center', padding: '7px 4px', borderRadius: 10,
                  background: '#1c1610', border: '1px solid #3a2c1a' }}>
                  <div style={{ fontSize: 16, fontWeight: 800, color: '#e9dcc2' }}>{v}</div>
                  <div style={{ fontSize: 11, color: '#a99676' }}>{k}</div>
                </div>
              ))}
            </div>

            {!rewards && (
              <div style={{ margin: '0 0 10px', padding: '7px 10px', borderRadius: 10, fontSize: 12,
                color: '#ffcf9a', background: 'rgba(120,90,30,.22)', border: '1px solid #6a5320' }}>
                ⚠️ Награды сейчас отключены (тестовый режим).
              </div>
            )}

            {/* Построчный отчёт по дружине (сорт по урону — с сервера) */}
            <div style={{ fontSize: 12.5, color: '#bfa775', margin: '2px 0 5px' }}>Дружина в бою:</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: '46vh', overflowY: 'auto' }}>
              {rows.map((r, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px',
                  borderRadius: 10, background: r.mine ? 'rgba(90,120,50,.22)' : '#1a140e',
                  border: `1px solid ${r.mine ? '#6a8a3a' : '#332616'}`, opacity: r.fell ? 0.72 : 1 }}>
                  <span style={{ fontSize: 15 }}>{ROLE_EMO[r.role] || '🗡'}</span>
                  <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap', color: r.mine ? '#e9f0d0' : '#d8c7a4', fontWeight: r.mine ? 700 : 500 }}>
                    {r.name}{r.fell && <span style={{ color: '#c98', fontSize: 11 }}> · пал</span>}
                  </span>
                  <span style={{ fontSize: 12.5, color: '#e0a94a', fontWeight: 700, whiteSpace: 'nowrap' }}>
                    {r.dmg} урона
                  </span>
                  {rewards && (r.gold || r.rep || r.trophy) ? (
                    <span style={{ fontSize: 11.5, color: '#9fd07a', whiteSpace: 'nowrap' }}>
                      {r.gold ? `${r.gold > 0 ? '+' : ''}${r.gold}🪙` : ''}{r.trophy ? ` 🎁` : ''}
                    </span>
                  ) : null}
                </div>
              ))}
              {rows.length === 0 && (
                <div style={{ padding: 14, textAlign: 'center', color: '#a99676', fontSize: 13 }}>
                  На зов никто не встал — орда прошла без боя.
                </div>
              )}
            </div>

            <button className="btn gold" onClick={onClose} style={{ width: '100%', marginTop: 14 }}>
              Закрыть
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
