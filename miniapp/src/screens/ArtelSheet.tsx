import { useEffect, useState } from 'react'
import { api, errText } from '../api'
import { haptic, hapticNotify } from '../telegram'

interface Reward {
  id: string; emoji: string; name: string; desc: string
  cost: number; kind: string; owned: boolean; affordable: boolean
}
interface Resp { ok?: boolean; zodar: number; catalog: Reward[] }

const DEV = import.meta.env.DEV
const SAMPLE: Resp = {
  zodar: 6,
  catalog: [
    { id: 't_zodchy', emoji: '🔨', name: 'Титул «Зодчий»', desc: 'Звание у имени — ты поднимал чудеса города.', cost: 10, kind: 'title', owned: false, affordable: false },
    { id: 't_mason', emoji: '🧱', name: 'Титул «Каменщик Недоливска»', desc: 'Уважение цеха каменщиков за вклад в стройки.', cost: 25, kind: 'title', owned: false, affordable: false },
    { id: 'f_carved', emoji: '🪵', name: 'Резной фасад таверны', desc: 'Артель украсит твою вывеску — видно гостям и на карте.', cost: 40, kind: 'facade', owned: false, affordable: false },
    { id: 't_pillar', emoji: '🏛', name: 'Титул «Столп общины»', desc: 'Высшее звание строителя — имя, что помнит весь город.', cost: 80, kind: 'title', owned: false, affordable: false },
  ],
}

/** Лавка Артели зодчих — трата редкой валюты «Зодар» на престиж. */
export default function ArtelSheet({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<Resp | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    (DEV ? Promise.resolve(SAMPLE) : api<Resp>('artel'))
      .then(setD).catch(() => setD({ zodar: 0, catalog: [] }))
  }, [])

  async function buy(r: Reward) {
    if (busy || r.owned || !r.affordable) return
    setBusy(true); setErr(''); haptic('medium')
    try {
      const res: Resp = DEV
        ? { zodar: d!.zodar - r.cost, catalog: d!.catalog.map((x) => x.id === r.id ? { ...x, owned: true } : x) }
        : await api<Resp>('artel/buy', { id: r.id })
      setD(res); hapticNotify('success')
    } catch (e) { setErr(errText(e)); hapticNotify('error') }
    finally { setBusy(false) }
  }

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="ar-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="ar-head">
          <span className="ar-title">⚒ Лавка Артели зодчих</span>
          <span className="ar-bal" title="Зодары — только за стройки">{d?.zodar ?? 0} ⚒</span>
        </div>
        <p className="ar-lore">«Зодар не купишь и не пропьёшь — его вручают за руки, что подняли чудеса города.»</p>

        {d === null ? (
          <div className="center" style={{ padding: '40px 0' }}><div className="spin" /></div>
        ) : (
          <div className="ar-list">
            {d.catalog.map((r) => (
              <div key={r.id} className={`ar-card${r.owned ? ' owned' : ''}`}>
                <span className="ar-emo">{r.emoji}</span>
                <div className="ar-body">
                  <div className="ar-name">{r.name}</div>
                  <div className="ar-desc">{r.desc}</div>
                </div>
                {r.owned ? (
                  <span className="ar-have">✓ есть</span>
                ) : (
                  <button className="btn ar-buy" disabled={busy || !r.affordable}
                    onClick={() => buy(r)}>{r.cost} ⚒</button>
                )}
              </div>
            ))}
          </div>
        )}

        {err && <div className="wd-err">⚠ {err}<small>Попробуй снова</small></div>}
        <button className="btn gold" style={{ marginTop: 10 }} onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
