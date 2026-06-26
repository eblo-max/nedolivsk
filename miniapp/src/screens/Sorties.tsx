import { useState, useEffect, useRef } from 'react'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify, initData } from '../telegram'
import { ResIcon, fmt } from '../components/icons'
import Sheet from '../components/Sheet'

// ── типы (зеркало webapp _hunt_state / _api_hunt_fight) ──
interface Drop { key?: string; trophy: boolean; lo?: number; hi?: number; chance: number; name?: string; emoji?: string; label?: string }
interface Beast {
  id: string; emoji: string; name: string; hp: number; attack: number; armor: number
  gold: [number, number]; rep: number; blurb: string; traits: string[]; regional: boolean
  win: number; est_hp: number; threat: { icon: string; label: string }; drops: Drop[]
}
interface HealOpt { key: string; name: string; emoji: string; hp: number; qty: number }
interface HuntState {
  ok: boolean; hp: { cur: number; max: number; regen: number }; ready: { can: boolean; minutes: number }
  stats: { damage: number; crit: number; armor: number; luck: number }
  heal: { can: boolean; full: boolean; options: HealOpt[] }; beasts: Beast[]
}
interface Round { pd: number; crit: boolean; miss: boolean; ed: number; php: number; ehp: number }
interface FightRes {
  ok: boolean; win: boolean; elite: boolean; enemy: { name: string; emoji: string; hp: number }
  player_hp0: number; hp_max: number; rounds: Round[]
  loot: { gold: number; res: { key: string; name: string; emoji: string; qty: number }[]; trophies: string[]; rep: number }
  gold_lost: number; hp_now: number; hunt: HuntState
}

const TRAIT: Record<string, string> = { venom: '☠ ядовит', evasive: '💨 увёртлив' }
const threatCls = (w: number) => (w >= 70 ? 'g' : w >= 40 ? 'y' : w >= 10 ? 'o' : 'r')
const hm = (m: number) => { const h = Math.floor(m / 60), mm = m % 60; return h ? `${h} ч ${mm} мин` : `${mm} мин` }

const SAMPLE: HuntState = {
  ok: true, hp: { cur: 26, max: 35, regen: 18 }, ready: { can: true, minutes: 0 },
  stats: { damage: 33, crit: 7, armor: 16, luck: 4 },
  heal: { can: true, full: false, options: [{ key: 'roast', name: 'Жаркое', emoji: '🍖', hp: 12, qty: 3 }] },
  beasts: [
    { id: 'zayac', emoji: '🐰', name: 'Заяц', hp: 8, attack: 2, armor: 0, gold: [3, 12], rep: 0, blurb: 'Можно и голыми руками.', traits: [], regional: false, win: 100, est_hp: 34, threat: { icon: '🟢', label: 'лёгкая добыча' }, drops: [{ key: 'game', trophy: false, lo: 2, hi: 4, chance: 100, name: 'Дичь', emoji: '🥩' }] },
    { id: 'volk', emoji: '🐺', name: 'Волк', hp: 40, attack: 7, armor: 2, gold: [16, 32], rep: 0, blurb: 'Кусается и юлит — нужен урон.', traits: ['evasive'], regional: false, win: 82, est_hp: 18, threat: { icon: '🟢', label: 'уверенно' }, drops: [{ key: 'game', trophy: false, lo: 4, hi: 7, chance: 100, name: 'Дичь', emoji: '🥩' }, { key: 'fang', trophy: false, lo: 1, hi: 2, chance: 30, name: 'Клык', emoji: '🦷' }] },
    { id: 'ataman', emoji: '👹', name: 'Атаман', hp: 215, attack: 30, armor: 13, gold: [190, 360], rep: 4, blurb: 'Гроза тракта. С него — перстень.', traits: [], regional: false, win: 22, est_hp: 6, threat: { icon: '🟠', label: 'опасно' }, drops: [{ key: 'ore', trophy: false, lo: 8, hi: 14, chance: 100, name: 'Руда', emoji: '⛏️' }, { key: 'ring', trophy: false, lo: 1, hi: 1, chance: 25, name: 'Перстень', emoji: '💍' }] },
  ],
}

export default function Sorties() {
  const { data, loading, error, set, reload } = useApi<HuntState>('hunt', SAMPLE)
  const [pick, setPick] = useState<Beast | null>(null)
  const [fight, setFight] = useState<FightRes | null>(null)
  const [step, setStep] = useState(-1)
  const [healOpen, setHealOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200) }

  // анимация боя: прокручиваем раунды, последний → итог
  useEffect(() => {
    if (!fight) return
    setStep(-1)
    const n = fight.rounds.length
    const iv = Math.max(360, Math.min(800, Math.round(3200 / Math.max(1, n))))
    let i = -1
    let t: ReturnType<typeof setTimeout>
    const tick = () => {
      i += 1; setStep(i)
      haptic(fight.rounds[i]?.crit ? 'heavy' : 'light')
      if (i < n - 1) t = setTimeout(tick, iv)
      else setTimeout(() => hapticNotify(fight.win ? 'success' : 'error'), 220)
    }
    t = setTimeout(tick, 420)
    return () => clearTimeout(t)
  }, [fight])

  // тихий реалтайм HP/реген, пока меню открыто и ничего не идёт
  const guard = useRef({ busy, pick: !!pick, fight: !!fight, healOpen })
  guard.current = { busy, pick: !!pick, fight: !!fight, healOpen }
  useEffect(() => {
    const refresh = () => { const g = guard.current; if (document.visibilityState === 'visible' && !g.busy && !g.pick && !g.fight && !g.healOpen) reload() }
    const iv = setInterval(refresh, 20000)
    document.addEventListener('visibilitychange', refresh)
    return () => { clearInterval(iv); document.removeEventListener('visibilitychange', refresh) }
  }, [reload])

  async function hunt(b: Beast) {
    if (busy) return
    setBusy(true); haptic('medium'); setPick(null)
    try {
      const r = await api<FightRes>('hunt_fight', { id: b.id })
      set(r.hunt); setFight(r)
    } catch (e) {
      const code = (e as { code?: string })?.code
      flash(code === 'lowhp' ? 'Слишком ранен — отлёживайся' : 'Не вышло'); hapticNotify('warning')
    } finally { setBusy(false) }
  }

  async function heal(key: string) {
    if (busy) return
    setBusy(true); haptic('light')
    try { await api('heal', { key }); reload(); hapticNotify('success') }
    catch { flash('Нечем подлечиться') }
    finally { setBusy(false) }
  }

  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  if (error && error !== 'no_tavern' && initData()) return (
    <div className="center" style={{ flex: 1, flexDirection: 'column', gap: 14, padding: 26, textAlign: 'center' }}>
      <div className="muted" style={{ fontStyle: 'italic' }}>Не удалось загрузить охоту.</div>
      <button className="btn gold" style={{ maxWidth: 220 }} onClick={() => reload()}>Повторить</button>
    </div>
  )
  const d = data ?? SAMPLE

  if (fight) return (
    <div className="scr">
      {toast && <div className="toast">{toast}</div>}
      <FightView fight={fight} step={step} onClose={() => { setFight(null); reload() }} />
    </div>
  )

  return (
    <div className="scr">
      {toast && <div className="toast">{toast}</div>}
      <div className="hero rise" style={{ paddingBottom: 0 }}>
        <div className="nm">Доска розыска</div>
        <div className="flavor" style={{ margin: '6px 14px 0', fontSize: 13.5 }}>«Гляди, кого нынче ищут на тракте. Возьми голову — возьми и награду.»</div>
      </div>

      <div className="board">
        <div className="board-head">
          <img className="board-hero" src={`${import.meta.env.BASE_URL}character/hero_static.png`} alt="" onError={(e) => { e.currentTarget.style.display = 'none' }} />
          <div className="board-hunter">
            <div className="bh-top"><span className="bh-hp"><b>{d.hp.cur}</b><small>/{d.hp.max} ❤</small></span><span className="bh-rg">{d.hp.regen > 0 ? hm(d.hp.regen) : 'в строю'}</span></div>
            <div className="ep-bar p bh-bar"><i style={{ width: `${Math.max(0, Math.min(100, (d.hp.cur / d.hp.max) * 100))}%` }} /></div>
            <div className="bh-stats"><i>⚔ {d.stats.damage}</i><i>💥 {d.stats.crit}%</i><i>🛡 {d.stats.armor}</i><i>🍀 {d.stats.luck}</i></div>
          </div>
          {d.heal.can && <button className="hunter-heal" disabled={busy || !d.heal.options.length} onClick={() => setHealOpen(true)} aria-label="Подлечиться">🍖</button>}
        </div>
        {!d.ready.can && <div className="bh-warn">⚠ Ранен — в строй через {hm(d.ready.minutes)}</div>}

        <div className="posters">
          {d.beasts.map((b, i) => (
            <button key={b.id} className={`poster th-${threatCls(b.win)}`}
              style={{ transform: `rotate(${(i % 2 ? 1 : -1) * (0.7 + (i % 3) * 0.5)}deg)`, marginLeft: i % 2 ? 10 : 0, marginRight: i % 2 ? 0 : 10, zIndex: 10 + i }}
              onClick={() => { haptic('light'); setPick(b) }}>
              <div className="poster-paper">
                <div className="poster-head">— РАЗЫСКИВАЕТСЯ —{b.regional && <em> · здешний</em>}</div>
                <div className="poster-row">
                  <span className="poster-emo">{b.emoji}</span>
                  <div className="poster-id">
                    <span className="poster-name">{b.name}</span>
                    <span className="poster-danger">угроза: {b.threat.label}{b.traits.length ? ` · ${b.traits.map((t) => TRAIT[t] || t).join(', ')}` : ''}</span>
                  </div>
                </div>
                <div className="poster-foot">
                  <span className="poster-reward"><ResIcon k="gold" size={15} />{b.gold[0]}–{b.gold[1]}</span>
                  <span className="poster-drops">{b.drops.slice(0, 3).map((dr, k) => dr.trophy
                    ? <span key={k}>🏆</span> : <ResIcon key={k} k={dr.key!} emoji={dr.emoji} size={14} />)}</span>
                </div>
              </div>
              <span className="nail" />
              <span className="seal"><b>{b.win}<small>%</small></b></span>
            </button>
          ))}
        </div>
      </div>

      {pick && (
        <Sheet title={`${pick.emoji} ${pick.name}`} onClose={() => setPick(null)}>
          <BeastBrief b={pick} ready={d.ready} busy={busy} onHunt={() => hunt(pick)} />
        </Sheet>
      )}
      {healOpen && (
        <Sheet title="🍖 Подлечиться" onClose={() => setHealOpen(false)}>
          <p className="bd-desc">Еда и питьё из погреба восстанавливают здоровье.</p>
          <div className="kv-list">
            {d.heal.options.map((o) => (
              <button key={o.key} className="heal-opt" disabled={busy} onClick={() => heal(o.key)}>
                <span>{o.emoji} {o.name}</span><b>+{o.hp} ❤ · ×{o.qty}</b>
              </button>
            ))}
            {!d.heal.options.length && <p className="muted" style={{ fontStyle: 'italic' }}>В погребе пусто — приготовь еду на кухне/в пекарне.</p>}
          </div>
        </Sheet>
      )}
    </div>
  )
}

// ── Бриф зверя ───────────────────────────────────────────────────────────
function BeastBrief({ b, ready, busy, onHunt }: { b: Beast; ready: { can: boolean; minutes: number }; busy: boolean; onHunt: () => void }) {
  return (
    <>
      <div className="brief-emo">{b.emoji}</div>
      <p className="bd-desc">{b.blurb}</p>
      <div className="kv-list">
        <div className="kv"><span>Здоровье зверя</span><b>{b.hp}</b></div>
        <div className="kv"><span>Атака · броня</span><b>{b.attack} · {b.armor}</b></div>
        <div className="kv"><span>Твой шанс</span><b className={`win-${threatCls(b.win)}`}>{b.threat.icon} {b.win}% · {b.threat.label}</b></div>
        <div className="kv"><span>Останется HP при победе</span><b>≈ {b.est_hp}</b></div>
        {b.traits.length > 0 && <div className="kv"><span>Особенность</span><b>{b.traits.map((t) => TRAIT[t] || t).join(', ')}</b></div>}
      </div>

      <div className="cap">добыча</div>
      <div className="kv-list">
        <div className="kv"><span><ResIcon k="gold" size={17} />Золото</span><b className="win-g">{b.gold[0]}–{b.gold[1]}</b></div>
        {b.drops.map((dr, i) => (
          <div key={i} className="kv">
            <span>{dr.trophy ? '🏆 ' : <ResIcon k={dr.key!} emoji={dr.emoji} size={17} />}{dr.trophy ? dr.label : dr.name}</span>
            <b className="muted">{dr.trophy ? '' : `×${dr.lo}${dr.hi! > dr.lo! ? '–' + dr.hi : ''} · `}{dr.chance >= 100 ? 'всегда' : dr.chance + '%'}</b>
          </div>
        ))}
        {b.rep > 0 && <div className="kv"><span>⭐ Репутация</span><b className="win-g">+{b.rep}</b></div>}
      </div>

      <button className="btn danger" style={{ marginTop: 14 }} disabled={busy || !ready.can} onClick={onHunt}>
        {ready.can ? '⚔ Охотиться!' : `Ранен — ${hm(ready.minutes)}`}
      </button>
    </>
  )
}

// ── Бой: кинематографичная арена (герой против зверя) ─────────────────────
function FightView({ fight, step, onClose }: { fight: FightRes; step: number; onClose: () => void }) {
  const r = step >= 0 ? fight.rounds[Math.min(step, fight.rounds.length - 1)] : null
  const php = r ? r.php : fight.player_hp0
  const ehp = r ? r.ehp : fight.enemy.hp
  const phpPct = Math.max(0, Math.min(100, (php / fight.hp_max) * 100))
  const ehpPct = Math.max(0, Math.min(100, (ehp / fight.enemy.hp) * 100))
  const done = step >= fight.rounds.length - 1
  const hero = `${import.meta.env.BASE_URL}character/hero_static.png`
  const arenaRef = useRef<HTMLDivElement>(null)

  // тряска экрана на удар (сильнее на крите); уважаем prefers-reduced-motion
  useEffect(() => {
    if (step < 0 || !r || !arenaRef.current) return
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const a = r.crit ? 11 : (r.pd > 0 || r.ed > 0) ? 5 : 0
    if (!a) return
    arenaRef.current.animate(
      [{ transform: 'translate(0,0)' }, { transform: `translate(${a}px,${-a}px)` }, { transform: `translate(${-a}px,${a / 2}px)` }, { transform: 'translate(0,0)' }],
      { duration: r.crit ? 340 : 200, easing: 'ease-out' })
  }, [step, r])

  return (
    <div className="ep">
      <button className="lnk-back" onClick={onClose}>‹ Назад</button>
      <div className="ep-arena" ref={arenaRef}>
        <div className="ep-embers" aria-hidden="true">
          {Array.from({ length: 9 }).map((_, i) => <i key={i} style={{ left: `${7 + i * 10.5}%`, animationDelay: `${i * 0.5}s`, animationDuration: `${4 + (i % 3)}s` }} />)}
        </div>

        <div className="ep-hp foe">
          <span className="ep-hp-nm">{fight.elite ? '✨ ' : ''}{fight.enemy.name}</span>
          <div className="ep-bar e"><i style={{ width: `${ehpPct}%` }} /></div>
        </div>

        <div className="ep-foe">
          <div className={`ep-foe-emo ${r ? (r.crit ? 'k-crit' : r.pd > 0 ? 'k-hit' : '') : ''}`} key={'f' + step}>{fight.enemy.emoji}</div>
          {r && r.pd > 0 && <div className={`ep-slash ${r.crit ? 'crit' : ''}`} key={'s' + step} />}
          {r && (r.pd > 0
            ? <div className={`ep-dmg foe ${r.crit ? 'crit' : ''}`} key={'d' + step}>−{r.pd}{r.crit && <b>КРИТ!</b>}</div>
            : <div className="ep-dmg miss" key={'d' + step}>мимо</div>)}
        </div>

        <div className="ep-mid">{done ? (fight.win ? '🏆' : '💀') : `РАУНД ${step + 1}`}</div>

        <div className="ep-hero" key={'h' + step}>
          <img src={hero} alt="" onError={(e) => { e.currentTarget.style.display = 'none' }} />
          {r && r.ed > 0 && <div className="ep-dmg me" key={'e' + step}>−{r.ed}</div>}
        </div>

        <div className="ep-hp me">
          <div className="ep-bar p"><i style={{ width: `${phpPct}%` }} /></div>
          <span className="ep-hp-nm">Ты · {php}/{fight.hp_max}</span>
        </div>

        {done && <div className={`ep-flash ${fight.win ? 'win' : 'lose'}`} />}
      </div>

      {done && (
        <div className={`ep-result ${fight.win ? 'win' : 'lose'}`}>
          {fight.win && <div className="ep-rays" aria-hidden="true" />}
          <div className="ep-res-h">{fight.win ? (fight.elite ? '✨ РЕДКАЯ ДОБЫЧА' : 'ПОБЕДА') : 'ПОРАЖЕНИЕ'}</div>
          {fight.win ? (
            <div className="ep-loot">
              {fight.loot.gold > 0 && <span className="ep-loot-i" style={{ animationDelay: '0s' }}><ResIcon k="gold" size={22} />+{fmt(fight.loot.gold)}</span>}
              {fight.loot.res.map((x, i) => <span key={x.key} className="ep-loot-i" style={{ animationDelay: `${(i + 1) * 0.09}s` }}><ResIcon k={x.key} emoji={x.emoji} size={22} />+{x.qty}</span>)}
              {fight.loot.rep > 0 && <span className="ep-loot-i">⭐ +{fight.loot.rep}</span>}
              {fight.loot.trophies.map((t, i) => <span key={i} className="ep-loot-i">🏆 {t}</span>)}
            </div>
          ) : (
            <div className="muted" style={{ textAlign: 'center' }}>Потеряно {fmt(fight.gold_lost)} 🪙. Раны затянутся — отлежись и подлечись.</div>
          )}
          <button className="btn gold" onClick={onClose}>← К бестиарию</button>
        </div>
      )}
    </div>
  )
}
