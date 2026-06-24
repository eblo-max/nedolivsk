import { useState, useEffect } from 'react'
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { pushBack, popBack } from './telegram'
import BottomNav from './components/BottomNav'
import Splash from './screens/Splash'
import Tavern from './screens/Tavern'
import Character from './screens/Character'
import Sorties from './screens/Sorties'
import Market from './screens/Market'
import MapScreen from './screens/MapScreen'

export default function App() {
  const [intro, setIntro] = useState(true)
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

  return (
    <>
      <div className="fx-glow" />
      <div className="fx-grain" />
      <div className="fx-vig" />
      {intro && <Splash onEnter={() => setIntro(false)} />}
      <div className="app">
        <div className="scroll">
          <Routes>
            <Route path="/" element={<Tavern />} />
            <Route path="/character" element={<Character />} />
            <Route path="/sorties" element={<Sorties />} />
            <Route path="/market" element={<Market />} />
            <Route path="/map" element={<MapScreen />} />
            <Route path="*" element={<Tavern />} />
          </Routes>
        </div>
        <BottomNav />
      </div>
    </>
  )
}
