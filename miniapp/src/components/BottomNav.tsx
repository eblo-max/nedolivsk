import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { haptic } from '../telegram'

// Обкатка: вкладка «🏛 Стройка» (городские чудеса) видна ТОЛЬКО админу, пока
// открываем не всем. Открыть всем при запуске = WONDERS_OPEN=true (+ снять
// WONDER_ADMIN_ONLY на сервере). Флаг админа кладёт Tavern в localStorage('adm').
const WONDERS_OPEN = false

const TABS = [
  { to: '/', icon: '🏠', label: 'Таверна' },
  { to: '/buildings', icon: '🏗', label: 'Двор' },       // ЛИЧНЫЕ пристройки таверны
  { to: '/wonders', icon: '🏛', label: 'Стройка', gate: 'wonders' },  // ГОРОДСКИЕ чудеса
  { to: '/character', icon: '🧍', label: 'Персонаж' },
  { to: '/sorties', icon: '⚔️', label: 'Вылазки' },
  { to: '/market', icon: '💰', label: 'Торг' },
  { to: '/map', icon: '🗺', label: 'Карта' },
]

function readAdm(): boolean {
  try { return localStorage.getItem('adm') === '1' } catch { return false }
}

export default function BottomNav() {
  const [adm, setAdm] = useState(readAdm)
  useEffect(() => {                                        // Tavern шлёт 'adm' после загрузки состояния
    const h = () => setAdm(readAdm())
    window.addEventListener('adm', h)
    window.addEventListener('storage', h)
    return () => { window.removeEventListener('adm', h); window.removeEventListener('storage', h) }
  }, [])

  const tabs = TABS.filter((t) => t.gate !== 'wonders' || WONDERS_OPEN || adm)
  return (
    <nav className="nav">
      {tabs.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          data-tut={`nav-${t.to}`}
          end={t.to === '/'}
          className={({ isActive }) => (isActive ? 'on' : '')}
          onClick={() => haptic('light')}
        >
          <span className="ic">{t.icon}</span>
          {t.label}
        </NavLink>
      ))}
    </nav>
  )
}
