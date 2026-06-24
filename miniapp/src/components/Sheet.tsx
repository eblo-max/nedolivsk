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

  useEffect(() => {
    const scroll = document.querySelector('.scroll') as HTMLElement | null
    const nav = document.querySelector('.nav') as HTMLElement | null
    const po = scroll?.style.overflowY
    const pn = nav?.style.display
    if (scroll) scroll.style.overflowY = 'hidden'
    if (nav) nav.style.display = 'none'
    return () => {
      if (scroll) scroll.style.overflowY = po ?? ''
      if (nav) nav.style.display = pn ?? ''
    }
  }, [])

  return (
    <div className={`sheet-ov${closing ? ' out' : ''}`} onClick={close}>
      <div className={`sheet${closing ? ' out' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grab" />
        <div className="sheet-h">
          {icon && <img className="sheet-ic" src={icon} alt="" />}
          <span>{title}</span>
          <button className="sheet-x" onClick={close} aria-label="Закрыть">✕</button>
        </div>
        <div className="sheet-b">{children}</div>
      </div>
    </div>
  )
}
