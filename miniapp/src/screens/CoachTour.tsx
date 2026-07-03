import { useState, useEffect, useCallback, useLayoutEffect } from 'react'
import { haptic } from '../telegram'
import { useIsAdmin } from '../admin'

// Универсальный контекстный гид (coachmark): подсветка реального элемента +
// карточка «что это и зачем». Переиспользуется для обзорного тура и для
// подробных пер-экранных подсказок (just-in-time при первом заходе).
export interface Step {
  sel?: string        // селектор подсвечиваемого элемента (нет — карточка по центру)
  emoji: string
  title: string
  body: string
  place?: 'top' | 'bottom'
}

function useRect(sel: string | undefined, tick: number) {
  const [rect, setRect] = useState<DOMRect | null>(null)
  useLayoutEffect(() => {
    if (!sel) { setRect(null); return }
    const el = document.querySelector(sel)
    if (el) { el.scrollIntoView({ block: 'center', behavior: 'auto' }); setRect(el.getBoundingClientRect()) }
    else setRect(null)
  }, [sel, tick])
  return rect
}

export default function CoachTour({ steps, onDone, endLabel = '🍺 За дело!' }: {
  steps: Step[]; onDone: () => void; endLabel?: string
}) {
  const [i, setI] = useState(0)
  const [tick, setTick] = useState(0)
  const step = steps[i]
  const rect = useRect(step?.sel, tick)

  useEffect(() => {
    const f = () => setTick((t) => t + 1)
    window.addEventListener('resize', f)
    const id = setTimeout(f, 60)
    return () => { window.removeEventListener('resize', f); clearTimeout(id) }
  }, [i])

  const done = useCallback(() => onDone(), [onDone])
  const next = () => { haptic('light'); i + 1 < steps.length ? setI(i + 1) : done() }
  if (!step) return null

  const pad = 8
  const above = rect && (step.place === 'top' || rect.top > window.innerHeight / 2)
  const cardTop = rect && !above ? rect.bottom + pad + 12 : undefined
  const cardBottom = rect && above ? (window.innerHeight - rect.top + pad + 12) : undefined

  return (
    <div className="tut-root">
      <div className="tut-dim" onClick={next} />
      {rect && (
        <div className="tut-spot" style={{
          left: rect.left - pad, top: rect.top - pad,
          width: rect.width + pad * 2, height: rect.height + pad * 2,
        }} />
      )}
      <div className="tut-card"
        style={rect
          ? { top: cardTop, bottom: cardBottom, left: '50%', transform: 'translateX(-50%)' }
          : { top: '50%', left: '50%', transform: 'translate(-50%,-50%)' }}
        onClick={(e) => e.stopPropagation()}>
        <div className="tut-emoji">{step.emoji}</div>
        <div className="tut-title">{step.title}</div>
        <p className="tut-body">{step.body}</p>
        <div className="tut-dots">
          {steps.map((_, k) => <i key={k} className={k === i ? 'on' : ''} />)}
        </div>
        <button className="btn gold tut-next" onClick={next}>
          {i + 1 < steps.length ? 'Дальше →' : endLabel}
        </button>
        <button className="tut-skip" onClick={() => { haptic('light'); done() }}>Пропустить</button>
      </div>
    </div>
  )
}

/** Тур при ПЕРВОМ заходе на экран: показывается один раз (флаг localStorage).
 * ВРЕМЕННО: только админу (обкатка обучения в проде) — остальным не мозолим глаза,
 * флаг первого визита им НЕ жжём, чтобы при открытии всем тур сработал честно. */
export function useFirstVisitTour(key: string) {
  const [show, setShow] = useState(false)
  const admin = useIsAdmin()
  useEffect(() => {
    if (!admin) { setShow(false); return }
    let seen = true
    try { seen = localStorage.getItem(`tour_${key}`) === '1' } catch { /* */ }
    if (!seen) setShow(true)
  }, [key, admin])
  const finish = useCallback(() => {
    try { localStorage.setItem(`tour_${key}`, '1') } catch { /* */ }
    setShow(false)
  }, [key])
  return { show, finish }
}
