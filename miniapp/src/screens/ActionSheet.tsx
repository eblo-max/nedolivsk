import { useEffect, useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { ResIcon, fmt } from '../components/icons'

interface Task { label: string; reward: string; status: 'claimed' | 'ready' | 'todo' }
interface GoalItem { key: string; name: string; qty: number }
interface Goal { label: string; items: GoalItem[] }
interface ResOpt { key: string; name: string; amount: number }
interface Panel {
  kind: string; error?: boolean
  // bonus
  active?: boolean; available?: boolean; emoji?: string; name?: string; desc?: string
  minutes_left?: number; hours?: number; reset_h?: number
  // newbie
  tasks?: Task[]; claimable?: boolean; perks?: boolean; grace_days?: number
  // expedition
  free?: number; total?: number; out?: number; ready?: number; next_minutes?: number
  pay?: number; goals?: Goal[]; resources?: ResOpt[]
}

const TITLE: Record<string, { ic: string; t: string }> = {
  bonus: { ic: 'bonus', t: 'ОПОХМЕЛ' },
  newbie: { ic: 'scroll', t: 'ГРАМОТА НОВОСЁЛА' },
  expedition: { ic: 'pickaxe', t: 'БРИГАДЫ РАБОТНИКОВ' },
}

// образцы для оффлайн-превью (когда нет /api)
const SAMPLE: Record<string, Panel> = {
  bonus: { kind: 'bonus', active: false, available: true, emoji: '🍺', name: 'Хмельной кураж', desc: 'Эль льётся рекой — доход на треть жирнее', hours: 6, reset_h: 14 },
  newbie: { kind: 'newbie', claimable: true, perks: true, grace_days: 7, tasks: [
    { label: 'Собери первую выручку', reward: '+50 🪙', status: 'claimed' },
    { label: 'Отправь бригаду', reward: '+30 🪵', status: 'ready' },
    { label: 'Улучши таверну до ур.2', reward: '+1 ✨', status: 'todo' },
  ] },
  expedition: { kind: 'expedition', free: 1, total: 2, out: 1, ready: 1, next_minutes: 14, pay: 25, hours: 4,
    goals: [{ label: 'До перестройки ур.3', items: [{ key: 'wood', name: 'Дерево', qty: 220 }, { key: 'grain', name: 'Зерно', qty: 180 }] }],
    resources: [
      { key: 'wood', name: 'Дерево', amount: 14 }, { key: 'grain', name: 'Зерно', amount: 12 },
      { key: 'hops', name: 'Хмель', amount: 8 }, { key: 'ore', name: 'Руда', amount: 6 },
      { key: 'stone', name: 'Камень', amount: 5 }, { key: 'clay', name: 'Глина', amount: 7 },
    ] },
}

export default function ActionSheet({ kind, onState, onClose, flash }: {
  kind: string
  onState: (s: unknown) => void
  onClose: () => void
  flash: (m: string) => void
}) {
  const [panel, setPanel] = useState<Panel | null>(null)
  const [busy, setBusy] = useState(false)
  const [closing, setClosing] = useState(false)

  useEffect(() => {
    let live = true
    api<{ panel: Panel }>('panel', { kind })
      .then((r) => { if (live) setPanel(r.panel) })
      .catch(() => { if (live) setPanel(SAMPLE[kind] ?? { kind, error: true }) })
    return () => { live = false }
  }, [kind])

  function close() {
    if (closing) return
    setClosing(true); setTimeout(onClose, 240)
  }

  // активировать бонус / забрать грамоту — действие и закрытие
  async function fire(path: string, done: (r: Record<string, unknown>) => string) {
    if (busy) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<Record<string, unknown>>(path)
      onState(r.state); hapticNotify('success'); flash(done(r)); close()
    } catch (e) {
      hapticNotify('warning')
      const code = (e as { code?: string })?.code
      flash(code === 'busy' ? 'Баф уже гуляет' : code === 'nothing' ? 'Забирать нечего' : 'Не вышло — попробуй ещё')
      setBusy(false)
    }
  }

  // действия бригад — обновляют панель, sheet остаётся открытым
  async function exped(path: string, body: Record<string, unknown> | undefined, ok: (r: Record<string, unknown>) => string) {
    if (busy) return
    haptic('medium'); setBusy(true)
    try {
      const r = await api<Record<string, unknown>>(path, body)
      onState(r.state); if (r.panel) setPanel(r.panel as Panel); hapticNotify('success'); flash(ok(r))
    } catch (e) {
      hapticNotify('warning')
      const code = (e as { code?: string })?.code
      flash(code === 'no_gold' ? 'Платить нечем' : code === 'no_slot' ? 'Все бригады в деле' : 'Не вышло')
    } finally { setBusy(false) }
  }

  const meta = TITLE[kind] ?? { ic: 'pickaxe', t: '' }
  return (
    <div className={`sheet-ov${closing ? ' out' : ''}`} onClick={close}>
      <div className={`sheet${closing ? ' out' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grab" />
        <div className="sheet-h">
          <img className="sheet-ic" src={`${import.meta.env.BASE_URL}act/${meta.ic}.png`} alt="" />
          <span>{meta.t}</span>
          <button className="sheet-x" onClick={close} aria-label="Закрыть">✕</button>
        </div>
        <div className="sheet-b">
          {!panel ? <div className="center" style={{ padding: 30 }}><div className="spin" /></div>
            : panel.error ? <p className="muted" style={{ fontStyle: 'italic' }}>Не загрузилось — закрой и попробуй ещё.</p>
              : kind === 'bonus' ? <BonusBody p={panel} busy={busy} onFire={fire} />
                : kind === 'newbie' ? <NewbieBody p={panel} busy={busy} onFire={fire} />
                  : <ExpedBody p={panel} busy={busy} onExped={exped} />}
        </div>
      </div>
    </div>
  )
}

function BonusBody({ p, busy, onFire }: { p: Panel; busy: boolean; onFire: (path: string, done: (r: Record<string, unknown>) => string) => void }) {
  if (p.active) return (
    <>
      <div className="sheet-lead"><b style={{ color: 'var(--parch)' }}>{p.emoji} {p.name}</b> уже гуляет</div>
      <p className="sheet-desc">«{p.desc}»</p>
      <div className="sheet-row"><span>⏳ Ещё</span><b>{p.minutes_left} мин</b></div>
      <p className="muted" style={{ fontStyle: 'italic', fontSize: 13, marginTop: 8 }}>Один баф за раз. Новый подвезут завтра.</p>
    </>
  )
  if (!p.available) return <p className="sheet-desc">«Сегодня халявы нет — всё уже выпито. Загляни завтра.»</p>
  return (
    <>
      <div className="sheet-lead"><b style={{ color: 'var(--parch)' }}>{p.emoji} {p.name}</b></div>
      <p className="sheet-desc">«{p.desc}»</p>
      <div className="sheet-row"><span>✨ Действует</span><b>{p.hours} ч</b></div>
      <div className="sheet-row"><span>🔄 Сброс через</span><b>{p.reset_h} ч</b></div>
      <button className="btn gold" style={{ marginTop: 14 }} disabled={busy}
        onClick={() => onFire('bonus', (r) => `Баф «${r.boon}» на ${r.minutes} мин!`)}>
        🍺 Опохмелиться
      </button>
    </>
  )
}

function NewbieBody({ p, busy, onFire }: { p: Panel; busy: boolean; onFire: (path: string, done: (r: Record<string, unknown>) => string) => void }) {
  const mark = (s: string) => (s === 'claimed' ? '✅' : s === 'ready' ? '🎁' : '⬜')
  return (
    <>
      <p className="sheet-desc">«Обживайся, кабатчик — за первые шаги город отсыпет на бедность.»</p>
      <div className="sheet-list">
        {(p.tasks ?? []).map((t, i) => (
          <div key={i} className={`sheet-task${t.status === 'ready' ? ' rdy' : ''}`}>
            <span className="m">{mark(t.status)}</span>
            <span className="l">{t.label}</span>
            <span className="r">{t.reward}</span>
          </div>
        ))}
      </div>
      <div className="sheet-note">
        {p.perks ? '🎯 Поблажки активны: ' : '⌛ Поблажки выдохлись. '}
        <span className="muted">работники −50% · добыча +25% · ходки быстрее (первые {p.grace_days} дн. и до ур.3)</span>
      </div>
      <button className="btn gold" style={{ marginTop: 14 }} disabled={busy || !p.claimable}
        onClick={() => onFire('newbie', (r) => {
          const t = r.reward ? Object.values(r.reward as Record<string, number>).reduce((s, v) => s + v, 0) : 0
          return t ? `Грамота: +${fmt(t)} в закрома` : 'Награды забраны'
        })}>
        {p.claimable ? '🎁 Забрать награды' : 'Пока забирать нечего'}
      </button>
    </>
  )
}

function ExpedBody({ p, busy, onExped }: { p: Panel; busy: boolean; onExped: (path: string, body: Record<string, unknown> | undefined, ok: (r: Record<string, unknown>) => string) => void }) {
  return (
    <>
      <div className="sheet-stat">
        <span>🟢 Свободно <b>{p.free}/{p.total}</b></span>
        <span>🚶 В пути <b>{p.out}</b></span>
        <span>🎒 Вернулись <b>{p.ready}</b></span>
      </div>

      {!!p.ready && (
        <button className="btn gold" style={{ marginTop: 4 }} disabled={busy}
          onClick={() => onExped('expedition', undefined, (r) => `+${fmt((r.claimed as number) ?? 0)} добра с бригад`)}>
          🎒 Забрать вернувшихся ({p.ready})
        </button>
      )}

      {!!(p.goals && p.goals.length) && (
        <div className="sheet-goals">
          <div className="sheet-sub">💡 На что копить</div>
          {p.goals!.map((g, i) => (
            <div key={i} className="sheet-goal">
              <b>{g.label}</b>
              <span>{g.items.map((it) => `${it.name} ${it.qty}`).join(' · ')}</span>
            </div>
          ))}
        </div>
      )}

      {!!(p.resources && p.resources.length) ? (
        <>
          <div className="sheet-sub" style={{ marginTop: 12 }}>⛏ Отправить за добром <span className="muted">· {p.pay} 🪙/бригада · {p.hours} ч</span></div>
          <div className="exp-grid">
            {p.resources!.map((r) => (
              <button key={r.key} className="exp-cell" disabled={busy}
                onClick={() => onExped('expedition_start', { resource: r.key }, () => `Бригада ушла за ${r.name.toLowerCase()}`)}>
                <ResIcon k={r.key} />
                <span className="en">{r.name}</span>
                <span className="ea">+{r.amount}</span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <p className="muted" style={{ fontStyle: 'italic', marginTop: 12 }}>Все бригады в деле — дождись возврата.</p>
      )}
    </>
  )
}
