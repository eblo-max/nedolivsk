import { useState, useEffect, useRef } from 'react'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify, initData } from '../telegram'
import { ResIcon, fmt } from '../components/icons'
import Sheet from '../components/Sheet'
import { MONSTERS, MON_FLIP, HERO, RANGED, type MonMeta, type AnimName } from '../monsters'
import Nightrun from './Nightrun'
import CoachTour, { useFirstVisitTour } from './CoachTour'

// переключатель режимов вылазки (Охота ↔ Ночная ходка)
function VyTabs({ mode, setMode }: { mode: 'hunt' | 'night'; setMode: (m: 'hunt' | 'night') => void }) {
  return (
    <div className="vy-tabs" data-tut="sortie-tabs">
      <button className={mode === 'hunt' ? 'on' : ''} onClick={() => setMode('hunt')}>🏹 Охота</button>
      <button className={mode === 'night' ? 'on' : ''} onClick={() => setMode('night')}>🌙 Ночная ходка</button>
    </div>
  )
}

// ── типы (зеркало webapp _hunt_state / _api_hunt_fight) ──
interface Drop { key?: string; trophy: boolean; lo?: number; hi?: number; chance: number; name?: string; emoji?: string; label?: string }
interface Beast {
  id: string; emoji: string; name: string; hp: number; attack: number; armor: number
  gold: [number, number]; rep: number; blurb: string; traits: string[]; regional: boolean
  win: number; est_hp: number; threat: { icon: string; label: string }; drops: Drop[]; sprite?: string
}
interface HealOpt { key: string; name: string; emoji: string; hp: number; qty: number }
interface HuntState {
  ok: boolean; closed?: boolean; note?: string
  hp: { cur: number; max: number; regen: number }; ready: { can: boolean; minutes: number }
  stats: { damage: number; crit: number; armor: number; luck: number }
  heal: { can: boolean; full: boolean; options: HealOpt[] }; beasts: Beast[]
  flask?: { slots: number; options: FlaskOpt[] }
}
interface FlaskOpt { key: string; name: string; emoji: string; label: string; qty: number }
interface Round {
  pd: number; crit: boolean; miss: boolean; ed: number; php: number; ehp: number
  burn?: number; stunned?: boolean; stun_next?: boolean; volley?: boolean
  lifesteal?: number; enrage?: boolean; charge?: boolean; plated?: boolean
  stoneskin?: boolean; chill?: number
}
interface FightRes {
  ok: boolean; win: boolean; elite: boolean; enemy: { name: string; emoji: string; hp: number; sprite?: string; traits?: string[] }
  player_hp0: number; hp_max: number; rounds: Round[]; rounds_n: number; crits: number; overwhelmed: boolean
  loot: { gold: number; res: { key: string; name: string; emoji: string; qty: number }[]; trophies: string[]; rep: number }
  gold_lost: number; hp_now: number; hunt: HuntState; flask?: string[]
}

const TRAIT: Record<string, string> = {
  venom: '☠ ядовит', evasive: '💨 увёртлив', charge: '📯 наскок', enrage: '💢 ярость',
  lifesteal: '🧛 кровосос', plated: '🛡 латы', volley: '🏹 дуплет', stoneskin: '🗿 камен. кожа',
  pickpocket: '💰 карманник', burn: '🔥 жар', stun: '🌀 сотрясение', chill: '🥶 стужа',
}
// полные тактические подсказки (как _TRAIT_HINT бота)
const TRAIT_HINT: Record<string, string> = {
  venom: '☠ Ядовит — бьёт сквозь броню. Спасает сбитень-антидот из фляги, уворот или быстрый занос.',
  evasive: '💨 Увёртлив — уводит часть твоих ударов. Нужен запас урона/крита.',
  charge: '📯 Наскок — первые раунды бьёт в полтора раза злее. Возьми запас здоровья и переживи разгон.',
  enrage: '💢 Ярость — на последней трети здоровья звереет. Добивай быстро: эль и крит в флягу.',
  lifesteal: '🧛 Кровосос — лечится твоей кровью. Уворачивайся (мёд) и бей на убой.',
  plated: '🛡 Латы — твои криты о него гаснут. Решает только чистый урон.',
  volley: '🏹 Дуплет — каждый третий раунд стреляет дважды. Держи броню и уворот.',
  stoneskin: '🗿 Каменная кожа — криты не множатся. Стакай сырой урон.',
  pickpocket: '💰 Карманник — проиграешь: обчистит вдвое. Победишь: заберёшь с наваром.',
  burn: '🔥 Жар — каждый твой удар обжигает сквозь броню. Кончай бой быстро, бери здоровье.',
  stun: '🌀 Сотрясение — четвёртый удар оглушает (пропустишь свой). Спасает уворот.',
  chill: '🥶 Стужа — укусы морозят руки: урон тает. Затяжной бой — смерть.',
}
const threatCls = (w: number) => (w >= 70 ? 'g' : w >= 40 ? 'y' : w >= 10 ? 'o' : 'r')
const hm = (m: number) => { const h = Math.floor(m / 60), mm = m % 60; return h ? `${h} ч ${mm} мин` : `${mm} мин` }

const SAMPLE: HuntState = {
  ok: true, hp: { cur: 26, max: 35, regen: 18 }, ready: { can: true, minutes: 0 },
  stats: { damage: 33, crit: 7, armor: 16, luck: 4 },
  heal: { can: true, full: false, options: [{ key: 'roast', name: 'Жаркое', emoji: '🍖', hp: 12, qty: 3 }] },
  beasts: [
    { id: 'zayac', emoji: '👁', name: 'Летучий Глаз', hp: 8, attack: 2, armor: 0, gold: [3, 12], rep: 0, blurb: 'Можно и голыми руками.', traits: [], regional: false, win: 100, est_hp: 34, threat: { icon: '🟢', label: 'лёгкая добыча' }, sprite: 'flying_eye', drops: [{ key: 'game', trophy: false, lo: 2, hi: 4, chance: 100, name: 'Дичь', emoji: '🥩' }] },
    { id: 'volk', emoji: '🐺', name: 'Цербер', hp: 40, attack: 7, armor: 2, gold: [16, 32], rep: 0, blurb: 'Кусается и юлит — нужен урон.', traits: ['evasive'], regional: false, win: 82, est_hp: 18, threat: { icon: '🟢', label: 'уверенно' }, sprite: 'cerberus', drops: [{ key: 'game', trophy: false, lo: 4, hi: 7, chance: 100, name: 'Дичь', emoji: '🥩' }, { key: 'fang', trophy: false, lo: 1, hi: 2, chance: 30, name: 'Клык', emoji: '🦷' }] },
    { id: 'ataman', emoji: '🐉', name: 'Дракон', hp: 215, attack: 30, armor: 13, gold: [190, 360], rep: 4, blurb: 'Гроза тракта. С него — перстень.', traits: [], regional: false, win: 22, est_hp: 6, threat: { icon: '🟠', label: 'опасно' }, sprite: 'dragon', drops: [{ key: 'ore', trophy: false, lo: 8, hi: 14, chance: 100, name: 'Руда', emoji: '⛏️' }, { key: 'ring', trophy: false, lo: 1, hi: 1, chance: 25, name: 'Перстень', emoji: '💍' }] },
  ],
}

const SORTIE_TOUR = [
  { sel: '[data-tut="sortie-tabs"]', emoji: '⚔️', title: 'Две вылазки',
    body: 'Охота — бой со зверьём ради шкур, мяса и золота. Ночная ходка — рискованный поход по тёмным тропам за большим кушем. Переключайся тут.', place: 'bottom' as const },
  { sel: '[data-tut="beasts"]', emoji: '🏹', title: 'Выбор добычи',
    body: 'На доске розыска — звери с прогнозом победы. Бери по силам: цвет подсказывает опасность. Перед боем можно хлебнуть флягу (эль — урон, вино — крит) для перевеса.', place: 'top' as const },
  { emoji: '🩹', title: 'Риск и лечение',
    body: 'Проиграешь — потеряешь здоровье и щепотку золота, и будешь ранен (пауза перед следующим боем). Лечись едой из погреба (значок 🍖). Копи снарягу — и берись за крупную дичь.' },
]

export default function Sorties() {
  const sortieTour = useFirstVisitTour('sorties')
  const { data, loading, error, set, reload } = useApi<HuntState>('hunt', SAMPLE)
  const [pick, setPick] = useState<Beast | null>(null)
  const [fight, setFight] = useState<FightRes | null>(null)
  const [step, setStep] = useState(-1)
  const [healOpen, setHealOpen] = useState(false)
  const [flaskSel, setFlaskSel] = useState<string[]>([])   // фляга: до 2 порций на бой
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const [mode, setMode] = useState<'hunt' | 'night'>('hunt')
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200) }

  // анимация боя: прокручиваем раунды, последний → итог
  useEffect(() => {
    if (!fight) return
    setStep(-1)
    const n = fight.rounds.length
    // пауза раунда с запасом под обмен ударами (фаза A+B ≈ 720 мс); длинные бои чуть быстрее
    const iv = Math.max(620, Math.min(900, Math.round(6400 / Math.max(1, n))))
    let i = -1
    let t: ReturnType<typeof setTimeout>
    const tick = () => {
      i += 1; setStep(i)
      haptic(fight.rounds[i]?.crit ? 'heavy' : 'light')
      if (i < n - 1) {
        // слоу-мо: после крита держим кадр дольше (кинематографичность)
        const wait = fight.rounds[i]?.crit ? Math.round(iv * 1.55) : iv
        t = setTimeout(tick, wait)
      } else setTimeout(() => hapticNotify(fight.win ? 'success' : 'error'), 220)
    }
    t = setTimeout(tick, 1150)   // 1-я пауза = интро-вспышка «VS»
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
      const r = await api<FightRes>('hunt_fight', { id: b.id, flask: flaskSel })
      set(r.hunt); setFight(r)
    } catch (e) {
      if (import.meta.env.DEV && !initData()) { setFight(synthFight(b, d)); return }   // dev-превью: демо-бой
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
  if (error && error !== 'no_tavern' && !import.meta.env.DEV) return (
    <div className="center" style={{ flex: 1, flexDirection: 'column', gap: 14, padding: 26, textAlign: 'center' }}>
      <div className="muted" style={{ fontStyle: 'italic' }}>Не удалось загрузить охоту.</div>
      <button className="btn gold" style={{ maxWidth: 220 }} onClick={() => reload()}>Повторить</button>
    </div>
  )
  const d = data ?? SAMPLE

  if (mode === 'night') return (
    <div className="scr">
      <VyTabs mode={mode} setMode={setMode} />
      <Nightrun />
    </div>
  )

  if (fight) return (
    <div className="scr">
      {toast && <div className="toast">{toast}</div>}
      <FightView fight={fight} step={step} onClose={() => { setFight(null); reload() }} />
    </div>
  )

  return (
    <div className="scr">
      {sortieTour.show && mode === 'hunt' && (
        <CoachTour steps={SORTIE_TOUR} onDone={sortieTour.finish} endLabel="Понятно" />
      )}
      {toast && <div className="toast">{toast}</div>}
      <VyTabs mode={mode} setMode={setMode} />
      <div className="hero rise" style={{ paddingBottom: 0 }}>
        <div className="nm">Доска розыска</div>
        <div className="flavor" style={{ margin: '6px 14px 0', fontSize: 13.5 }}>«Гляди, кого нынче ищут на тракте. Возьми голову — возьми и награду.»</div>
      </div>

      {data?.closed ? (
        <div className="board" style={{ textAlign: 'center', padding: '26px 18px' }}>
          <div style={{ fontSize: 40 }}>🛠</div>
          <div className="nm" style={{ marginTop: 8 }}>Охота на переучёте</div>
          <p className="flavor" style={{ margin: '10px 4px 0', fontSize: 14 }}>
            «{data?.note || 'Обновление механики и новых фич боёвки. Откроется в течение 3 часов.'}»
          </p>
        </div>
      ) : (
      <>

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

        <div className="posters" data-tut="beasts">
          {d.beasts.map((b, i) => (
            <button key={b.id} className={`poster th-${threatCls(b.win)}`}
              style={{ transform: `rotate(${(i % 2 ? 1 : -1) * (0.7 + (i % 3) * 0.5)}deg)`, marginLeft: i % 2 ? 10 : 0, marginRight: i % 2 ? 0 : 10, zIndex: 10 + i }}
              onClick={() => { haptic('light'); setPick(b) }}>
              <div className="poster-paper">
                <div className="poster-head">— РАЗЫСКИВАЕТСЯ —{b.regional && <em> · здешний</em>}</div>
                <div className="poster-row">
                  {b.sprite && MONSTERS[b.sprite]
                    ? <div className="poster-mug"><Sprite path={`monsters/${b.sprite}`} meta={MONSTERS[b.sprite]} anim="idle" token={0}
                        height={Math.min(58, Math.round(78 * MONSTERS[b.sprite].fh / MONSTERS[b.sprite].fw))} flip={!!MON_FLIP[b.sprite]} animate={false} /></div>
                    : <span className="poster-emo">{b.emoji}</span>}
                  <div className="poster-id">
                    <span className="poster-name">{b.name}</span>
                    <span className="poster-danger">угроза: {b.threat.label} · сила ❤{b.hp}{b.traits.length ? ` · ${b.traits.map((t) => TRAIT[t] || t).join(', ')}` : ''}</span>
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
        <Sheet title={`${pick.emoji} ${pick.name}`} onClose={() => { setPick(null); setFlaskSel([]) }}>
          <BeastBrief b={pick} hp={d.hp} ready={d.ready} busy={busy} onHunt={() => hunt(pick)}
            flask={d.flask} sel={flaskSel} setSel={setFlaskSel} />
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
      </>
      )}
    </div>
  )
}

// ── Бриф зверя ───────────────────────────────────────────────────────────
function BeastBrief({ b, hp, ready, busy, onHunt, flask, sel, setSel }: { b: Beast; hp: { cur: number; max: number }; ready: { can: boolean; minutes: number }; busy: boolean; onHunt: () => void; flask?: { slots: number; options: FlaskOpt[] }; sel: string[]; setSel: (s: string[]) => void }) {
  const toggle = (k: string) => {
    const i = sel.indexOf(k)
    if (i >= 0) setSel(sel.filter((_, j) => j !== i))
    else if (sel.length < (flask?.slots ?? 2)) setSel([...sel, k])
  }
  // живой прогноз с флягой: «что в прогнозе — то и в бою», включая выпитое
  const [boost, setBoost] = useState<{ win: number; est: number } | null>(null)
  useEffect(() => {
    if (!sel.length) { setBoost(null); return }
    let dead = false
    api<{ ok: boolean; win: number; est_hp: number }>('hunt_forecast', { id: b.id, flask: sel })
      .then((r) => { if (!dead && r.ok) setBoost({ win: r.win, est: r.est_hp }) })
      .catch(() => { if (!dead) setBoost(null) })
    return () => { dead = true }
  }, [sel, b.id])
  return (
    <>
      {b.sprite && MONSTERS[b.sprite]
        ? <div className="brief-sprite"><Sprite path={`monsters/${b.sprite}`} meta={MONSTERS[b.sprite]} anim="idle" token={0} height={104} flip={!!MON_FLIP[b.sprite]} /></div>
        : <div className="brief-emo">{b.emoji}</div>}
      <p className="bd-desc">{b.blurb}</p>
      <div className="cap">зверь</div>
      <div className="kv-list">
        <div className="kv"><span>Здоровье</span><b>❤ {b.hp}</b></div>
        <div className="kv"><span>Атака · броня</span><b>⚔ {b.attack} · 🛡 {b.armor}</b></div>
      </div>

      {b.traits.map((t) => TRAIT_HINT[t] && (
        <p key={t} className="trait-hint">{TRAIT_HINT[t]}</p>
      ))}

      <div className="cap">твой расклад</div>
      <div className="kv-list">
        <div className="kv"><span>Шанс победы</span><b className={`win-${threatCls(boost ? boost.win : b.win)}`}>
          {b.threat.icon} {boost && boost.win !== b.win
            ? <>{b.win}% <span className="win-shift">→ {boost.win}%</span></>
            : <>{b.win}%</>} · {b.threat.label}</b></div>
        <div className="kv"><span>При здоровье</span><b>❤ {hp.cur}/{hp.max}</b></div>
        {b.win > 0 && <div className="kv"><span>Останется при победе</span><b>≈ {b.est_hp}/{hp.max}</b></div>}
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

      {flask && flask.options.length > 0 && (
        <>
          <div className="cap">фляга — в бой ({sel.length}/{flask.slots})</div>
          <div className="flask-row">
            {flask.options.map((o) => {
              const n = sel.filter((k) => k === o.key).length
              return (
                <button key={o.key} className={`flask-opt${n ? ' on' : ''}`} disabled={busy || (!n && sel.length >= flask.slots) || n >= o.qty}
                  onClick={() => { haptic('light'); toggle(o.key) }}>
                  <span className="fo-emo">{o.emoji}{n > 1 ? `×${n}` : ''}</span>
                  <span className="fo-nm">{o.name}</span>
                  <span className="fo-eff">{o.label}</span>
                </button>
              )
            })}
          </div>
        </>
      )}

      <button className="btn danger" style={{ marginTop: 14 }} disabled={busy || !ready.can} onClick={onHunt}>
        {ready.can ? '⚔ Охотиться!' : `Ранен — ${hm(ready.minutes)}`}
      </button>
    </>
  )
}

// демо-бой для офлайн-превью (вне Telegram): грубая симуляция ради анимации
function synthFight(b: Beast, d: HuntState): FightRes {
  const hpMax = d.hp.max; let php = d.hp.cur; let ehp = b.hp
  const win = b.win >= 50
  const pdmg = Math.max(3, d.stats.damage - b.armor)
  const edmg = Math.max(1, b.attack - d.stats.armor)
  const rounds: Round[] = []; let crits = 0
  for (let i = 0; i < 14 && php > 0 && ehp > 0; i++) {
    const crit = (i % 4 === 2); if (crit) crits++
    const miss = b.traits.includes('evasive') && i % 3 === 1
    const pd = miss ? 0 : Math.round(pdmg * (crit ? 1.8 : 1) * (win ? 1.2 : 0.7))
    ehp = Math.max(0, ehp - pd)
    const ed = ehp > 0 ? Math.round(edmg * (win ? 0.7 : 1.3)) : 0
    php = Math.max(win ? 1 : 0, php - ed)
    rounds.push({ pd, crit, miss, ed, php, ehp })
    if (ehp <= 0 || php <= 0) break
  }
  return {
    ok: true, win, elite: false, enemy: { name: b.name, emoji: b.emoji, hp: b.hp, sprite: b.sprite, traits: b.traits },
    player_hp0: d.hp.cur, hp_max: hpMax, rounds, rounds_n: rounds.length, crits, overwhelmed: !win,
    loot: { gold: win ? Math.round((b.gold[0] + b.gold[1]) / 2) : 0, res: win ? b.drops.filter((x) => !x.trophy).map((x) => ({ key: x.key!, name: x.name!, emoji: x.emoji!, qty: x.lo || 1 })) : [], trophies: [], rep: win ? b.rep : 0 },
    gold_lost: win ? 0 : 8, hp_now: php, hunt: d,
  }
}

// ── Анимированный спрайт (лента кадров fw×fh, шаги по кадрам) ──────────────
function Sprite({ path, meta, anim, token, height, flip, animate = true }: {
  path: string; meta: MonMeta; anim: AnimName; token: number; height: number; flip: boolean; animate?: boolean
}) {
  const [frame, setFrame] = useState(0)
  const n = meta[anim] || 1
  useEffect(() => {
    setFrame(0)
    // на доске розыска ~10 спрайтов разом: НЕ анимируем (статичный 1-й кадр),
    // иначе на слабом Android ~100 ререндеров/сек → фриз. Анимация — в карточке/бою.
    if (!animate || n <= 1) return
    const loop = anim === 'idle' || anim === 'run'
    // фиксированная длительность клипа (мс) → кадр = длительность/кадры:
    // любой клип успевает доиграть внутри раунда вне зависимости от числа кадров
    const DUR: Record<AnimName, number> = { idle: 1000, attack: 320, hurt: 230, death: 600, run: 620 }
    // лупам (idle/run) — пол кадра 90мс: на доске розыска до ~11 спрайтов разом,
    // не частим ререндерами; в фоне (hidden) кадр не двигаем (батарея/джанк)
    const interval = Math.max(loop ? 90 : 16, DUR[anim] / n)
    let f = 0
    const id = setInterval(() => {
      if (loop && document.hidden) return
      f += 1
      if (f >= n) {
        if (loop) { f = 0 } else { clearInterval(id); setFrame(n - 1); return }
      }
      setFrame(f)
    }, interval)
    return () => clearInterval(id)
    // token заставляет переиграть даже ту же анимацию (hurt 2 раунда подряд)
  }, [anim, token, n, animate])
  const scale = height / meta.fh
  return (
    <div className="ep-sprite" style={{
      width: meta.fw * scale, height,
      backgroundImage: `url(${import.meta.env.BASE_URL}${path}/${anim}.webp)`,
      backgroundSize: `${n * 100}% 100%`,
      backgroundPosition: n > 1 ? `${(frame / (n - 1)) * 100}% 0` : '0 0',
      transform: flip ? 'scaleX(-1)' : undefined,
    }} />
  )
}

// ── Вспышка попадания (лист hit.webp = 3 кадра 16×16), одноразовая ─────────
function Burst({ token, x, y }: { token: number; x: string; y: string }) {
  const [f, setF] = useState(0)
  useEffect(() => {
    if (!token) return
    setF(0); let i = 0
    const id = setInterval(() => { i += 1; if (i >= 3) { clearInterval(id); setF(2); return } setF(i) }, 65)
    return () => clearInterval(id)
  }, [token])
  if (!token) return null
  return <div className="ep-burst" key={token} style={{
    left: x, top: y, backgroundImage: `url(${import.meta.env.BASE_URL}fx/hit.webp)`,
    backgroundPosition: `${(f / 2) * 100}% 0`,
  }} />
}

// ── Бой: кинематографичная арена (герой против зверя) ─────────────────────
function FightView({ fight, step, onClose }: { fight: FightRes; step: number; onClose: () => void }) {
  const r = step >= 0 ? fight.rounds[Math.min(step, fight.rounds.length - 1)] : null
  const php = r ? r.php : fight.player_hp0
  const ehp = r ? r.ehp : fight.enemy.hp
  const phpPct = Math.max(0, Math.min(100, (php / fight.hp_max) * 100))
  const ehpPct = Math.max(0, Math.min(100, (ehp / fight.enemy.hp) * 100))
  const done = step >= fight.rounds.length - 1
  // Усталость от вылазки (HUNT_EXERTION): любой бой стоит минимум HP. Если зверь
  // нанёс меньше — разница уходит на усталость. Подписываем ОТДЕЛЬНО, иначе игрок
  // видит падение HP после лёгкого 1-шота и думает, что зверь его «тайно» ударил.
  const enemyDmg = fight.rounds.reduce((a, r) => a + (r.ed || 0), 0)
  const fatigue = Math.max(0, fight.player_hp0 - fight.hp_now - enemyDmg)
  const arenaRef = useRef<HTMLDivElement>(null)

  const skey = fight.enemy.sprite
  const meta = skey ? MONSTERS[skey] : undefined
  const projAsset = skey ? RANGED[skey] : undefined   // дальнобойный? → ассет снаряда
  const foeTraits = fight.enemy.traits || []          // черты зверя (☠ ядовит / 💨 увёртлив)
  const venom = foeTraits.includes('venom')
  const evasive = foeTraits.includes('evasive')

  // хореография раунда: монстр бьёт (снаряд/ближний → вспышка на герое) →
  // герой отвечает (вспышка на монстре); победа → death, поражение → побег героя
  const [monAnim, setMonAnim] = useState<AnimName>('idle')
  const [heroAnim, setHeroAnim] = useState<AnimName>('idle')
  const [proj, setProj] = useState(0)        // токен снаряда в полёте
  const [sparkHero, setSparkHero] = useState(0)
  const [sparkFoe, setSparkFoe] = useState(0)
  const [flee, setFlee] = useState(false)
  useEffect(() => {
    if (step < 0 || !r) { setMonAnim('idle'); setHeroAnim('idle'); setProj(0); return }
    const mHits = r.ed > 0, hHits = r.pd > 0, ranged = !!projAsset
    const t: ReturnType<typeof setTimeout>[] = []
    setProj(0)
    // фаза A — монстр бьёт
    if (mHits) {
      setMonAnim('attack'); setHeroAnim('idle')
      if (ranged) {
        t.push(setTimeout(() => setProj(step + 1), 150))                                  // пуск снаряда
        t.push(setTimeout(() => { setHeroAnim('hurt'); setSparkHero(step + 1) }, 440))    // прилёт
      } else {
        t.push(setTimeout(() => { setHeroAnim('hurt'); setSparkHero(step + 1) }, 180))    // ближний контакт
      }
    } else { setMonAnim('idle'); setHeroAnim('idle') }
    // фаза B — ответ героя
    const dB = mHits ? (projAsset ? 560 : 380) : 100
    t.push(setTimeout(() => {
      if (done && !fight.win) { setHeroAnim('run'); setFlee(true); setMonAnim('attack') }  // побег
      else {
        setHeroAnim('attack')
        if (done && fight.win) setMonAnim('death')
        else setMonAnim(hHits ? 'hurt' : 'idle')
      }
    }, dB))
    if ((done && fight.win) || hHits) t.push(setTimeout(() => setSparkFoe(step + 1), dB + 170))  // удар героя достиг
    if (!done) t.push(setTimeout(() => { setMonAnim('idle'); setHeroAnim('idle') }, dB + 380))
    return () => t.forEach(clearTimeout)
    // только на смену раунда; done/win/projAsset/r стабильны в пределах боя
  }, [step]) // eslint-disable-line react-hooks/exhaustive-deps

  // тряска + крит-зум (сильнее на крите и добивающем ударе); уважаем reduce-motion
  useEffect(() => {
    if (step < 0 || !r || !arenaRef.current) return
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const big = r.crit || (done && fight.win)
    const a = big ? 11 : (r.pd > 0 || r.ed > 0) ? 5 : 0
    if (!a && !big) return
    const sc = big ? 1.06 : 1
    arenaRef.current.animate([
      { transform: 'translate(0,0) scale(1)' },
      { transform: `translate(${a}px,${-a}px) scale(${sc})`, offset: 0.25 },
      { transform: `translate(${-a}px,${a / 2}px) scale(${sc * 0.99})`, offset: 0.6 },
      { transform: 'translate(0,0) scale(1)' },
    ], { duration: big ? 460 : 200, easing: 'ease-out' })
  }, [step, r, done, fight.win])

  // события черт текущего раунда → всплывающие бейджи (кто: foe|hero)
  const events: { txt: string; side: 'foe' | 'hero'; cls: string }[] = []
  if (r) {
    if (r.charge) events.push({ txt: '📯 наскок!', side: 'foe', cls: 'warn' })
    if (r.enrage) events.push({ txt: '💢 РАЗЪЯРИЛСЯ!', side: 'foe', cls: 'danger' })
    if (r.volley) events.push({ txt: '🏹 дуплет ×2', side: 'foe', cls: 'warn' })
    if (r.lifesteal) events.push({ txt: `🧛 +${r.lifesteal}`, side: 'foe', cls: 'heal' })
    if (r.plated) events.push({ txt: '🛡 крит погашен', side: 'foe', cls: 'block' })
    if (r.stoneskin) events.push({ txt: '🗿 крит не множится', side: 'foe', cls: 'block' })
    if (r.burn) events.push({ txt: `🔥 ожог −${r.burn}`, side: 'hero', cls: 'danger' })
    if (r.stunned) events.push({ txt: '🌀 оглушён!', side: 'hero', cls: 'danger' })
    if (r.stun_next) events.push({ txt: '🌀 звенит в голове…', side: 'hero', cls: 'warn' })
    if (r.chill) events.push({ txt: `🥶 стужа ×${r.chill}`, side: 'hero', cls: 'warn' })
  }

  return (
    <div className="ep">
      <button className="lnk-back" onClick={onClose}>‹ Назад</button>
      <div className={`ep-arena ${fight.elite ? 'elite' : ''}`} ref={arenaRef}>
        {events.length > 0 && (
          <div className="ep-events" key={step} aria-hidden>
            {events.map((e, i) => (
              <span key={i} className={`ep-ev ${e.side} ${e.cls}`}
                style={{ animationDelay: `${i * 0.12}s` }}>{e.txt}</span>
            ))}
          </div>
        )}
        <div className="ep-embers" aria-hidden="true">
          {Array.from({ length: 9 }).map((_, i) => <i key={i} style={{ left: `${7 + i * 10.5}%`, animationDelay: `${i * 0.5}s`, animationDuration: `${4 + (i % 3)}s` }} />)}
        </div>

        <div className="ep-hp foe">
          <span className="ep-hp-nm">{fight.enemy.name}</span>
          {foeTraits.length > 0 && (
            <span className="ep-traits">{foeTraits.map((t) => (
              <em key={t} className={`ep-trait ${t}`}>{TRAIT[t] || t}</em>
            ))}</span>
          )}
          <div className="ep-bar e"><i className="gh" style={{ width: `${ehpPct}%` }} /><i className="fl" style={{ width: `${ehpPct}%` }} /></div>
        </div>

        {/* монстр — СЛЕВА, лицом к герою */}
        <div className={`ep-foe ${fight.elite ? 'elite' : ''} ${monAnim === 'death' ? 'dead' : monAnim === 'attack' ? 'atk' : ''}`}>
          {meta && skey
            ? <Sprite path={`monsters/${skey}`} meta={meta} anim={monAnim} token={step} height={132} flip={!!MON_FLIP[skey]} />
            : <div className={`ep-foe-emo ${r ? (r.crit ? 'k-crit' : r.pd > 0 ? 'k-hit' : '') : ''}`} key={'f' + step}>{fight.enemy.emoji}</div>}
          {r && r.pd > 0 && <div className={`ep-slash ${r.crit ? 'crit' : ''}`} key={'s' + step} />}
          {r && (r.pd > 0
            ? <div className={`ep-dmg foe ${r.crit ? 'crit' : ''}`} key={'d' + step}>−{r.pd}{r.crit && <b>КРИТ!</b>}</div>
            : <div className="ep-dmg miss" key={'d' + step}>{evasive ? '💨 увернулся' : 'мимо'}</div>)}
        </div>

        {/* летящий снаряд дальнобойного зверя (слева → направо, к герою) */}
        {proj === step + 1 && projAsset && (
          <div className="ep-proj" key={'p' + step} style={{ backgroundImage: `url(${import.meta.env.BASE_URL}fx/${projAsset}.webp)` }} />
        )}
        <Burst token={sparkFoe} x="22%" y="54%" />
        <Burst token={sparkHero} x="76%" y="52%" />

        <div className="ep-mid">{done ? (fight.win ? '🏆' : '💀') : `РАУНД ${step + 1}`}</div>

        {/* герой — СПРАВА, лицом к монстру (зеркалим: спрайт смотрит вправо) */}
        <div className={`ep-hero ${flee ? 'flee' : ''}`}>
          <Sprite path="character/hero" meta={HERO} anim={heroAnim} token={step} height={156} flip />
          {r && r.ed > 0 && <div className={`ep-dmg me ${venom ? 'venom' : ''}`} key={'e' + step}>−{r.ed}{venom && <b>☠</b>}</div>}
        </div>

        <div className="ep-hp me">
          <div className="ep-bar p"><i className="gh" style={{ width: `${phpPct}%` }} /><i className="fl" style={{ width: `${phpPct}%` }} /></div>
          <span className="ep-hp-nm">Ты · {php}/{fight.hp_max}</span>
        </div>

        {/* интро-вспышка «VS» перед первым раундом */}
        {step < 0 && (
          <div className="ep-intro" key="intro">
            <div className="ep-intro-vs">⚔ VS ⚔</div>
            <div className="ep-intro-nm">{fight.enemy.name}</div>
            {fight.elite && <div className="ep-intro-el">РЕДКИЙ ПРОТИВНИК</div>}
          </div>
        )}

        {done && <div className={`ep-flash ${fight.win ? 'win' : 'lose'}`} />}
      </div>

      {done && (
        <div className={`ep-result ${fight.win ? 'win' : 'lose'}`}>
          {fight.win && <div className="ep-rays" aria-hidden="true" />}
          <div className={`ep-res-h${fight.win && fight.elite ? ' rare' : ''}`}>{fight.win ? (fight.elite ? '✨ РЕДКАЯ ДОБЫЧА' : 'ПОБЕДА') : 'ПОРАЖЕНИЕ'}</div>
          {fight.win ? (
            <>
              {fight.flask && fight.flask.length > 0 && <div className="ep-flask">🍺 Фляга: {fight.flask.join(' · ')}</div>}
              <div className="ep-tally">🗡 Уложил за {fight.rounds_n} р.{fight.crits > 0 ? ` · ${fight.crits} крит.` : ''} · осталось ❤{fight.hp_now}/{fight.hp_max}{fatigue > 0 ? ` · 😮‍💨 устал −${fatigue}` : ''}</div>
              <div className="ep-loot">
                {fight.loot.gold > 0 && <span className="ep-loot-i" style={{ animationDelay: '0s' }}><ResIcon k="gold" size={22} />+{fmt(fight.loot.gold)}</span>}
                {fight.loot.res.map((x, i) => <span key={x.key} className="ep-loot-i" style={{ animationDelay: `${(i + 1) * 0.09}s` }}><ResIcon k={x.key} emoji={x.emoji} size={22} />+{x.qty}</span>)}
                {fight.loot.rep > 0 && <span className="ep-loot-i">⭐ +{fight.loot.rep}</span>}
                {fight.loot.trophies.map((t, i) => <span key={i} className="ep-loot-i">🏆 {t}</span>)}
              </div>
            </>
          ) : (
            <div className="ep-lose-body">
              <p className="ep-tally">«{fight.overwhelmed ? `${fight.enemy.name} оказался не по зубам — еле уволок ноги.` : `${fight.enemy.name} подмял тебя на ${fight.rounds_n}-м раунде.`}»</p>
              <div className="muted" style={{ textAlign: 'center' }}>🩸 Еле выполз — ❤{fight.hp_now}/{fight.hp_max}{fight.gold_lost > 0 ? ` · обронил −${fmt(fight.gold_lost)} 🪙` : ''}. Отлёживайся, здоровье вернётся.</div>
            </div>
          )}
          <button className="btn gold" onClick={onClose}>← К бестиарию</button>
        </div>
      )}
    </div>
  )
}
