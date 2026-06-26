import { useState, useEffect, type CSSProperties } from 'react'
import { useApi } from '../hooks'
import { api } from '../api'
import { haptic, hapticNotify, initData } from '../telegram'
import { ResIcon, fmt } from '../components/icons'

// ── типы (зеркало webapp _nightrun_state / _nr_out) ──
interface NItem { key: string; name: string; emoji: string; qty: number }
interface NFork { kind: string; emoji: string; name: string; risky: boolean; hint: string; success: number }
interface NRun {
  leg: number; state: string; hp: number; hp_max: number; satchel: NItem[]; satchel_value: number
  situation: string | null; can_push: boolean; rest_heal: number
  fork?: NFork[]; meet?: { npc: string; scene: string; options: { id: string; label: string }[] }
  quiz?: { q: string; options: string[] }
}
interface NState { ok: boolean; cooldown: number; active: boolean; max_legs: number; stats: { armor: number; luck: number }; run: NRun | null }
interface NOut {
  kind: string; busted: boolean; loot: NItem[]; hp_cost: number; healed: number; roll?: number | null
  lose_faces?: number | null; collapsed: boolean; lost?: NItem[]; correct?: boolean
  factions?: { faction: string; delta: number }[]; npc?: string
}

const SITUATION: Record<string, { t: string; cls: string }> = {
  curfew: { t: '🚨 Комендантский час — стража лютует', cls: 'bad' },
  thieves_rampant: { t: '🗡 Воры распоясались — на тракте лихо', cls: 'bad' },
  merchant_boom: { t: '💰 Купеческий бум — караваны жирны', cls: 'good' },
}
const hms = (s: number) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return h ? `${h} ч ${m} мин` : `${m} мин ${s % 60} с` }

// СВОЙ фон и место на КАЖДЫЙ этап — чем дальше в ночь, тем мрачнее (лор)
const SCENES = [
  { bg: 'town', name: 'Окраина' },
  { bg: 'forest', name: 'Опушка леса' },
  { bg: 'forest2', name: 'Глухая чаща' },
  { bg: 'ruins', name: 'Старый погост' },
  { bg: 'ruins2', name: 'Сердце руин' },
  { bg: 'ruins2', name: 'Сердце руин' },
]
const sceneFor = (leg: number) => SCENES[Math.min(Math.max(leg, 1), SCENES.length) - 1]

const SAMPLE: NState = {
  ok: true, cooldown: 0, active: false, max_legs: 6, stats: { armor: 12, luck: 4 }, run: null,
}

// ── Офлайн-движок для превью (вне Telegram): мок поведения бэка ──
function offState(run: NRun | null, cooldown = 0): NState {
  return { ...SAMPLE, cooldown, active: !!run, run }
}
function offStart(): NRun {
  return { leg: 1, state: 'fork', hp: 35, hp_max: 35, satchel: [], satchel_value: 0, situation: 'merchant_boom', can_push: true, rest_heal: 14, fork: offFork(1) }
}
function offFork(leg: number): NFork[] {
  const all: NFork[] = [
    { kind: 'fight', emoji: '⚔️', name: 'Засада', risky: true, hint: 'Сила и броня решают. Победа стоит здоровья.', success: Math.max(45, 90 - leg * 6) },
    { kind: 'gamble', emoji: '🎲', name: 'Лихо', risky: true, hint: 'Бросок костей: куш или обчистят.', success: Math.max(40, 82 - leg * 6) },
    { kind: 'sneak', emoji: '🌒', name: 'Тишком', risky: true, hint: 'Удача — проскользнуть мимо беды.', success: Math.max(45, 88 - leg * 6) },
    { kind: 'meet', emoji: '🗣', name: 'Встреча', risky: false, hint: 'Выбор и сдвиг сил города. Без бюста.', success: 100 },
    { kind: 'quiz', emoji: '❓', name: 'Загадка', risky: false, hint: 'Угадал — куш. Без бюста.', success: 100 },
    { kind: 'rest', emoji: '🔥', name: 'Привал', risky: false, hint: 'Лечит. Добычи нет.', success: 100 },
    { kind: 'find', emoji: '💰', name: 'Схрон', risky: false, hint: 'Малая добыча. Безопасно.', success: 100 },
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
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(''), 2200) }
  const off = !initData()

  // живой кулдаун-таймер
  const [, tick] = useState(0)
  useEffect(() => { const i = setInterval(() => tick((x) => x + 1), 1000); return () => clearInterval(i) }, [])

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

  async function start() {
    if (busy) return; setBusy(true); haptic('medium')
    if (off) { set(offState(offStart())); setBusy(false); return }
    const r = await call<NState>('nightrun/start'); if (r) set(r); setBusy(false)
  }
  async function pick(f: NFork) {
    if (busy || !run) return; setBusy(true); haptic('medium')
    if (off) { offPick(f); setBusy(false); return }
    const r = await call<{ out: NOut; nightrun: NState }>('nightrun/pick', { kind: f.kind })
    if (r) {
      if (f.kind === 'meet' || f.kind === 'quiz') { set(r.nightrun) }   // под-экран, без оверлея
      else { setOut(r.out); set(r.nightrun); if (r.out.busted) setEnd({ kind: 'bust', out: r.out }) }
    }
    setBusy(false)
  }
  async function meet(optId: string) {
    if (busy) return; setBusy(true); haptic('medium')
    if (off) { offMeet(optId); setBusy(false); return }
    const r = await call<{ out: NOut; nightrun: NState }>('nightrun/meet', { opt: optId })
    if (r) { setOut(r.out); set(r.nightrun) }
    setBusy(false)
  }
  async function quiz(ans: number) {
    if (busy) return; setBusy(true); haptic('medium')
    if (off) { offQuiz(ans); setBusy(false); return }
    const r = await call<{ out: NOut; nightrun: NState }>('nightrun/quiz', { answer: ans })
    if (r) { setOut(r.out); set(r.nightrun) }
    setBusy(false)
  }
  async function push() {
    if (busy) return; setBusy(true); haptic('medium'); setOut(null)
    if (off && run) { const leg = run.leg + 1; set(offState({ ...run, leg, state: 'fork', fork: offFork(leg) })); setBusy(false); return }
    const r = await call<NState>('nightrun/push'); if (r) set(r); setBusy(false)
  }
  async function bank() {
    if (busy || !run) return; setBusy(true); haptic('medium'); setOut(null)
    if (off) { setEnd({ kind: 'bank', banked: run.satchel, value: run.satchel_value }); setBusy(false); return }
    const r = await call<{ banked: NItem[]; value: number; nightrun: NState }>('nightrun/bank')
    if (r) { setEnd({ kind: 'bank', banked: r.banked, value: r.value }); set(r.nightrun) }
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
    set(offState({ ...run, ...extra, state: 'crossroad', satchel: sat, satchel_value: sat.reduce((a, x) => a + (x.key === 'gold' ? x.qty : x.qty * 3), 0) }))
  }
  function offPick(f: NFork) {
    if (!run) return
    if (f.kind === 'meet') { set(offState({ ...run, state: 'meet', meet: { npc: '🥷 Контрабандист Тихушкин', scene: 'из темноты шипят: «Эй, хозяин… товар не нужен? Дёшево, мимо застав».', options: [{ id: 'buy', label: '🤝 Взять товар' }, { id: 'turn', label: '🛡 Сдать страже' }] } })); return }
    if (f.kind === 'quiz') { set(offState({ ...run, state: 'quiz', quiz: { q: '🔮 Ведьма щерится: «Что в кабаке льётся рекой, а наутро аукается башкой?»', options: ['Вода', 'Эль', 'Дождь', 'Слёзы должника'] } })); return }
    const ok = Math.random() * 100 < f.success
    if (f.risky && !ok) { const o: NOut = { kind: f.kind, busted: true, loot: [], hp_cost: 0, healed: 0, collapsed: false, lost: run.satchel, roll: f.kind === 'gamble' ? Math.ceil(Math.random() * 2) : null, lose_faces: 2 }; setOut(o); setEnd({ kind: 'bust', out: o }); return }
    if (f.kind === 'rest') { const heal = Math.min(run.rest_heal, run.hp_max - run.hp); const o: NOut = { kind: 'rest', busted: false, loot: [], hp_cost: 0, healed: heal, collapsed: false }; setOut(o); offCross({ hp: run.hp + heal }, []); return }
    const loot = offLoot(f.kind === 'find' ? 0.6 : f.kind === 'gamble' ? 1.4 : 1)
    let hp = run.hp; const cost = f.kind === 'fight' ? 4 + run.leg + Math.floor(Math.random() * 6) : 0; hp -= cost
    const o: NOut = { kind: f.kind, busted: false, loot, hp_cost: cost, healed: 0, collapsed: false, roll: f.kind === 'gamble' ? 3 + Math.floor(Math.random() * 3) : null, lose_faces: f.kind === 'gamble' ? 2 : null }
    setOut(o); offCross({ hp }, loot)
  }
  function offMeet(optId: string) { const mult = optId === 'buy' ? 1.6 : 1.0; const loot = offLoot(mult); const o: NOut = { kind: 'meet', busted: false, loot, hp_cost: 0, healed: 0, collapsed: false, npc: '🥷 Контрабандист', factions: [{ faction: 'thieves', delta: optId === 'buy' ? 4 : -4 }] }; setOut(o); if (run) offCross({}, loot) }
  function offQuiz(ans: number) { const correct = ans === 1; const loot = correct ? offLoot(1.5) : []; const o: NOut = { kind: 'quiz', busted: false, loot, hp_cost: 0, healed: 0, collapsed: false, correct }; setOut(o); if (run) offCross({}, loot) }

  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  if (error && error !== 'no_tavern' && initData()) return (
    <div className="center" style={{ flex: 1, flexDirection: 'column', gap: 14, padding: 26 }}>
      <div className="muted" style={{ fontStyle: 'italic' }}>Тракт во мгле — не загрузилось.</div>
      <button className="btn gold" style={{ maxWidth: 220 }} onClick={() => reload()}>Повторить</button>
    </div>
  )

  // ── финал (бюст / банк) ──
  if (end) return (
    <div className="nr" style={nrbg}>
      <div className="nr-bgfix" key={bgName} aria-hidden="true" />
      {toast && <div className="toast">{toast}</div>}
      <NrEnd end={end} onClose={() => { setEnd(null); setOut(null); if (off) set(offState(null, end.kind === 'bank' ? 4 * 3600 : 4 * 3600)); else reload() }} />
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
      {!d.active && <NrIntro d={d} busy={busy} onStart={start} />}
      {run && run.state === 'fork' && <NrFork d={d} run={run} busy={busy} onPick={pick} />}
      {run && run.state === 'meet' && <NrMeet run={run} busy={busy} onPick={meet} />}
      {run && run.state === 'quiz' && <NrQuiz run={run} busy={busy} onAnswer={quiz} />}
      {run && run.state === 'crossroad' && !out && <NrCross run={run} busy={busy} onPush={push} onBank={bank} />}
    </div>
  )
}

// ── шапка забега (этап, HP, котомка) ──
function NrHud({ run, max }: { run: NRun; max: number }) {
  const hpPct = Math.max(0, Math.min(100, (run.hp / run.hp_max) * 100))
  return (
    <div className="nr-hud">
      <div className="nr-legs">{Array.from({ length: max }).map((_, i) => <i key={i} className={i < run.leg ? 'on' : ''} />)}<span className="nr-leg-n">{sceneFor(run.leg).name}</span></div>
      <div className="nr-hud-row">
        <span className="nr-hp"><span className="nr-bar"><i style={{ width: `${hpPct}%` }} /></span><b>{run.hp}</b><small>/{run.hp_max} ❤</small></span>
        <span className="nr-sat">🎒 <b>{fmt(run.satchel_value)}</b><small>🪙-экв</small></span>
      </div>
    </div>
  )
}

// ── интро ──
function NrIntro({ d, busy, onStart }: { d: NState; busy: boolean; onStart: () => void }) {
  const cd = d.cooldown
  return (
    <div className="nr-scene intro rise">
      <div className="nr-fog" />
      <h2 className="nr-title">Ночная ходка</h2>
      <p className="nr-flavor">«Когда город спит, тракт оживает. Иди во тьму — но знай меру: зарвёшься, и обчистят дочиста.»</p>
      <div className="nr-stats"><i>🛡 {d.stats.armor}</i><i>🍀 {d.stats.luck}</i></div>
      {cd > 0
        ? <div className="nr-cd">🌅 Ноги ещё гудят — в путь через <b>{hms(cd)}</b></div>
        : <button className="btn nr-go" disabled={busy} onClick={onStart}>🌙 Выйти на тракт</button>}
    </div>
  )
}

// ── развилка ──
function NrFork({ d, run, busy, onPick }: { d: NState; run: NRun; busy: boolean; onPick: (f: NFork) => void }) {
  const sit = run.situation ? SITUATION[run.situation] : null
  return (
    <div className="nr-scene rise">
      <div className="nr-fog" />
      <NrHud run={run} max={d.max_legs} />
      {sit && <div className={`nr-sit ${sit.cls}`}>{sit.t}</div>}
      <div className="nr-fork-h">⟔ развилка ⟔</div>
      <div className="nr-fork2">
        {(run.fork || []).map((f) => (
          <button key={f.kind} className={`nr-path ${f.risky ? 'risky' : 'safe'}`} disabled={busy} onClick={() => { haptic('light'); onPick(f) }}>
            <span className="nr-path-emo">{f.emoji}</span>
            <span className="nr-path-nm">{f.name}</span>
            <span className={`nr-path-tag ${f.risky ? 'risk' : 'safe'}`}>{f.risky ? `${f.success}%` : 'без риска'}</span>
            <span className="nr-path-hint">{f.hint}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── встреча с НПС ──
function NrMeet({ run, busy, onPick }: { run: NRun; busy: boolean; onPick: (id: string) => void }) {
  const m = run.meet!
  return (
    <div className="nr-scene rise">
      <div className="nr-fog" />
      <div className="nr-npc">{m.npc}</div>
      <p className="nr-scene-txt">«{m.scene}»</p>
      <div className="nr-opts">
        {m.options.map((o) => (
          <button key={o.id} className="btn nr-opt" disabled={busy} onClick={() => { haptic('light'); onPick(o.id) }}>{o.label}</button>
        ))}
      </div>
    </div>
  )
}

// ── загадка Ведьмы ──
function NrQuiz({ run, busy, onAnswer }: { run: NRun; busy: boolean; onAnswer: (i: number) => void }) {
  const q = run.quiz!
  return (
    <div className="nr-scene rise">
      <div className="nr-fog" />
      <div className="nr-witch">🔮</div>
      <p className="nr-riddle">{q.q}</p>
      <div className="nr-quiz-opts">
        {q.options.map((o, i) => (
          <button key={i} className="btn nr-quiz-opt" disabled={busy} onClick={() => { haptic('light'); onAnswer(i) }}>{o}</button>
        ))}
      </div>
    </div>
  )
}

// ── перекрёсток ──
function NrCross({ run, busy, onPush, onBank }: { run: NRun; busy: boolean; onPush: () => void; onBank: () => void }) {
  return (
    <div className="nr-scene rise">
      <div className="nr-fog" />
      <div className="nr-cross-h">Распутье</div>
      <div className="nr-satchel">
        <div className="nr-satchel-h">🎒 Котомка · <b>{fmt(run.satchel_value)}</b> 🪙-экв</div>
        <div className="nr-loot">
          {run.satchel.length ? run.satchel.map((it) => (
            <span key={it.key} className="nr-loot-i"><ResIcon k={it.key} emoji={it.emoji} size={18} />{fmt(it.qty)}</span>
          )) : <span className="muted" style={{ fontStyle: 'italic' }}>пусто — пока нечего нести</span>}
        </div>
      </div>
      <div className="nr-cross-btns">
        {run.can_push
          ? <button className="btn danger nr-deeper" disabled={busy} onClick={onPush}>⬇️ Глубже в ночь<small>риск растёт, добыча жирнеет</small></button>
          : <div className="nr-dawn">🌅 Впереди рассвет — дальше тракт не ведёт</div>}
        <button className="btn green nr-home" disabled={busy} onClick={onBank}>🏠 Свернуть в таверну<small>забрать {fmt(run.satchel_value)} 🪙-экв</small></button>
      </div>
    </div>
  )
}

// ── резолв-оверлей: анимация исхода ──
function NrResolve({ out, onNext }: { out: NOut; onNext: () => void }) {
  const dice = out.kind === 'gamble' && out.roll
  return (
    <div className="nr-scene resolve">
      <div className="nr-fog" />
      {dice ? <Die value={out.roll!} loseFaces={out.lose_faces || 0} /> : <div className="nr-res-emo">{RES_EMO[out.kind] || '🌙'}</div>}
      <div className="nr-res-h">{RES_TITLE(out)}</div>
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

// ── анимированный кубик ──
function Die({ value, loseFaces }: { value: number; loseFaces: number }) {
  const [face, setFace] = useState(1)
  const lost = value <= loseFaces
  useEffect(() => {
    let n = 0; const id = setInterval(() => { n++; setFace(1 + Math.floor(Math.random() * 6)); if (n > 12) { clearInterval(id); setFace(value); hapticNotify(lost ? 'error' : 'success') } }, 90)
    return () => clearInterval(id)
  }, [value, lost])
  return (
    <div className={`nr-die ${face === value ? (lost ? 'final-lose' : 'final-win') : ''}`}>
      <span className="nr-die-v">{['', '⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][face]}</span>
      <span className="nr-die-faces">{loseFaces > 0 ? `проигрыш: 1–${loseFaces}` : ''}</span>
    </div>
  )
}

// ── финал ──
function NrEnd({ end, onClose }: { end: { kind: 'bust' | 'bank'; out?: NOut; banked?: NItem[]; value?: number }; onClose: () => void }) {
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
