import { useEffect, useState, type ReactNode } from 'react'
import { pushBack, popBack } from '../telegram'

/** Переиспользуемая bottom-sheet оболочка: затемнение, выезд снизу, закрытие
 * (X / тап вне / нативная «назад»), блок прокрутки фона и скрытие навбара. */
export default function Sheet({ icon, title, onClose, children }: {
  icon?: string
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const [closing, setClosing] = useState(false)
  function close() { if (closing) return; setClosing(true); setTimeout(onClose, 240) }

  useEffect(() => {
    pushBack(close)
    return () => popBack(close)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // блок прокрутки фона (скроллит body): iOS-устойчиво — фиксируем body со
  // смещением на текущую позицию, на закрытии возвращаем. + прячем навбар.
  useEffect(() => {
    const body = document.body
    const nav = document.querySelector('.nav') as HTMLElement | null
    const y = window.scrollY
    const prev = { overflow: body.style.overflow, position: body.style.position, top: body.style.top, width: body.style.width }
    const pn = nav?.style.display
    body.style.overflow = 'hidden'; body.style.position = 'fixed'; body.style.top = `-${y}px`; body.style.width = '100%'
    if (nav) nav.style.display = 'none'
    return () => {
      body.style.overflow = prev.overflow; body.style.position = prev.position; body.style.top = prev.top; body.style.width = prev.width
      window.scrollTo(0, y)
      if (nav) nav.style.display = pn ?? ''
    }
  }, [])

  return (
    <div className={`sheet-ov${closing ? ' out' : ''}`} onClick={close}>
      <div className={`sheet${closing ? ' out' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grab" />
        <div className="sheet-h">
          {icon && <img className="sheet-ic" src={icon} alt="" onError={(e) => { e.currentTarget.style.display = 'none' }} />}
          <span>{title}</span>
          <button className="sheet-x" onClick={close} aria-label="Закрыть">✕</button>
        </div>
        <div className="sheet-b">{children}</div>
      </div>
    </div>
  )
}
