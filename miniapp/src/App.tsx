import { useState, useEffect } from 'react'
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { pushBack, popBack } from './telegram'
import BottomNav from './components/BottomNav'
import { music } from './music'
import Splash from './screens/Splash'
import TestAccessModal from './screens/TestAccessModal'
import Tavern from './screens/Tavern'
import Character from './screens/Character'
import Sorties from './screens/Sorties'
import Buildings from './screens/Buildings'
import Market from './screens/Market'
import WorldMap from './screens/WorldMap'

export default function App() {
  const [intro, setIntro] = useState(true)
  const [notice, setNotice] = useState(false)   // дисклеймер раннего доступа (каждый вход)
  const loc = useLocation()
  const nav = useNavigate()

  // на под-экранах нативная «назад» Telegram возвращает в Таверну
  // (панели-модалки кладут свой обработчик ПОВЕРХ этого через pushBack)
  useEffect(() => {
    if (intro || loc.pathname === '/') return
    const cb = () => nav('/')
    pushBack(cb)
    return () => popBack(cb)
  }, [loc.pathname, intro, nav])

  // фоновая музыка: старт по первому жесту (вебвью запрещает автоплей), пауза при сворачивании
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
    <>
      <div className="fx-glow" />
      <div className="fx-grain" />
      <div className="fx-vig" />
      {intro && <Splash onEnter={() => { setIntro(false); setNotice(true) }} />}
      {!intro && notice && <TestAccessModal onClose={() => setNotice(false)} />}
      <div className="app">
        {/* место под фикс. тикер резервируем только на Таверне (он там и рендерится) */}
        <div className={`scroll${['/buildings', '/character', '/sorties', '/market', '/map'].includes(loc.pathname) ? '' : ' with-ticker'}`}>
          <Routes>
            <Route path="/" element={<Tavern />} />
            <Route path="/buildings" element={<Buildings />} />
            <Route path="/character" element={<Character />} />
            <Route path="/sorties" element={<Sorties />} />
            <Route path="/market" element={<Market />} />
            <Route path="/map" element={<WorldMap />} />
            {/* Карта пока в боте — любой др. путь ведёт в Таверну */}
            <Route path="*" element={<Tavern />} />
          </Routes>
        </div>
        <BottomNav />
      </div>
    </>
  )
}
