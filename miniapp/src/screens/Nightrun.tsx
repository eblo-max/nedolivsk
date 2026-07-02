import { useState, useEffect, useRef, type CSSProperties } from 'react'
import lottie from 'lottie-web/build/player/lottie_light'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify, initData } from '../telegram'
import { music } from '../music'
import { ResIcon, fmt } from '../components/icons'

// ── типы (зеркало webapp _nightrun_state / _nr_out) ──
interface NItem { key: string; name: string; emoji: string; qty: number }
interface NFork { kind: string; emoji: string; name: string; risky: boolean; hint: string; success: number; risk: number; reward: number; stat: string | null }
interface NRun {
  leg: number; state: string; hp: number; hp_max: number; satchel: NItem[]; satchel_value: number
  situation: string | null; can_push: boolean; rest_heal: number; next_value: number; growth: number
  fork?: NFork[]; meet?: { npc: string; scene: string; options: { id: string; label: string }[] }
  quiz?: { q: string; options: string[] }
}
interface NState { ok: boolean; cooldown: number; active: boolean; max_legs: number; stats: { armor: number; luck: number }; run: NRun | null
  flask?: { key: string; name: string; emoji: string; hint: string; qty: number }[] }
interface NOut {
  kind: string; busted: boolean; loot: NItem[]; hp_cost: number; healed: number; roll?: number | null
  lose_faces?: number | null; collapsed: boolean; lost?: NItem[]; correct?: boolean
  factions?: { faction: string; delta: number }[]; npc?: string; story?: string
}

const SITUATION: Record<string, { t: string; cls: string }> = {
  curfew: { t: '🚨 Облава! Стража злее голодной собаки', cls: 'bad' },
  thieves_rampant: { t: '🗡 Ворьё гуляет, держи кошель крепче', cls: 'bad' },
  merchant_boom: { t: '💰 Обозы жирные, хапай пока дают', cls: 'good' },
}
const hms = (s: number) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h} ч ${m} мин` : `${m} мин ${s % 60} с` }

// СВОЙ фон и место на КАЖДЫЙ этап — чем дальше в ночь, тем мрачнее (лор)
const SCENES = [
  { bg: 'town', name: 'Окраина', icon: '🏘' },
  { bg: 'forest', name: 'Опушка леса', icon: '🌲' },
  { bg: 'forest2', name: 'Глухая чаща', icon: '🌫' },
  { bg: 'ruins', name: 'Старый погост', icon: '🪦' },
  { bg: 'ruins2', name: 'Сердце руин', icon: '🏚' },
  { bg: 'ruins2', name: 'Бездна', icon: '🔥' },
]
const sceneFor = (leg: number) => SCENES[Math.min(Math.max(leg, 1), SCENES.length) - 1]
const STAT_LABEL: Record<string, string> = { armor: '🛡 решает броня', luck: '🍀 решает удача' }

// ── Лор зон + движок повествования (живая хроника ночи) ──
const ZONE_LORE: Record<string, string> = {
  town: 'Город спит мёртвым сном. Ты выскальзываешь за околицу — туда, где правит иной закон.',
  forest: 'Опушка встречает шорохом. Лес смыкается за спиной — назад дороги уже не разобрать.',
  forest2: 'Туман глотает звуки и тропы. Где-то ухает сыч. Каждый шаг — как по тонкому льду.',
  ruins: 'Старый погост дышит холодом. Здесь хоронили тех, кого не отпели. Камни помнят дурное.',
  ruins2: 'В самом сердце руин ворочается мрак. Самое жирное добро — и самая лютая цена.',
}
const _pick = (a: string[]) => a[Math.floor(Math.random() * a.length)]
function narrate(out: NOut): string {
  if (out.busted) {
    if (out.collapsed) return _pick(['Ты одолел врага — да рухнул без сил. Очнулся: котомка пуста, тьма хохочет.', 'Победа далась дорого — свет померк, а пробудился уже обчищенным дочиста.'])
    if (out.kind === 'gamble') return _pick(['Кости легли худо. Картавый осклабился и выгреб всё подчистую.', 'Не свезло на костях — и вот ты с пустыми руками среди ночи.'])
    return _pick(['На тёмной тропе тебя подстерегли. Очнулся — ни котомки, ни обидчиков.', 'Беда вынырнула из мрака внезапно. Унесли всё, что нажил за ночь.'])
  }
  switch (out.kind) {
    case 'fight': return _pick(['Из тьмы метнулись тени — но твоя сталь была быстрее. Добыча твоя, да рёбрам досталось.', 'Засада! Короткая злая схватка — и тракт снова твой. Кровь чужая, синяки свои.'])
    case 'sneak': return _pick(['Ты вжался в тень у плетня и пропустил беду мимо. Тихо, как тать.', 'Ни ветка не хрустнула. Проскользнул мимо опасности — и подобрал, что плохо лежало.'])
    case 'gamble': return _pick(['Кости стукнули о камень и легли в твою пользу. Картавый нехотя отсыпал долю.', 'Фортуна нынче на твоей стороне — бросок вышел знатный.'])
    case 'find': return _pick(['Под корягой блеснуло — кто-то припрятал, да не вернулся. Теперь твоё.', 'Старый схрон у приметного камня. Немного, да на дороге не валяется.'])
    case 'rest': return _pick(['Ты развёл огонёк в укрытии и перевёл дух. Раны затянулись, на душе полегчало.', 'Короткий привал у костра вернул силы. Ночь подождёт.'])
    case 'meet': return _pick([`На тракте — ${out.npc || 'некто'}. Слово за слово, и сделка слажена. Город запомнит твой выбор.`, `Встреча в ночи свела тебя с ${out.npc || 'прохожим'}. Ты решил по-своему.`])
    case 'quiz': return out.correct ? _pick(['Ведьма щерилась, да загадка тебе по зубам. За верный ответ — щедрый куш.', 'Ты разгадал хитрость старухи — и она, шипя, отсыпала обещанное.']) : _pick(['Ведьма расхохоталась: «Мимо!» Но хоть без потерь.', 'Ответ вышел кривой. Старуха лишь погрозила клюкой.'])
  }
  return 'Ночь идёт своим чередом.'
}

// плавный счётчик (модерн-полировка)
function useCounter(target: number, ms = 600): number {
  const [v, setV] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    const a = from.current, t0 = performance.now(); let raf = 0
    const step = (t: number) => { const k = Math.min(1, (t - t0) / ms); setV(Math.round(a + (target - a) * (1 - (1 - k) * (1 - k)))); if (k < 1) raf = requestAnimationFrame(step); else from.current = target }
    raf = requestAnimationFrame(step); return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return v
}

// печатная машинка (живой рассказ)
function Typewriter({ text, speed = 20 }: { text: string; speed?: number }) {
  const [n, setN] = useState(0)
  useEffect(() => { setN(0); let i = 0; const id = setInterval(() => { i += 1; setN(i); if (i >= text.length) clearInterval(id) }, speed); return () => clearInterval(id) }, [text, speed])
  return <span>{text.slice(0, n)}{n < text.length && <span className="nr-caret" />}</span>
}

const SAMPLE: NState = {
  ok: true, cooldown: 0, active: false, max_legs: 6, stats: { armor: 12, luck: 4 }, run: null,
}

// ── Офлайн-движок для превью (вне Telegram): мок поведения бэка ──
function offState(run: NRun | null, cooldown = 0): NState {
  return { ...SAMPLE, cooldown, active: !!run, run }
}
function offStart(): NRun {
  return { leg: 1, state: 'fork', hp: 35, hp_max: 35, satchel: [], satchel_value: 0, situation: 'merchant_boom', can_push: true, rest_heal: 14, next_value: Math.round(25 * 1.45), growth: 1.45, fork: offFork(1) }
}
function offFork(leg: number): NFork[] {
  const base = Math.round(25 * Math.pow(1.45, leg - 1))
  const mk = (kind: string, emoji: string, name: string, risky: boolean, hint: string, success: number, mult: number, stat: string | null): NFork =>
    ({ kind, emoji, name, risky, hint, success, risk: risky ? 100 - success : 0, reward: Math.round(base * mult), stat })
  const all: NFork[] = [
    mk('fight', '⚔️', 'Засада', true, 'Сила и броня решают. Победа стоит здоровья.', Math.max(45, 90 - leg * 6), 1, 'armor'),
    mk('gamble', '🎲', 'Лихо', true, 'Бросок костей: куш или обчистят.', Math.max(40, 82 - leg * 6), 1.4, null),
    mk('sneak', '🌒', 'Тишком', true, 'Удача — проскользнуть мимо беды.', Math.max(45, 88 - leg * 6), 1, 'luck'),
    mk('meet', '🗣', 'Встреча', false, 'Выбор и сдвиг сил города. Без бюста.', 100, 1, null),
    mk('quiz', '❓', 'Загадка', false, 'Угадал — куш. Без бюста.', 100, 1.5, null),
    mk('rest', '🔥', 'Привал', false, 'Лечит. Добычи нет.', 100, 0, null),
    mk('find', '💰', 'Схрон', false, 'Малая добыча. Безопасно.', 100, 0.6, null),
  ]
  const pick = [all[(leg * 2) % all.length], all[(leg * 2 + 3) % all.length]]
  return pick[0].kind === pick[1].kind ? [pick[0], all[(leg + 1) % all.length]] : pick
}

export default function Nightrun() {
  const { data, loading, error, set, reload } = useApi<NState>('nightrun', SAMPLE)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')
  const [out, setOut] = useState<NOut | null>(null)   // резолв-оверлей (анимация исхода)
  const [end, setEnd] = useState<{ kind: 'bust' | 'bank'; out?: NOut; banked?: NItem[]; value?: number } | null>(null)
  const [chron, setChron] = useState<string[]>([])    // хроника ночи (летопись забега)
  const beat = (s: string) => setChron((c) => [...c, s])
  const narr = (o: NOut) => { o.story = narrate(o); beat(o.story); return o }
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200) }
  const off = !initData()
  // музыка: на ночной ходке — тёмно-эпичный набор, по выходу — обратно к трактирному
  useEffect(() => { music.setScene('night'); return () => music.setScene('tavern') }, [])

  // живой кулдаун-таймер
  const [, tick] = useState(0)
  useEffect(() => { const i = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(i) }, [])

  // лор: вошёл в новую зону — добавить строку в хронику
  const prevZone = useRef<string | null>(null)
  useEffect(() => {
    const r = data?.run
    if (!r) { prevZone.current = null; return }
    const z = sceneFor(r.leg).bg
    if (z !== prevZone.current) {
      if (prevZone.current !== null) beat(ZONE_LORE[z])
      prevZone.current = z
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.run?.leg])

  const d = data ?? SAMPLE
  const run = d.run
  const bgName = run ? sceneFor(run.leg).bg : 'city'   // свой фон на этап (интро — город)
  const nrbg = { '--nr-bg': `url(${import.meta.env.BASE_URL}nightrun/${bgName}.webp)` } as CSSProperties

  async function call<T = NState>(path: string, body: Record<string, unknown> = {}): Promise<T | null> {
    try { return await api<T>(path, body) } catch (e) {
      if (off) return null
      flash((e as { code?: string })?.code === 'cooldown' ? 'Ноги ещё гудят — отдышись' : 'Не вышло'); hapticNotify('warning'); return null
    }
  }

  const [flaskSel, setFlaskSel] = useState<string[]>([])
  async function start() {
    if (busy) return; setBusy(true); haptic('medium'); setChron([ZONE_LORE.town])
    if (off) { set(offState(offStart())); setBusy(false); return }
    const r = await call<NState>('nightrun/start', flaskSel.length ? { flask: flaskSel } : {})
    if (r) set(r); setBusy(false)
  }
  function resolveOut(o: NOut, ns: NState) {
    setOut(narr(o)); set(ns)
    if (o.busted) setEnd({ kind: 'bust', out: o })
  }
  async function pick(f: NFork) {
    if (busy || !run) return; setBusy(true); haptic('medium')
    if (off) { offPick(f); setBusy(false); return }
    const r = await call<{ out: NOut; nightrun: NState }>('nightrun/pick', { kind: f.kind })
    if (r) { (f.kind === 'meet' || f.kind === 'quiz') ? set(r.nightrun) : resolveOut(r.out, r.nightrun) } else reload()
    setBusy(false)
  }
  async function meet(optId: string) {
    if (busy) return; setBusy(true); haptic('medium')
    if (off) { offMeet(optId); setBusy(false); return }
    const r = await call<{ out: NOut; nightrun: NState }>('nightrun/meet', { opt: optId })
    if (r) resolveOut(r.out, r.nightrun); else reload()
    setBusy(false)
  }
  async function quiz(ans: number) {
    if (busy) return; setBusy(true); haptic('medium')
    if (off) { offQuiz(ans); setBusy(false); return }
    const r = await call<{ out: NOut; nightrun: NState }>('nightrun/quiz', { answer: ans })
    if (r) resolveOut(r.out, r.nightrun); else reload()
    setBusy(false)
  }
  async function push() {
    if (busy) return; setBusy(true); haptic('medium'); setOut(null)
    if (off && run) { const leg = run.leg + 1; set(offState({ ...run, leg, state: 'fork', fork: offFork(leg) })); setBusy(false); return }
    const r = await call<NState>('nightrun/push'); if (r) set(r); else reload(); setBusy(false)
  }
  async function bank() {
    if (busy || !run) return; setBusy(true); haptic('medium'); setOut(null)
    if (off) { setEnd({ kind: 'bank', banked: run.satchel, value: run.satchel_value }); setBusy(false); return }
    // банк особый: если ответ-успех потерялся (таймаут/повтор), забег на сервере уже свёрнут
    // (добыча начислена) → трактуем 'stale' как успех и ресинкаемся, а не пугаем «Не вышло».
    try {
      const r = await api<{ banked: NItem[]; value: number; nightrun: NState }>('nightrun/bank')
      setEnd({ kind: 'bank', banked: r.banked, value: r.value }); set(r.nightrun)
    } catch (e) {
      const code = (e as { code?: string })?.code
      if (code === 'cooldown') flash('Ноги ещё гудят — отдышись')
      else { flash(code === 'stale' ? 'Забег свёрнут — добыча уже в таверне' : 'Связь подвисла — сверяюсь с сервером'); hapticNotify('warning'); reload() }
    }
    setBusy(false)
  }

  // ── офлайн-моки исходов (только для превью) ──
  function offLoot(mult = 1): NItem[] {
    const v = Math.round(25 * Math.pow(1.45, (run?.leg || 1) - 1) * mult)
    return [{ key: 'gold', name: 'Золото', emoji: '🪙', qty: Math.round(v * 0.35) }, { key: 'grain', name: 'Зерно', emoji: '🌾', qty: Math.max(1, Math.round(v * 0.4 / 3)) }]
  }
  function offCross(extra: Partial<NRun>, loot: NItem[]) {
    if (!run) return
    const sat = [...run.satchel]; loot.forEach((l) => { const e = sat.find((x) => x.key === l.key); if (e) e.qty += l.qty; else sat.push({ ...l }) })
    set(offState({ ...run, ...extra, state: 'crossroad', satchel: sat, next_value: Math.round(25 * Math.pow(1.45, run.leg)), satchel_value: sat.reduce((a, x) => a + (x.key === 'gold' ? x.qty : x.qty * 3), 0) }))
  }
  function offPick(f: NFork) {
    if (!run) return
    if (f.kind === 'meet') { set(offState({ ...run, state: 'meet', meet: { npc: '🥷 Контрабандист Тихушкин', scene: 'из темноты шипят: «Эй, хозяин… товар не нужен? Дёшево, мимо застав».', options: [{ id: 'buy', label: '🤝 Взять товар' }, { id: 'turn', label: '🛡 Сдать страже' }] } })); return }
    if (f.kind === 'quiz') { set(offState({ ...run, state: 'quiz', quiz: { q: '🔮 Ведьма щерится: «Что в кабаке льётся рекой, а наутро аукается башкой?»', options: ['Вода', 'Эль', 'Дождь', 'Слёзы должника'] } })); return }
    const ok = Math.random() * 100 < f.success
    if (f.risky && !ok) { const o: NOut = { kind: f.kind, busted: true, loot: [], hp_cost: 0, healed: 0, collapsed: false, lost: run.satchel, roll: f.kind === 'gamble' ? Math.ceil(Math.random() * 2) : null, lose_faces: 2 }; setOut(narr(o)); setEnd({ kind: 'bust', out: o }); return }
    if (f.kind === 'rest') { const heal = Math.min(run.rest_heal, run.hp_max - run.hp); const o: NOut = { kind: 'rest', busted: false, loot: [], hp_cost: 0, healed: heal, collapsed: false }; setOut(narr(o)); offCross({ hp: run.hp + heal }, []); return }
    const loot = offLoot(f.kind === 'find' ? 0.6 : f.kind === 'gamble' ? 1.4 : 1)
    let hp = run.hp; const cost = f.kind === 'fight' ? 4 + run.leg + Math.floor(Math.random() * 6) : 0; hp -= cost
    const o: NOut = { kind: f.kind, busted: false, loot, hp_cost: cost, healed: 0, collapsed: false, roll: f.kind === 'gamble' ? 3 + Math.floor(Math.random() * 3) : null, lose_faces: f.kind === 'gamble' ? 2 : null }
    setOut(narr(o)); offCross({ hp }, loot)
  }
  function offMeet(optId: string) { const mult = optId === 'buy' ? 1.6 : 1.0; const loot = offLoot(mult); const o: NOut = { kind: 'meet', busted: false, loot, hp_cost: 0, healed: 0, collapsed: false, npc: '🥷 Контрабандист', factions: [{ faction: 'thieves', delta: optId === 'buy' ? 4 : -4 }] }; setOut(narr(o)); if (run) offCross({}, loot) }
  function offQuiz(ans: number) { const correct = ans === 1; const loot = correct ? offLoot(1.5) : []; const o: NOut = { kind: 'quiz', busted: false, loot, hp_cost: 0, healed: 0, collapsed: false, correct }; setOut(narr(o)); if (run) offCross({}, loot) }

  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  if (error && error !== 'no_tavern' && initData()) return (
    <div className="center" style={{ flex: 1, flexDirection: 'column', gap: 14, padding: 26 }}>
      <div className="muted" style={{ fontStyle: 'italic' }}>Тракт во мгле — не загрузилось.</div>
      <button className="btn gold" style={{ maxWidth: 220 }} onClick={() => reload()}>Повторить</button>
    </div>
  )

  // ── проигрышный БРОСОК: даём нативному кубику докатиться до проигрышной грани, затем финал (по «Дальше») ──
  if (out && out.kind === 'gamble' && out.busted) return (
    <div className="nr" style={nrbg}>
      <div className="nr-bgfix" key={bgName} aria-hidden="true" />
      {toast && <div className="toast">{toast}</div>}
      <NrResolve out={out} onNext={() => setOut(null)} />
    </div>
  )

  // ── финал (бюст / банк) ──
  if (end) return (
    <div className="nr" style={nrbg}>
      <div className="nr-bgfix" key={bgName} aria-hidden="true" />
      {toast && <div className="toast">{toast}</div>}
      <NrEnd end={end} chron={chron} onClose={() => { setEnd(null); setOut(null); setChron([]); if (off) set(offState(null, end.kind === 'bank' ? 4 * 3600 : 4 * 3600)); else reload() }} />
    </div>
  )

  // ── резолв-оверлей (анимация исхода испытания) ──
  if (out && run && run.state === 'crossroad') return (
    <div className="nr" style={nrbg}>
      <div className="nr-bgfix" key={bgName} aria-hidden="true" />
      {toast && <div className="toast">{toast}</div>}
      <NrResolve out={out} onNext={() => setOut(null)} />
    </div>
  )

  return (
    <div className="nr" style={nrbg}>
      <div className="nr-bgfix" key={bgName} aria-hidden="true" />
      {toast && <div className="toast">{toast}</div>}
      {!d.active && <NrIntro d={d} busy={busy} onStart={start} flaskSel={flaskSel} onFlask={(k) => setFlaskSel((c) => c.includes(k) ? c.filter((x) => x !== k) : c.length < 2 ? [...c, k] : c)} />}
      {run && run.state === 'fork' && <NrFork d={d} run={run} busy={busy} onPick={pick} />}
      {run && run.state === 'meet' && <NrMeet run={run} busy={busy} onPick={meet} />}
      {run && run.state === 'quiz' && <NrQuiz run={run} busy={busy} onAnswer={quiz} />}
      {run && run.state === 'crossroad' && !out && <NrCross run={run} chron={chron} busy={busy} onPush={push} onBank={bank} />}
    </div>
  )
}

// ── плавающий HUD ходки: без коробки, текст поверх сцены (язык «раскол сцены») ──
function NrTopHud({ run, max }: { run: NRun; max: number }) {
  const sc = sceneFor(run.leg)
  const sat = useCounter(run.satchel_value)
  return (
    <div className="nr-top">
      <div className="nr-top-zone">{sc.icon} {sc.name} <i>· этап {run.leg}/{max}</i></div>
      <div className="nr-top-prog">
        {Array.from({ length: max }, (_, i) => (
          <span key={i} className={`nr-seg ${i + 1 < run.leg ? 'done' : i + 1 === run.leg ? 'now' : ''}`} />
        ))}
      </div>
      <div className="nr-top-stats">
        <span className="nr-hp">❤️ <b>{run.hp}</b><small>/{run.hp_max}</small></span>
        <span className="nr-dot">·</span>
        <span className="nr-sat">🎒 <b>{fmt(sat)}</b><small>🪙-экв</small></span>
      </div>
    </div>
  )
}

// ── РАСКОЛ СЦЕНЫ: две тапающиеся половины мира (fork / встреча / перекрёсток) ──
interface SplitSide { key: string; emoji: string; name: string; sub?: string; note?: string; tag?: string; reward?: number; tone: 'risk' | 'safe' | 'gold' | 'cool'; onPick: () => void }
function NrSplit({ left, right, busy, note }: { left: SplitSide; right: SplitSide; busy: boolean; note?: string }) {
  return (
    <div className="nr-split">
      <button className={`nr-half L ${left.tone}`} disabled={busy} onClick={() => { haptic('medium'); left.onPick() }}>
        <span className="nr-half-in"><HalfBody s={left} /></span>
      </button>
      <button className={`nr-half R ${right.tone}`} disabled={busy} onClick={() => { haptic('medium'); right.onPick() }}>
        <span className="nr-half-in"><HalfBody s={right} /></span>
      </button>
      <div className="nr-seam" aria-hidden="true" />
      {note && <div className="nr-split-note">{note}</div>}
    </div>
  )
}
function HalfBody({ s }: { s: SplitSide }) {
  return (
    <>
      <span className="nr-half-emo">{s.emoji}</span>
      <span className="nr-half-nm">{s.name}</span>
      {s.sub && <span className="nr-half-sub">{s.sub}</span>}
      {s.tag && <span className={`nr-half-tag ${s.tone}`}>{s.tag}</span>}
      {!!s.reward && s.reward > 0 && <span className="nr-half-rew">+{fmt(s.reward)} <small>🪙</small></span>}
      {s.note && <span className="nr-half-note">{s.note}</span>}
    </>
  )
}

// ── интро ──
function NrIntro({ d, busy, onStart, flaskSel, onFlask }: {
  d: NState; busy: boolean; onStart: () => void; flaskSel: string[]; onFlask: (k: string) => void
}) {
  const cd = d.cooldown
  return (
    <div className="nr-scene intro rise">
      <div className="nr-fog" />
      <h2 className="nr-title">Ночная ходка</h2>
      <p className="nr-flavor">«Когда город спит, тракт оживает. Иди во тьму — но знай меру: зарвёшься, и обчистят дочиста.»</p>
      <div className="nr-stats"><i>🛡 {d.stats.armor}</i><i>🍀 {d.stats.luck}</i></div>
      {cd <= 0 && (d.flask?.length ?? 0) > 0 && (
        <div className="raid-flask">
          <span className="raid-flask-h">🍺 Глоток на дорожку (до 2):</span>
          {d.flask!.map((f) => (
            <button key={f.key} className={`raid-flask-chip${flaskSel.includes(f.key) ? ' on' : ''}`}
              onClick={() => { haptic('light'); onFlask(f.key) }}>
              {f.emoji} {f.name} — {f.hint} <em>×{f.qty}</em>
            </button>
          ))}
        </div>
      )}
      {cd > 0
        ? <div className="nr-cd">🌅 Ноги ещё гудят — в путь через <b>{hms(cd)}</b></div>
        : <button className="btn nr-go" disabled={busy} onClick={() => { haptic('medium'); onStart() }}>🌙 Выйти на тракт</button>}
    </div>
  )
}

// ── развилка → раскол сцены ──
function NrFork({ d, run, busy, onPick }: { d: NState; run: NRun; busy: boolean; onPick: (f: NFork) => void }) {
  const sit = run.situation ? SITUATION[run.situation] : null
  const f = run.fork || []
  const side = (ff: NFork): SplitSide => ({
    key: ff.kind, emoji: ff.emoji, name: ff.name, sub: ff.hint,
    tag: ff.risky ? `риск · ${ff.success}%` : 'верно', reward: ff.reward,
    note: ff.stat ? STAT_LABEL[ff.stat] : undefined,
    tone: ff.risky ? 'risk' : 'safe', onPick: () => onPick(ff),
  })
  return (
    <>
      <NrTopHud run={run} max={d.max_legs} />
      {f.length >= 2 && <NrSplit left={side(f[0])} right={side(f[1])} busy={busy} note={sit ? sit.t : '⟔ выбери тропу ⟔'} />}
    </>
  )
}

// ── встреча с НПС → раскол сцены (диалог сверху, два ответа половинами) ──
function NrMeet({ run, busy, onPick }: { run: NRun; busy: boolean; onPick: (id: string) => void }) {
  const m = run.meet!
  const o = m.options
  const side = (op: { id: string; label: string }, tone: 'gold' | 'cool'): SplitSide => {
    const parts = op.label.trim().split(' ')
    const emoji = /\p{Emoji}/u.test(parts[0]) ? parts.shift()! : '🗣'
    return { key: op.id, emoji, name: parts.join(' '), tone, onPick: () => onPick(op.id) }
  }
  return (
    <>
      <div className="nr-meet-hd">
        <div className="nr-meet-npc">{m.npc}</div>
        <p className="nr-meet-scene">«{m.scene}»</p>
      </div>
      {o.length >= 2 && <NrSplit left={side(o[0], 'gold')} right={side(o[1], 'cool')} busy={busy} />}
    </>
  )
}

// ── загадка Ведьмы → кинематографичные строки-ответы (без коробок) ──
function NrQuiz({ run, busy, onAnswer }: { run: NRun; busy: boolean; onAnswer: (i: number) => void }) {
  const q = run.quiz!
  return (
    <div className="nr-cine">
      <div className="nr-witch">🔮</div>
      <p className="nr-riddle">{q.q}</p>
      <div className="nr-qlist">
        {q.options.map((o, i) => (
          <button key={i} className="nr-qrow" disabled={busy} onClick={() => { haptic('light'); onAnswer(i) }}>
            <span className="nr-qk">{'АБВГ'[i]}</span><span className="nr-qt">{o}</span><span className="nr-qchev">›</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── перекрёсток → раскол сцены (глубже / свернуть) ──
function NrCross({ run, chron, busy, onPush, onBank }: { run: NRun; chron: string[]; busy: boolean; onPush: () => void; onBank: () => void }) {
  const last = chron.length ? chron[chron.length - 1] : null
  const deeper: SplitSide = {
    key: 'push', emoji: '🌒', name: 'Глубже в ночь', sub: `×${run.growth} → +${fmt(run.next_value)} 🪙`,
    tag: 'риск', note: 'можно потерять котомку', tone: 'risk', onPick: onPush,
  }
  const home: SplitSide = {
    key: 'bank', emoji: '🏠', name: 'Свернуть', sub: `забрать ${fmt(run.satchel_value)} 🪙`,
    tag: 'верно', note: 'без риска', tone: 'safe', onPick: onBank,
  }
  return (
    <>
      <NrTopHud run={run} max={6} />
      {last && <div className="nr-cross-narr">{last}</div>}
      {run.can_push
        ? <NrSplit left={deeper} right={home} busy={busy} note="⟔ распутье ⟔" />
        : (
          <div className="nr-cine onlybank">
            <div className="nr-dawn-emo">🌅</div>
            <p className="nr-dawn-txt">Впереди рассвет — дальше тракт не ведёт. Пора домой с добычей.</p>
            <button className="btn nr-go" disabled={busy} onClick={onBank}>🏠 Свернуть в таверну · {fmt(run.satchel_value)} 🪙</button>
          </div>
        )}
    </>
  )
}

// ── резолв-оверлей: анимация исхода ──
function NrResolve({ out, onNext }: { out: NOut; onNext: () => void }) {
  const dice = out.kind === 'gamble' && out.roll
  return (
    <div className="nr-cine resolve">
      {dice ? <TgDice value={out.roll!} loseFaces={out.lose_faces || 0} /> : <div className="nr-res-emo">{RES_EMO[out.kind] || '🌙'}</div>}
      <div className="nr-res-h">{RES_TITLE(out)}</div>
      {out.story && <p className="nr-story"><Typewriter text={out.story} /></p>}
      {out.healed > 0 && <div className="nr-res-heal">+{out.healed} ❤</div>}
      {out.hp_cost > 0 && <div className="nr-res-cost">−{out.hp_cost} ❤ за победу</div>}
      {out.factions && out.factions.length > 0 && (
        <div className="nr-res-fac">{out.factions.map((f) => <span key={f.faction}>{FAC[f.faction] || f.faction} {f.delta > 0 ? '↑' : '↓'}</span>)}</div>
      )}
      {out.loot.length > 0 && (
        <div className="nr-res-loot">{out.loot.map((it, i) => (
          <span key={it.key} className="nr-loot-i pop" style={{ animationDelay: `${i * 0.08}s` }}><ResIcon k={it.key} emoji={it.emoji} size={22} />+{fmt(it.qty)}</span>
        ))}</div>
      )}
      {out.kind === 'quiz' && !out.correct && <div className="nr-res-miss">Ведьма хохочет — мимо. Но без потерь.</div>}
      <button className="btn gold nr-next" onClick={() => { haptic('light'); onNext() }}>Дальше ›</button>
    </div>
  )
}

// ── НАТИВНЫЙ кубик Telegram: официальная Lottie-анимация грани (value=1..6), играется один раз ──
// Файлы — извлечённый стикерсет inputStickerSetDice('🎲'), индекс=грань (см. core.telegram.org/api/dice).
function TgDice({ value, loseFaces }: { value: number; loseFaces: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const [fail, setFail] = useState(false)
  const [done, setDone] = useState(false)
  const lost = value <= loseFaces
  useEffect(() => {
    let anim: ReturnType<typeof lottie.loadAnimation> | null = null
    let cancelled = false
    // .tgs = gzip(Lottie JSON), ~64 КБ; распаковываем нативным DecompressionStream (без pako)
    fetch(`${import.meta.env.BASE_URL}nightrun/dice/${value}.tgs`)
      .then((r) => { if (!r.ok) throw new Error('no dice asset'); return r.body!.pipeThrough(new DecompressionStream('gzip')) })
      .then((stream) => new Response(stream).json())
      .then((data) => {
        if (cancelled || !ref.current) return
        anim = lottie.loadAnimation({ container: ref.current, renderer: 'svg', loop: false, autoplay: true, animationData: data })
        anim.addEventListener('complete', () => { setDone(true); hapticNotify(lost ? 'error' : 'success') })
      })
      .catch(() => setFail(true))  // нет ассета / старый webview без DecompressionStream → запасной 3D-куб
    return () => { cancelled = true; anim?.destroy() }
  }, [value, lost])
  if (fail) return <Die value={value} loseFaces={loseFaces} />  // запасной 3D-куб, если ассет недоступен
  return (
    <div className="tgd-wrap">
      <div className={`tgd-lottie ${done ? (lost ? 'lose' : 'win') : ''}`} ref={ref} />
      <span className="tgd-cap">{done ? <>выпало <b>{value}</b>{loseFaces > 0 ? ` · проигрыш 1–${loseFaces}` : ''}</> : 'бросок…'}</span>
    </div>
  )
}

// ── запасной 3D-куб (CSS): на случай, если нативная Lottie-анимация недоступна ──
const DICE_PIPS: Record<number, number[]> = {
  1: [5], 2: [1, 9], 3: [1, 5, 9], 4: [1, 3, 7, 9], 5: [1, 3, 5, 7, 9], 6: [1, 3, 4, 6, 7, 9],
}
// финальный поворот куба (с двумя оборотами) — выводит нужную грань к зрителю
const DICE_REST: Record<number, string> = {
  1: 'rotateX(-720deg) rotateY(-720deg)',
  2: 'rotateX(-630deg) rotateY(-720deg)',
  3: 'rotateX(-720deg) rotateY(-810deg)',
  4: 'rotateX(-720deg) rotateY(-630deg)',
  5: 'rotateX(-810deg) rotateY(-720deg)',
  6: 'rotateX(-720deg) rotateY(-540deg)',
}
function DieFace({ v, cls }: { v: number; cls: string }) {
  return (
    <div className={`tgd-face ${cls}`}>
      {Array.from({ length: 9 }, (_, i) => <span key={i} className={`tgd-pip ${DICE_PIPS[v].includes(i + 1) ? 'on' : ''}`} />)}
    </div>
  )
}
function Die({ value, loseFaces }: { value: number; loseFaces: number }) {
  const [tf, setTf] = useState('rotateX(-12deg) rotateY(8deg)')
  const [done, setDone] = useState(false)
  const lost = value <= loseFaces
  useEffect(() => {
    const r = requestAnimationFrame(() => setTf(DICE_REST[value]))
    const t = setTimeout(() => { setDone(true); hapticNotify(lost ? 'error' : 'success') }, 1180)
    return () => { cancelAnimationFrame(r); clearTimeout(t) }
  }, [value, lost])
  return (
    <div className="tgd-wrap">
      <div className="tgd-stage">
        <div className={`tgd ${done ? (lost ? 'lose' : 'win') : 'rolling'}`}>
          <div className="tgd-cube" style={{ transform: tf }}>
            <DieFace v={1} cls="f-front" /><DieFace v={6} cls="f-back" />
            <DieFace v={3} cls="f-right" /><DieFace v={4} cls="f-left" />
            <DieFace v={5} cls="f-top" /><DieFace v={2} cls="f-bot" />
          </div>
        </div>
        <div className="tgd-shadow" />
      </div>
      <span className="tgd-cap">{done ? <>выпало <b>{value}</b>{loseFaces > 0 ? ` · проигрыш 1–${loseFaces}` : ''}</> : 'бросок…'}</span>
    </div>
  )
}

// ── финал ──
function NrEnd({ end, chron, onClose }: { end: { kind: 'bust' | 'bank'; out?: NOut; banked?: NItem[]; value?: number }; chron: string[]; onClose: () => void }) {
  const bust = end.kind === 'bust'
  return (
    <div className={`nr-scene final ${bust ? 'bust' : 'bank'}`}>
      <div className="nr-fog" />
      <div className="nr-final-emo">{bust ? (end.out?.collapsed ? '💀' : '🌑') : '🏠'}</div>
      <div className="nr-final-h">{bust ? 'ОБЧИСТИЛИ!' : 'ВЕРНУЛСЯ С ТРАКТА'}</div>
      {bust ? (
        <>
          <p className="nr-final-txt">{end.out?.collapsed ? 'Победил, да рухнул без сил — всё растащили.' : 'Не свезло на тёмной тропе. Котомку как ветром сдуло.'}</p>
          {end.out?.lost && end.out.lost.length > 0 && (
            <div className="nr-res-loot lost">{end.out.lost.map((it) => <span key={it.key} className="nr-loot-i"><ResIcon k={it.key} emoji={it.emoji} size={20} />−{fmt(it.qty)}</span>)}</div>
          )}
        </>
      ) : (
        <>
          <p className="nr-final-txt">Котомка цела — добро в твоей таверне.</p>
          {end.banked && end.banked.length > 0
            ? <div className="nr-res-loot">{end.banked.map((it, i) => <span key={it.key} className="nr-loot-i pop" style={{ animationDelay: `${i * 0.08}s` }}><ResIcon k={it.key} emoji={it.emoji} size={22} />+{fmt(it.qty)}</span>)}</div>
            : <p className="muted" style={{ fontStyle: 'italic' }}>Пустым вернулся — да хоть цел.</p>}
          {!!end.value && <div className="nr-final-val">≈ {fmt(end.value)} 🪙-эквивалента</div>}
        </>
      )}
      {chron.length > 0 && (
        <div className="nr-chron">
          <div className="nr-chron-h">📜 Хроника ночи</div>
          <div className="nr-chron-body">
            {chron.map((s, i) => <p key={i} className="nr-chron-l" style={{ animationDelay: `${Math.min(i * 0.12, 1.4)}s` }}><i>{i + 1}.</i> {s}</p>)}
          </div>
        </div>
      )}
      <button className="btn gold nr-next" onClick={onClose}>← К вылазкам</button>
    </div>
  )
}

const RES_EMO: Record<string, string> = { fight: '⚔️', sneak: '🌒', find: '💰', rest: '🔥', meet: '🗣', quiz: '❓' }
const FAC: Record<string, string> = { thieves: '🗡 Воры', watch: '🛡 Стража', crown: '👑 Корона', church: '⛪ Церковь' }
function RES_TITLE(out: NOut): string {
  if (out.kind === 'fight') return 'Отбился!'
  if (out.kind === 'sneak') return 'Проскользнул'
  if (out.kind === 'gamble') return out.roll && (out.lose_faces || 0) >= out.roll ? 'Не свезло…' : 'Свезло!'
  if (out.kind === 'find') return 'Схрон!'
  if (out.kind === 'rest') return 'Привал у костра'
  if (out.kind === 'meet') return out.npc || 'Встреча'
  if (out.kind === 'quiz') return out.correct ? 'Угадал!' : 'Мимо'
  return 'Тракт'
}
