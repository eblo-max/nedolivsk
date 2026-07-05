import { lazy, Suspense, useState } from 'react'
import { useNavigate } from 'react-router-dom'

const WonderSheet = lazy(() => import('./WonderSheet'))
const ArtelSheet = lazy(() => import('./ArtelSheet'))

/** Экран «Стройка города» — хаб городских строек (чудеса). Вынесен в навпанель:
 *  тут будут все коллективные стройки. Лавка Артели — вложенный оверлей. */
export default function Wonders() {
  const nav = useNavigate()
  const [artel, setArtel] = useState(false)
  return (
    <Suspense fallback={<div className="center" style={{ flex: 1, paddingTop: 80 }}><div className="spin" /></div>}>
      <WonderSheet page onClose={() => nav('/')} onOpenArtel={() => setArtel(true)} />
      {artel && <ArtelSheet onClose={() => setArtel(false)} />}
    </Suspense>
  )
}
