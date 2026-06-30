import { tgUser } from '../telegram'

// Вкладка «Карта мира» — ОТКРЫТА ВСЕМ игрокам. Полноценная тайловая карта (/world,
// Leaflet) грузится в iframe на весь экран между шапкой и навбаром; uid пробрасываем
// в URL (внутри iframe initData недоступна) — нужен лишь для подсветки своей таверны.
export default function WorldMap() {
  const uid = tgUser()?.id || 0
  return (
    <div style={{
      position: 'fixed', left: 0, right: 0, top: 'var(--sa-top, 0px)',
      bottom: 'calc(var(--nav-h) + var(--sa-bottom, 0px))', zIndex: 1, background: '#0b1020',
    }}>
      <iframe title="Карта мира" src={`/world?uid=${uid}`}
        style={{ width: '100%', height: '100%', border: 0, display: 'block' }} />
    </div>
  )
}
