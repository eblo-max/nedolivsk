import { useEffect, useState } from 'react'
import { api } from '../api'
import { haptic } from '../telegram'

interface Entry { text: string; ago: string }

/** Летопись города — лента заметных событий (история мира). Тянется с /api/chronicle. */
export default function ChronicleSheet({ onClose }: { onClose: () => void }) {
  const [entries, setEntries] = useState<Entry[] | null>(null)
  useEffect(() => {
    api<{ entries: Entry[] }>('chronicle').then((r) => setEntries(r.entries || [])).catch(() => setEntries([]))
  }, [])
  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="chron-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="chron-head">📜 Летопись Недоливска</div>
        {entries === null ? (
          <div className="center" style={{ padding: '34px 0' }}><div className="spin" /></div>
        ) : entries.length === 0 ? (
          <p className="chron-empty">«Летопись чиста, как совесть младенца — пока тут не стряслось ничего, достойного пера.»</p>
        ) : (
          <div className="chron-list">
            {entries.map((e, i) => (
              <div key={i} className="chron-row">
                <span className="chron-dot" />
                <div className="chron-body">
                  <p className="chron-text">{e.text}</p>
                  {e.ago && <span className="chron-ago">{e.ago}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
        <button className="btn gold chron-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
