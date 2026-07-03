import { useState, useEffect, useCallback, useLayoutEffect, useRef, type CSSProperties } from 'react'
import { haptic } from '../telegram'

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

// Найти и измерить подсвечиваемый элемент. Скроллим его в центр и меряем на
// следующем кадре (после того как скролл применился) — иначе рамка встаёт по
// старой позиции. Если элемента ещё нет в DOM (данные грузятся) — пробуем ещё
// несколько раз, а не молча гасим подсветку.
function useRect(sel: string | undefined, tick: number) {
  const [rect, setRect] = useState<DOMRect | null>(null)
  useLayoutEffect(() => {
    if (!sel) { setRect(null); return }
    let raf = 0, tries = 0
    const find = () => {
      const el = document.querySelector(sel)
      if (el) {
        el.scrollIntoView({ block: 'center', behavior: 'auto' })
        raf = requestAnimationFrame(() => setRect(el.getBoundingClientRect()))
        return
      }
      if (tries++ < 20) raf = requestAnimationFrame(find)   // ждём появления якоря
      else setRect(null)
    }
    find()
    return () => cancelAnimationFrame(raf)
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
  const cardRef = useRef<HTMLDivElement>(null)
  const [cardH, setCardH] = useState(0)

  useEffect(() => {
    const f = () => setTick((t) => t + 1)
    window.addEventListener('resize', f)
    const id = setTimeout(f, 80)
    return () => { window.removeEventListener('resize', f); clearTimeout(id) }
  }, [i])

  // высота карточки нужна, чтобы зажать её в экран (не улетала за край)
  useLayoutEffect(() => {
    if (cardRef.current) setCardH(cardRef.current.offsetHeight)
  }, [i, tick, rect])

  const done = useCallback(() => onDone(), [onDone])
  const next = () => { haptic('light'); i + 1 < steps.length ? setI(i + 1) : done() }
  if (!step) return null

  const pad = 8, edge = 12, gap = 14
  const vh = window.innerHeight

  // Позиция карточки: под элементом или над ним — где влезает; если не влезает
  // нигде (высокий якорь) — прижимаем к низу. Итог всегда зажат в вьюпорт.
  let cardStyle: CSSProperties
  if (rect && cardH) {
    const below = rect.bottom + gap
    const aboveTop = rect.top - gap - cardH
    const fitsBelow = below + cardH <= vh - edge
    const fitsAbove = aboveTop >= edge
    let top: number
    if (step.place === 'top' && fitsAbove) top = aboveTop
    else if (step.place === 'bottom' && fitsBelow) top = below
    else if (fitsBelow) top = below
    else if (fitsAbove) top = aboveTop
    else top = vh - edge - cardH
    top = Math.max(edge, Math.min(top, vh - edge - cardH))
    cardStyle = { top, left: '50%', transform: 'translateX(-50%)' }
  } else {
    cardStyle = { top: '50%', left: '50%', transform: 'translate(-50%,-50%)' }
  }

  return (
    <div className="tut-root">
      {/* затемнение: при подсветке — прозрачный ловец кликов (темноту даёт вырез
          в тени .tut-spot); без подсветки — сплошная заливка под центр-карточку */}
      <div className={`tut-dim${rect ? '' : ' full'}`} onClick={next} />
      {rect && (
        <div className="tut-spot" style={{
          left: rect.left - pad, top: rect.top - pad,
          width: rect.width + pad * 2, height: rect.height + pad * 2,
        }} />
      )}
      <div ref={cardRef} className="tut-card" style={cardStyle} onClick={(e) => e.stopPropagation()}>
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

/** Тур при ПЕРВОМ заходе на экран: показывается один раз (флаг localStorage). */
export function useFirstVisitTour(key: string) {
  const [show, setShow] = useState(false)
  useEffect(() => {
    let seen = true
    try { seen = localStorage.getItem(`tour_${key}`) === '1' } catch { /* */ }
    if (!seen) setShow(true)
  }, [key])
  const finish = useCallback(() => {
    try { localStorage.setItem(`tour_${key}`, '1') } catch { /* */ }
    setShow(false)
  }, [key])
  return { show, finish }
}
