import { useEffect, useState } from 'react'
import { haptic } from '../telegram'

/** Заставка при запуске: таверна показывается крупным планом и ~10 c
 * медленно отдаляется, открывая весь зал. Кнопка «Налить пива» — вход в игру. */
export default function Splash({ onEnter }: { onEnter: () => void }) {
  const [leaving, setLeaving] = useState(false)

  function enter() {
    if (leaving) return
    haptic('medium'); setLeaving(true)
    setTimeout(onEnter, 420)               // дать отыграть затухание
  }

  // мягкая вибро-затравка в начале
  useEffect(() => { haptic('light') }, [])

  return (
    <div className={`splash${leaving ? ' out' : ''}`}>
      <div className="splash-scene">
        <img
          className="splash-img"
          src={`${import.meta.env.BASE_URL}scene/tavern.png`}
          alt="Таверна"
        />
      </div>

      <div className="splash-veil" />

      <div className="splash-top">
        <div className="title">НЕДОЛИВСК<small>САМЫЙ СКЛОЧНЫЙ ГОРОДОК</small></div>
        <div className="orn"><img className="orn-ic" src={`${import.meta.env.BASE_URL}goods/ale.png`} alt="" /></div>
      </div>

      <div className="splash-bottom">
        <div className="splash-tag">Свечи оплыли, эль разлит — пора и тебе за стойку.</div>
        <button className="btn gold splash-cta" onClick={enter}>
          <img className="btn-ic" src={`${import.meta.env.BASE_URL}goods/ale.png`} alt="" />НАЛИТЬ ПИВА
        </button>
      </div>
    </div>
  )
}
