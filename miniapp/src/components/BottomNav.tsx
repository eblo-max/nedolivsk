import { NavLink } from 'react-router-dom'
import { haptic } from '../telegram'

// Карта мира: вкладка-заглушка для всех, реальная тайловая карта — пока только админу.
const TABS = [
  { to: '/', icon: '🏠', label: 'Таверна' },
  { to: '/buildings', icon: '🏗', label: 'Стройка' },
  { to: '/character', icon: '🧍', label: 'Персонаж' },
  { to: '/sorties', icon: '⚔️', label: 'Вылазки' },
  { to: '/market', icon: '💰', label: 'Торг' },
  { to: '/map', icon: '🗺', label: 'Карта' },
]

export default function BottomNav() {
  return (
    <nav className="nav">
      {TABS.map((t) => (
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
