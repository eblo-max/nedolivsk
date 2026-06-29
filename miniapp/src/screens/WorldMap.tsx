import { useEffect, useState } from 'react'
import { api } from '../api'
import { tgUser } from '../telegram'
import Placeholder from './_Placeholder'

// Вкладка «Карта мира». Полноценная тайловая карта (/world, Leaflet) — пока ТОЛЬКО
// админу; остальным — заглушка «скоро». Карту грузим в iframe на весь экран между
// шапкой и навбаром; uid пробрасываем в URL (внутри iframe initData недоступна) —
// нужен лишь для подсветки своей таверны, доступ гейтит сервер (whoami по initData).
export default function WorldMap() {
  const [admin, setAdmin] = useState<boolean | null>(null)

  useEffect(() => {
    api<{ admin?: boolean }>('whoami').then((r) => setAdmin(!!r.admin)).catch(() => setAdmin(false))
  }, [])

  if (admin === null) {
    return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  }
  if (!admin) {
    return (
      <Placeholder
        title="Карта мира" sub="скоро"
        note="Огромная мировая карта Недоливска с таврнами всех игроков — уже в пути. Скоро откроем для всех." />
    )
  }
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
