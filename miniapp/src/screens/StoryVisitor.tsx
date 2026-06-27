import { useRef, useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { ResIcon, fmt } from '../components/icons'

// ── типы (зеркало webapp _story_state / _api_story_choice) ──
interface StoryNpc { emoji: string; name: string; blurb: string; traits: string[] }
interface StoryChoice { index: number; label: string }
export interface StoryData { id: string; title: string; text: string; npc: StoryNpc | null; choices: StoryChoice[] }
interface ResLine { key: string; qty: number; name: string; emoji?: string }
interface Outcome { text: string; gold: number; rep: number; res: ResLine[] }

/** Внезапный визитёр-горожанин (story-движок): карточка с репликой и выбором, затем исход.
 *  На выбор сервер применяет эффекты (золото/репутация/добыча, сдвиги города) и отдаёт дельты. */
export default function StoryVisitor({ story, onResolved, onClose }:
  { story: StoryData; onResolved: (state: unknown) => void; onClose: () => void }) {
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<Outcome | null>(null)
  const newState = useRef<unknown>(null)

  async function choose(i: number) {
    if (busy) return; setBusy(true); haptic('medium')
    try {
      const r = await api<{ text: string; gold: number; rep: number; res: ResLine[]; state: unknown }>(
        'story_choice', { index: i })
      newState.current = r.state
      setOut({ text: r.text, gold: r.gold, rep: r.rep, res: r.res })
      hapticNotify('success')
    } catch {
      hapticNotify('warning'); onClose()   // гость ушёл / выбор недоступен — закрываем
    }
    setBusy(false)
  }
  const done = () => { haptic('light'); onResolved(newState.current) }

  const npc = story.npc
  return (
    <div className="sv-backdrop" onClick={out ? done : onClose}>
      <div className="sv-card" onClick={(e) => e.stopPropagation()}>
        {!out ? (
          <>
            {npc && (
              <div className="sv-npc">
                <span className="sv-npc-emo">{npc.emoji}</span>
                <div className="sv-npc-id">
                  <div className="sv-npc-nm">{npc.name}</div>
                  {npc.blurb && <div className="sv-npc-bl">{npc.blurb}</div>}
                </div>
              </div>
            )}
            {npc && npc.traits.length > 0 && (
              <div className="sv-traits">{npc.traits.map((t) => <span key={t} className="sv-trait">{t}</span>)}</div>
            )}
            <div className="sv-title">{story.title}</div>
            <p className="sv-text">{story.text}</p>
            <div className="sv-choices">
              {story.choices.map((c) => (
                <button key={c.index} className="sv-choice" disabled={busy} onClick={() => choose(c.index)}>
                  <span>{c.label}</span><span className="sv-go">›</span>
                </button>
              ))}
              <button className="sv-later" disabled={busy} onClick={onClose}>🚪 Не сейчас</button>
            </div>
          </>
        ) : (
          <div className="sv-result">
            {npc && <div className="sv-res-emo">{npc.emoji}</div>}
            <div className="sv-title">{story.title}</div>
            <p className="sv-text">{out.text}</p>
            <div className="sv-deltas">
              {out.gold !== 0 && <span className={`sv-delta ${out.gold > 0 ? 'pos' : 'neg'}`}>{out.gold > 0 ? '+' : ''}{fmt(out.gold)} 🪙</span>}
              {out.rep !== 0 && <span className={`sv-delta ${out.rep > 0 ? 'pos' : 'neg'}`}>{out.rep > 0 ? '+' : ''}{out.rep} ⭐</span>}
              {out.res.map((r) => (
                <span key={r.key} className={`sv-delta ${r.qty > 0 ? 'pos' : 'neg'}`}>
                  <ResIcon k={r.key} emoji={r.emoji} size={16} />{r.qty > 0 ? '+' : ''}{fmt(r.qty)}
                </span>
              ))}
            </div>
            <button className="btn gold sv-done" onClick={done}>Дальше ›</button>
          </div>
        )}
      </div>
    </div>
  )
}
