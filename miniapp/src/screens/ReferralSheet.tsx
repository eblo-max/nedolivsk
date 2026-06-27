import { useEffect, useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify, openTgLink } from '../telegram'
import { ResIcon } from '../components/icons'

interface Tier { need: number; bonus: number; done: boolean }
interface NextTier { need: number; bonus: number; left: number }
interface TopRow { name: string; count: number; me: boolean }
interface Reward { inviter_gold: number; inviter_rep: number; invitee_gold: number }
interface RefData {
  ok: boolean; link: string; share_url: string; invited: number
  tier: number; tiers: Tier[]; next: NextTier | null; reward: Reward; top: TopRow[]
}

const MEDAL = ['🥇', '🥈', '🥉']

/** Зазывала (рефералка): личная ссылка, прогресс по вехам и топ зазывал.
 * Перенос texts.referral_screen / referrers_screen из текстового бота. */
export default function ReferralSheet({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<RefData | null>(null)
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    api<RefData>('referral').then(setD).catch(() => setD(null))
  }, [])

  function share() {
    if (!d?.share_url) return
    haptic('medium'); openTgLink(d.share_url)
  }
  async function copy() {
    if (!d?.link) return
    haptic('light')
    try { await navigator.clipboard.writeText(d.link); setCopied(true); hapticNotify('success'); setTimeout(() => setCopied(false), 1600) }
    catch { /* старый webview — ссылку видно, скопирует вручную */ }
  }

  // прогресс к следующей вехе (для полоски)
  const prevNeed = d && d.tier > 0 ? d.tiers[d.tier - 1].need : 0
  const pct = d && d.next
    ? Math.max(4, Math.min(100, ((d.invited - prevNeed) / Math.max(1, d.next.need - prevNeed)) * 100))
    : 100

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="zz-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="zz-head">🍻 Зазывала</div>
        {d === null ? (
          <div className="center" style={{ padding: '34px 0' }}><div className="spin" /></div>
        ) : (
          <div className="zz-scroll">
            <p className="zz-pitch">Зови друзей в Недоливск — <b>в выгоде оба</b>.</p>

            <div className="zz-reward">
              <div className="zz-reward-cap">За каждого, кто заведёт кабак:</div>
              <div className="zz-reward-row"><span>Тебе</span><b><ResIcon k="gold" size={15} />+{d.reward.inviter_gold} · ⭐ +{d.reward.inviter_rep}</b></div>
              <div className="zz-reward-row"><span>Другу на старт</span><b><ResIcon k="gold" size={15} />+{d.reward.invitee_gold}</b></div>
            </div>

            <div className="zz-prog">
              <div className="zz-prog-top">
                <span>Приведено друзей: <b>{d.invited}</b></span>
                {d.next
                  ? <span className="zz-prog-goal">до +{d.next.bonus} 🪙 ещё {d.next.left}</span>
                  : <span className="zz-prog-goal zz-legend">все вехи взяты — легенда найма</span>}
              </div>
              <div className="zz-bar"><i style={{ width: `${pct}%` }} /></div>
              <div className="zz-tiers">
                {d.tiers.map((t, i) => (
                  <span key={i} className={`zz-tier ${t.done ? 'done' : d.tier === i ? 'cur' : ''}`}>
                    {t.done ? '✓' : t.need} <small>+{t.bonus}</small>
                  </span>
                ))}
              </div>
            </div>

            <button className="btn gold zz-share" onClick={share} disabled={!d.share_url}>📤 Позвать друга</button>
            {d.link && (
              <button className="zz-link" onClick={copy} title="Нажми, чтобы скопировать">
                <span className="zz-link-url">{d.link}</span>
                <span className="zz-link-act">{copied ? '✓ скопировано' : '⧉ копировать'}</span>
              </button>
            )}

            <div className="zz-cap">🏆 Лучшие зазывалы</div>
            {d.top.length === 0 ? (
              <p className="zz-empty">«Пока тихо — стань первым, кто зазовёт народ в город.»</p>
            ) : (
              <div className="zz-top">
                {d.top.map((r, i) => (
                  <div key={i} className={`zz-trow${r.me ? ' me' : ''}`}>
                    <span className="zz-medal">{MEDAL[i] ?? `${i + 1}.`}</span>
                    <span className="zz-tname">{r.name}{r.me && <span className="zz-you"> · это ты</span>}</span>
                    <span className="zz-tcount">{r.count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <button className="btn zz-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
