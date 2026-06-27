import { NavLink } from 'react-router-dom'
import { haptic } from '../telegram'

// Только готовые разделы. Торг и Карта пока в боте — вернём вкладки, когда доделаем.
const TABS = [
  { to: '/', icon: '🏠', label: 'Таверна' },
  { to: '/buildings', icon: '🏗', label: 'Стройка' },
  { to: '/character', icon: '🧍', label: 'Персонаж' },
  { to: '/sorties', icon: '⚔️', label: 'Вылазки' },
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
