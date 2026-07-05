import { useState, useEffect, lazy, Suspense } from 'react'
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { pushBack, popBack } from './telegram'
import BottomNav from './components/BottomNav'
import { music } from './music'
import Splash from './screens/Splash'
import ChannelModal from './screens/ChannelModal'
import Tavern from './screens/Tavern'

// Под-экраны — ленивые чанки: первый вход грузит только Таверну (быстрее старт
// на холодном WebView), остальное подтягивается при переходе по вкладкам.
const Character = lazy(() => import('./screens/Character'))
const Sorties = lazy(() => import('./screens/Sorties'))
const Buildings = lazy(() => import('./screens/Buildings'))
const Wonders = lazy(() => import('./screens/Wonders'))
const Market = lazy(() => import('./screens/Market'))
const WorldMap = lazy(() => import('./screens/WorldMap'))
const Tutorial = lazy(() => import('./screens/Tutorial'))

const LOADING = <div className="center" style={{ flex: 1, paddingTop: 80 }}><div className="spin" /></div>

// промо канала — не чаще раза в сутки на устройство (дата последнего показа)
function channelDueToday(): boolean {
  try {
    const today = new Date().toISOString().slice(0, 10)
    if (localStorage.getItem('chanSeen') === today) return false
    localStorage.setItem('chanSeen', today)
    return true
  } catch { return false }   // приватный режим/нет localStorage — не назойливо
}

export default function App() {
  const [intro, setIntro] = useState(true)
  const [chan, setChan] = useState(false)
  const [tut, setTut] = useState(false)
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
      {intro && <Splash onEnter={() => {
        setIntro(false)
        let done = true
        try { done = localStorage.getItem('tutDone') === '1' } catch { /* */ }
        if (!done) setTut(true)                      // новичок → обучение (один раз)
        else if (channelDueToday()) setChan(true)
      }} />}
      {!intro && tut && (
        <Suspense fallback={null}>
          <Tutorial onDone={() => {
            try { localStorage.setItem('tutDone', '1') } catch { /* */ }   // больше не всплывать
            setTut(false); if (channelDueToday()) setChan(true)
          }} />
        </Suspense>
      )}
      {!intro && !tut && chan && <ChannelModal onClose={() => setChan(false)} />}
      <div className="app">
        {/* место под фикс. тикер резервируем только на Таверне (он там и рендерится) */}
        <div className={`scroll${['/buildings', '/wonders', '/character', '/sorties', '/market', '/map'].includes(loc.pathname) ? '' : ' with-ticker'}`}>
          <Suspense fallback={LOADING}>
            <Routes>
              <Route path="/" element={<Tavern />} />
              <Route path="/buildings" element={<Buildings />} />
              <Route path="/wonders" element={<Wonders />} />
              <Route path="/character" element={<Character />} />
              <Route path="/sorties" element={<Sorties />} />
              <Route path="/market" element={<Market />} />
              <Route path="/map" element={<WorldMap />} />
              {/* любой другой путь ведёт в Таверну */}
              <Route path="*" element={<Tavern />} />
            </Routes>
          </Suspense>
        </div>
        <BottomNav />
      </div>
    </>
  )
}
