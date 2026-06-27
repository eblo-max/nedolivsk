import { useEffect, useState } from 'react'
import { music } from '../music'
import { haptic } from '../telegram'

/** Плавающая кнопка вкл/выкл фоновой музыки + автостарт по первому жесту (автоплей в вебвью
 *  запрещён до взаимодействия). Состояние mute помнится в localStorage (через music). */
export default function MusicToggle() {
  const [, force] = useState(0)
  useEffect(() => music.subscribe(() => force((n) => n + 1)), [])

  useEffect(() => {
    const kick = () => music.start()
    window.addEventListener('pointerdown', kick, { once: true })
    window.addEventListener('keydown', kick, { once: true })
    const vis = () => music.setHidden(document.hidden)
    document.addEventListener('visibilitychange', vis)
    return () => {
      window.removeEventListener('pointerdown', kick)
      window.removeEventListener('keydown', kick)
      document.removeEventListener('visibilitychange', vis)
    }
  }, [])

  return (
    <button
      className={`music-btn ${music.muted ? 'off' : 'on'}`}
      aria-label={music.muted ? 'Включить музыку' : 'Выключить музыку'}
      onClick={() => { haptic('light'); music.toggleMute() }}
    >
      {music.muted ? '🔇' : '🎵'}
    </button>
  )
}
