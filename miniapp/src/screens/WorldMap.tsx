import { lazy, Suspense, useEffect, useState } from 'react'
import { tgUser } from '../telegram'

const InvasionSheet = lazy(() => import('./InvasionSheet'))

// Вкладка «Карта мира» — ОТКРЫТА ВСЕМ игрокам. Полноценная тайловая карта (/world,
// Leaflet) грузится в iframe на весь экран между шапкой и навбаром; uid пробрасываем
// в URL (внутри iframe initData недоступна) — нужен лишь для подсветки своей таверны.
// Клик по орде в iframe шлёт postMessage → открываем панель «В строй» ПОВЕРХ карты
// (без релоада приложения — раньше tap уводил в главное меню).
export default function WorldMap() {
  const uid = tgUser()?.id || 0
  const [invOpen, setInvOpen] = useState(false)

  useEffect(() => {
    function onMsg(e: MessageEvent) {
      if (e.origin === location.origin && (e.data as { t?: string })?.t === 'nedo-orda') setInvOpen(true)
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [])

  return (
    <div style={{
      position: 'fixed', left: 0, right: 0, top: 'var(--sa-top, 0px)',
      bottom: 'calc(var(--nav-h) + var(--sa-bottom, 0px))', zIndex: 1, background: '#0b1020',
    }}>
      <iframe title="Карта мира" src={`/world?uid=${uid}`}
        style={{ width: '100%', height: '100%', border: 0, display: 'block' }} />
      {invOpen && (
        <Suspense fallback={null}>
          <InvasionSheet onClose={() => setInvOpen(false)} />
        </Suspense>
      )}
    </div>
  )
}
