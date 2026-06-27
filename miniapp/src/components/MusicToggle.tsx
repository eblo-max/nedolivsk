import { useEffect, useState } from 'react'
import { music } from '../music'
import { haptic } from '../telegram'

/** Кнопка вкл/выкл фоновой музыки (вшита в шапку Таверны). Автостарт по первому жесту и
 *  пауза при сворачивании живут глобально в App; здесь — только переключатель состояния. */
export default function MusicToggle() {
  const [, force] = useState(0)
  useEffect(() => music.subscribe(() => force((n) => n + 1)), [])
  return (
    <button
      className={`music-btn ${music.muted ? 'off' : 'on'}`}
      aria-label={music.muted ? 'Включить музыку' : 'Выключить музыку'}
      onClick={(e) => { e.stopPropagation(); haptic('light'); music.toggleMute() }}
    >
      {music.muted ? '🔇' : '🎵'}
    </button>
  )
}
