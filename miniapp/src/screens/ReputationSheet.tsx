import { useEffect, useState } from 'react'
import { api } from '../api'
import { haptic } from '../telegram'

interface Faction { id: string; name: string; emoji: string; value: number; rank: string; tone: string; member: boolean; perks?: string[]; rank_title?: string }
interface NpcRel { id: string; name: string; emoji: string; blurb: string; avatar: number | null; value: number; rank: string; tone: string }

/** Биполярная шкала −100..100: заливка от центра вправо (друг) / влево (враг). */
function RepBar({ value, tone }: { value: number; tone: string }) {
  const w = Math.min(50, Math.abs(value) / 2)               // полтрека = ±100
  const pos = value >= 0
  return (
    <div className="rep-bar">
      <span className="rep-bar-mid" />
      <i className={`rep-fill ${tone}`} style={pos ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }} />
    </div>
  )
}

function RepAvatar({ avatar, emoji }: { avatar: number | null; emoji: string }) {
  const [fail, setFail] = useState(false)
  if (avatar && !fail) return <img className="rep-av" src={`${import.meta.env.BASE_URL}npc/${avatar}.png`} alt="" onError={() => setFail(true)} />
  return <span className="rep-av rep-av-emo">{emoji}</span>
}

/** Экран репутации игрока: расклад у фракций + отношения с горожанами. */
export default function ReputationSheet({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<{ factions: Faction[]; npcs: NpcRel[] } | null>(null)
  useEffect(() => {
    api<{ factions: Faction[]; npcs: NpcRel[] }>('reputation')
      .then((r) => setData({ factions: r.factions || [], npcs: r.npcs || [] }))
      .catch(() => setData({ factions: [], npcs: [] }))
  }, [])
  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="rep-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="rep-head">🤝 Репутация</div>
        {data === null ? (
          <div className="center" style={{ padding: '34px 0' }}><div className="spin" /></div>
        ) : (
          <div className="rep-scroll">
            <div className="rep-cap">Фракции города</div>
            <div className="rep-facs">
              {data.factions.map((f) => (
                <div key={f.id} className="rep-frow">
                  <span className="rep-femo">{f.emoji}</span>
                  <div className="rep-fbody">
                    <div className="rep-ftop">
                      <span className="rep-fname">{f.name}</span>
                      {f.member && <span className="rep-mbadge" title="Состоишь в гильдии">🗝</span>}
                      <span className={`rep-rank ${f.tone}`}>{f.rank}</span>
                    </div>
                    <RepBar value={f.value} tone={f.tone} />
                    {(f.perks?.length ?? 0) > 0 && (
                      <div className="rep-perks">{f.perks!.map((p, i) => <span key={i} className="rep-perk">◆ {p}</span>)}</div>
                    )}
                  </div>
                  <span className={`rep-val ${f.tone}`}>{f.value > 0 ? '+' : ''}{f.value}</span>
                </div>
              ))}
            </div>

            <div className="rep-cap">Горожане</div>
            {data.npcs.length === 0 ? (
              <p className="rep-empty">«Ты пока ни с кем не сдружился и не разосрался — серая мышь за стойкой.»</p>
            ) : (
              <div className="rep-npcs">
                {data.npcs.map((n) => (
                  <div key={n.id} className="rep-nrow">
                    <RepAvatar avatar={n.avatar} emoji={n.emoji} />
                    <div className="rep-nbody">
                      <div className="rep-ntop"><span className="rep-nname">{n.name}</span><span className={`rep-rank ${n.tone}`}>{n.rank}</span></div>
                      {n.blurb && <div className="rep-nblurb">{n.blurb}</div>}
                      <RepBar value={n.value} tone={n.tone} />
                    </div>
                    <span className={`rep-val ${n.tone}`}>{n.value > 0 ? '+' : ''}{n.value}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <button className="btn gold rep-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
