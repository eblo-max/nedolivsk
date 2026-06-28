import { NavLink } from 'react-router-dom'
import { haptic } from '../telegram'

// Карта пока в боте. Торг открыт (закрыт гейтом до запуска — внутри lock-экран).
const TABS = [
  { to: '/', icon: '🏠', label: 'Таверна' },
  { to: '/buildings', icon: '🏗', label: 'Стройка' },
  { to: '/character', icon: '🧍', label: 'Персонаж' },
  { to: '/sorties', icon: '⚔️', label: 'Вылазки' },
  { to: '/market', icon: '💰', label: 'Торг' },
]

export default function BottomNav() {
  return (
    <nav className="nav">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
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
