import { useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import BottomNav from './components/BottomNav'
import Splash from './screens/Splash'
import Tavern from './screens/Tavern'
import Character from './screens/Character'
import Sorties from './screens/Sorties'
import Market from './screens/Market'
import MapScreen from './screens/MapScreen'

export default function App() {
  const [intro, setIntro] = useState(true)
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
