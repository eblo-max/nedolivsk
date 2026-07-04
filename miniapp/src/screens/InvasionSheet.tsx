import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'

// ── ФАЗА 1: панель сбора «Орда орков» — выбор СТОЙКИ (роли), слабость орды
// (варлорд-трейт) и доска готовности. Автобой; агентность — в композиции. ──
interface Stance { id: string; emoji: string; name: string; blurb: string; role: string; counter: boolean }
interface Comp { tank: number; archer: number; scout: number; ratnik: number; front: number; n: number }
interface Trait { id: string; emoji: string; name: string; counter: string; blurb: string }
interface State {
  ok: boolean; active: boolean; n?: number; ready?: number; gather_left?: number
  registered?: boolean; my_stance?: string | null
  trait?: Trait; comp?: Comp; hint?: string; stances?: Stance[]
}

const ROLE_EMO: Record<string, string> = { tank: '🛡', archer: '⚔️', scout: '🔭', ratnik: '🗡' }

function fmt(s: number) { const m = (s / 60) | 0, ss = (s | 0) % 60; return `${m}:${ss < 10 ? '0' : ''}${ss}` }

export default function InvasionSheet({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<State | null>(null)
  const [busy, setBusy] = useState(false)
  const [pick, setPick] = useState<string>('')
  const [left, setLeft] = useState(0)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  async function load() {
    try { const r = await api<State>('invasion/state', {}); setD(r); if (r.gather_left != null) setLeft(r.gather_left) } catch { /* keep */ }
  }
  useEffect(() => {
    load(); const t = setInterval(load, 5000)
    timer.current = setInterval(() => setLeft((v) => Math.max(0, v - 1)), 1000)
    return () => { clearInterval(t); if (timer.current) clearInterval(timer.current) }
  }, [])

  async function join(stance: string) {
    if (busy) return; setBusy(true); haptic('medium')
    try {
      const r = await api<State & { error?: string }>('invasion/join', { stance })
      if (r.ok) { hapticNotify('success'); await load() }
      else hapticNotify('warning')
    } catch { hapticNotify('warning') } finally { setBusy(false) }
  }

  const active = d?.active
  const trait = d?.trait
  const comp = d?.comp
  const ready = Math.max(0, Math.min(1, d?.ready ?? 0))
  const win = ready >= 0.7

  return createPortal(
    <div className="sv-backdrop" onClick={onClose}>
      <div className="chron-sheet" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 4px 8px' }}>
          <span style={{ fontSize: 24 }}>🪓</span>
          <b style={{ fontSize: 17, color: '#e9c98a' }}>Орда орков</b>
          {active && <span style={{ marginLeft: 'auto', color: '#bfa775', fontSize: 13 }}>сбор {fmt(left)}</span>}
          <button onClick={onClose} style={{ marginLeft: active ? 8 : 'auto', background: 'none',
            border: 'none', color: '#a99676', fontSize: 20, cursor: 'pointer', lineHeight: 1 }}>✕</button>
        </div>

        {!active ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#a99676' }}>
            <div style={{ fontSize: 40, marginBottom: 8 }}>🏞</div>
            Орда не идёт. На горизонте тихо — готовь дружину к следующей волне.
          </div>
        ) : (
          <div style={{ padding: '4px 14px 14px' }}>
            {/* Слабость орды (варлорд-трейт) */}
            {trait && (
              <div style={{ margin: '8px 0', padding: '10px 12px', borderRadius: 12,
                background: 'rgba(120,40,30,.25)', border: '1px solid #7a3a2a' }}>
                <div style={{ fontWeight: 800, color: '#ffcf9a' }}>{trait.emoji} {trait.name}</div>
                <div style={{ fontSize: 12.5, color: '#d8bfa0', marginTop: 3 }}>{trait.blurb}</div>
              </div>
            )}

            {/* Доска готовности */}
            <div style={{ margin: '10px 0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, color: '#bfa775', marginBottom: 4 }}>
                <span>Готовность дружины · {d?.n ?? 0} бойцов</span>
                <span style={{ color: win ? '#8fd14f' : '#e0a94a', fontWeight: 700 }}>{win ? 'победа в кармане' : 'мало сил'}</span>
              </div>
              <div style={{ height: 12, borderRadius: 8, background: '#241a12', overflow: 'hidden', border: '1px solid #4a3420' }}>
                <div style={{ height: '100%', width: `${Math.round(ready * 100)}%`, transition: 'width .5s',
                  background: win ? 'linear-gradient(90deg,#4a8f2a,#8fd14f)' : 'linear-gradient(90deg,#8a4a1a,#e0a94a)' }} />
              </div>
              {d?.hint && <div style={{ marginTop: 6, fontSize: 12.5, fontWeight: 700,
                color: d.hint.includes('НУЖЕН') || d.hint.includes('нужны') ? '#ffb060' : '#9fd07a' }}>{d.hint}</div>}
            </div>

            {/* Состав по ролям */}
            {comp && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0 12px', justifyContent: 'center' }}>
                {(['tank', 'archer', 'scout', 'ratnik'] as const).map((r) => (
                  <span key={r} style={{ padding: '4px 9px', borderRadius: 999, background: '#241a12',
                    border: '1px solid #4a3420', fontSize: 13, color: comp[r] ? '#e9dcc2' : '#6a5a44' }}>
                    {ROLE_EMO[r]} {comp[r]}
                  </span>
                ))}
              </div>
            )}

            {/* Запись / выбор стойки */}
            {d?.registered ? (
              <div style={{ textAlign: 'center', padding: '10px 0', color: '#8fd14f', fontWeight: 700 }}>
                ✅ Ты в строю ({d.stances?.find((s) => s.id === d.my_stance)?.name || 'в резерве'}).<br />
                <span style={{ color: '#a99676', fontWeight: 400, fontSize: 13 }}>Зови соратников — доберите нужные роли!</span>
              </div>
            ) : (
              <>
                <div style={{ fontSize: 13, color: '#bfa775', marginBottom: 6 }}>Выбери, кем встать в бой:</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  {(d?.stances || []).map((s) => (
                    <button key={s.id} disabled={busy} onClick={() => setPick(s.id)}
                      style={{ textAlign: 'left', padding: '9px 11px', borderRadius: 12, cursor: 'pointer',
                        background: pick === s.id ? 'rgba(90,150,50,.22)' : '#1c1610',
                        border: `1.5px solid ${pick === s.id ? '#8fd14f' : (s.counter ? '#c79a44' : '#4a3420')}` }}>
                      <div style={{ fontWeight: 700, color: '#e9dcc2' }}>{s.emoji} {s.name}
                        {s.counter && <span style={{ color: '#ffd27a', fontSize: 11 }}> ★ против орды</span>}</div>
                      <div style={{ fontSize: 11.5, color: '#a99676', marginTop: 2 }}>{s.blurb}</div>
                    </button>
                  ))}
                </div>
                <button className="btn gold" disabled={busy || !pick} onClick={() => join(pick)}
                  style={{ width: '100%', marginTop: 12, opacity: pick ? 1 : 0.5 }}>
                  ⚔️ Встать в строй
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>,
    document.body,
  )
}
