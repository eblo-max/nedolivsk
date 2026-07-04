import { lazy, Suspense, useEffect, useState } from 'react'
import { api } from '../api'
import { haptic, tgUser } from '../telegram'

const InvasionSheet = lazy(() => import('./InvasionSheet'))
const InvasionResult = lazy(() => import('./InvasionResult'))
const RaidSheet = lazy(() => import('./RaidSheet'))

// Вкладка «Карта мира» — ОТКРЫТА ВСЕМ игрокам. Полноценная тайловая карта (/world,
// Leaflet) грузится в iframe на весь экран между шапкой и навбаром; uid пробрасываем
// в URL (внутри iframe initData недоступна) — нужен лишь для подсветки своей таверны.
// Клик по орде в iframe шлёт postMessage → открываем панель «В строй» ПОВЕРХ карты
// (без релоада приложения — раньше tap уводил в главное меню).
export default function WorldMap() {
  const uid = tgUser()?.id || 0
  const [invOpen, setInvOpen] = useState(false)
  const [resOpen, setResOpen] = useState(false)
  const [raidOpen, setRaidOpen] = useState(false)                   // бой рейд-босса поверх карты
  const [chip, setChip] = useState<{ won: boolean } | null>(null)   // «Итог последнего боя» — переоткрыть, если пропустил

  useEffect(() => {
    function onMsg(e: MessageEvent) {
      if (e.origin !== location.origin) return
      const data = (e.data ?? {}) as { t?: string; won?: boolean }
      if (data.t === 'nedo-orda') { setResOpen(false); setInvOpen(true) }          // панель сбора «в строй»
      else if (data.t === 'nedo-orda-result') {                                    // модалка итогов боя
        setInvOpen(false); setResOpen(true); setChip({ won: !!data.won })          // + оставляем чип для переоткрытия
      } else if (data.t === 'nedo-orda-fx' || data.t === 'nedo-raid-fx') haptic('heavy')   // сильный гаптик на добивании
      else if (data.t === 'nedo-raid') { setInvOpen(false); setResOpen(false); setRaidOpen(true) }   // бой рейд-босса
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [])

  // Зашёл на карту, а бой уже прошёл (в окне 20 мин)? Покажем чип, чтобы посмотреть итог.
  useEffect(() => {
    let alive = true
    api<{ available?: boolean; won?: boolean }>('invasion/result', {})
      .then((r) => { if (alive && r.available) setChip({ won: !!r.won }) })
      .catch(() => { /* нет свежего боя — молча */ })
    return () => { alive = false }
  }, [])

  return (
    <div style={{
      position: 'fixed', left: 0, right: 0, top: 'var(--sa-top, 0px)',
      bottom: 'calc(var(--nav-h) + var(--sa-bottom, 0px))', zIndex: 1, background: '#0b1020',
    }}>
      <iframe title="Карта мира" src={`/world?uid=${uid}`}
        style={{ width: '100%', height: '100%', border: 0, display: 'block' }} />

      {chip && !resOpen && !invOpen && (
        <div style={{ position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)', zIndex: 5,
          display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px 8px 13px', borderRadius: 13,
          maxWidth: '92%', whiteSpace: 'nowrap', color: '#fff', fontWeight: 700, fontSize: 13.5,
          boxShadow: '0 4px 16px rgba(0,0,0,.5)',
          background: chip.won ? 'linear-gradient(180deg,#3f7a24,#255015)' : 'linear-gradient(180deg,#7a2b1e,#4a1810)',
          border: `1px solid ${chip.won ? '#7fd14f' : '#c9603a'}` }}>
          <span onClick={() => setResOpen(true)} style={{ cursor: 'pointer' }}>
            {chip.won ? '🏆' : '💀'} Итог последнего боя ›
          </span>
          <span onClick={() => setChip(null)} aria-label="Скрыть"
            style={{ cursor: 'pointer', opacity: 0.7, paddingLeft: 2, fontSize: 15, lineHeight: 1 }}>✕</span>
        </div>
      )}

      {invOpen && (
        <Suspense fallback={null}>
          <InvasionSheet onClose={() => setInvOpen(false)} />
        </Suspense>
      )}
      {resOpen && (
        <Suspense fallback={null}>
          <InvasionResult onClose={() => setResOpen(false)} />
        </Suspense>
      )}
      {raidOpen && (
        <Suspense fallback={null}>
          <RaidSheet onClose={() => setRaidOpen(false)} />
        </Suspense>
      )}
    </div>
  )
}
