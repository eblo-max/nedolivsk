import { useEffect, useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify, pushBack, popBack } from '../telegram'
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
  // retail
  items?: { key: string; name: string; emoji: string; qty: number; price: number; sum: number }[]
  reason?: { emoji: string; text: string } | null
  empty?: boolean
  // upgrade
  level?: number; next?: number; maxed?: boolean; affordable?: boolean; gold_cost?: number
  cost?: { key: string; name: string; need: number; have: number; ok: boolean }[]
  gains?: { label: string; frm: number; to: number }[]
}

const TITLE: Record<string, { ic: string; t: string }> = {
  bonus: { ic: 'bonus', t: 'ОПОХМЕЛ' },
  newbie: { ic: 'scroll', t: 'ГРАМОТА НОВОСЁЛА' },
  expedition: { ic: 'pickaxe', t: 'БРИГАДЫ РАБОТНИКОВ' },
  retail: { ic: 'beer', t: 'ГОСТИ ЖДУТ ЗАКАЗ' },
  upgrade: { ic: 'hammer', t: 'ПЕРЕСТРОЙКА' },
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
  retail: { kind: 'retail', total: 71, reason: { emoji: '🦠', text: 'Поветрие: спрос −15%' }, items: [
    { key: 'ale1', name: 'Эль', emoji: '🍺', qty: 6, price: 8, sum: 46 },
    { key: 'pie', name: 'Пирог', emoji: '🥧', qty: 2, price: 13, sum: 25 },
  ] },
  upgrade: { kind: 'upgrade', level: 2, next: 3, affordable: true, gold_cost: 715,
    cost: [
      { key: 'gold', name: 'Золото', need: 715, have: 1340, ok: true },
      { key: 'wood', name: 'Дерево', need: 220, have: 260, ok: true },
      { key: 'grain', name: 'Зерно', need: 180, have: 90, ok: false },
    ],
    gains: [
      { label: 'Места', frm: 20, to: 25 }, { label: 'Уют', frm: 2, to: 3 },
      { label: 'Доход/ч', frm: 18, to: 26 },
    ] },
}

export default function ActionSheet({ kind, initial, onCache, onState, onClose, flash }: {
  kind: string
  initial?: unknown
  onCache?: (kind: string, data: unknown) => void
  onState: (s: unknown) => void
  onClose: () => void
  flash: (m: string) => void
}) {
  // если панель уже открывалась — сразу рисуем прошлые данные (полная высота, без спиннера),
  // а свежие подтягиваем фоном; первое открытие показывает крупный спиннер
  const [panel, setPanel] = useState<Panel | null>((initial as Panel) ?? null)
  const [busy, setBusy] = useState(false)
  const [closing, setClosing] = useState(false)
  const cache = (d: Panel) => { setPanel(d); onCache?.(kind, d) }

  useEffect(() => {
    let live = true
    api<{ panel: Panel }>('panel', { kind })
      .then((r) => { if (live) cache(r.panel) })
      .catch(() => { if (live) setPanel((p) => p ?? (SAMPLE[kind] ?? { kind, error: true })) })
    return () => { live = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind])

  // пока панель открыта: блокируем прокрутку фона и прячем нижнюю навигацию,
  // иначе навбар (с safe-area снизу) перекрывает низ панели на телефоне
  useEffect(() => {
    const scroll = document.querySelector('.scroll') as HTMLElement | null
    const nav = document.querySelector('.nav') as HTMLElement | null
    const prevOv = scroll?.style.overflowY
    const prevNav = nav?.style.display
    if (scroll) scroll.style.overflowY = 'hidden'
    if (nav) nav.style.display = 'none'
    return () => {
      if (scroll) scroll.style.overflowY = prevOv ?? ''
      if (nav) nav.style.display = prevNav ?? ''
    }
  }, [])

  function close() {
    if (closing) return
    setClosing(true); setTimeout(onClose, 240)
  }

  // нативная кнопка «назад» Telegram закрывает панель (поверх навигации под-экрана)
  useEffect(() => {
    pushBack(close)
    return () => popBack(close)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
      onState(r.state); if (r.panel) cache(r.panel as Panel); hapticNotify('success'); flash(ok(r))
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
          {!panel ? <div className="center" style={{ minHeight: 260 }}><div className="spin" /></div>
            : panel.error ? <p className="muted" style={{ fontStyle: 'italic' }}>Не загрузилось — закрой и попробуй ещё.</p>
              : kind === 'bonus' ? <BonusBody p={panel} busy={busy} onFire={fire} />
                : kind === 'newbie' ? <NewbieBody p={panel} busy={busy} onFire={fire} />
                  : kind === 'retail' ? <RetailBody p={panel} busy={busy} onFire={fire} />
                    : kind === 'upgrade' ? <UpgradeBody p={panel} busy={busy} onFire={fire} />
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

function UpgradeBody({ p, busy, onFire }: { p: Panel; busy: boolean; onFire: (path: string, done: (r: Record<string, unknown>) => string) => void }) {
  if (p.maxed) return <p className="sheet-desc">«Выше строить некуда — ты легенда Недоливска.»</p>
  return (
    <>
      <div className="sheet-sub">ВЫЛОЖИШЬ</div>
      <div className="sheet-list">
        {(p.cost ?? []).map((c, i) => (
          <div key={i} className="sheet-task">
            <ResIcon k={c.key} />
            <span className="l">{c.name}</span>
            <span className="r" style={{ color: c.ok ? 'var(--green)' : 'var(--crimson)' }}>{fmt(c.have)} / {fmt(c.need)}</span>
          </div>
        ))}
      </div>
      <div className="sheet-sub" style={{ marginTop: 14 }}>ПОЛУЧИШЬ · ур. {p.next}</div>
      {(p.gains ?? []).map((g, i) => (
        <div key={i} className="sheet-row"><span>{g.label}</span>
          <b>{g.frm} <span style={{ color: 'var(--brass)' }}>→</span> {g.to}</b></div>
      ))}
      <button className="btn gold" style={{ marginTop: 14 }} disabled={busy || !p.affordable}
        onClick={() => onFire('upgrade', (r) => `Таверна выросла до ур. ${r.level}!`)}>
        {p.affordable ? `⬆ Улучшить до ур. ${p.next}` : 'Не хватает ресурсов'}
      </button>
    </>
  )
}

function RetailBody({ p, busy, onFire }: { p: Panel; busy: boolean; onFire: (path: string, done: (r: Record<string, unknown>) => string) => void }) {
  if (p.empty) return <p className="sheet-desc">«Гости уже разошлись — заказа нет.»</p>
  return (
    <>
      <p className="sheet-desc">«Гости распробовали — хотят выкупить товар прямо из погреба.»</p>
      <div className="sheet-list">
        {(p.items ?? []).map((it, i) => (
          <div key={i} className="sheet-task">
            <span className="m">{it.emoji}</span>
            <span className="l">{it.name} <b style={{ fontFamily: 'var(--num)' }}>×{it.qty}</b></span>
            <span className="r">{fmt(it.sum)} 🪙</span>
          </div>
        ))}
      </div>
      {p.reason && (
        <div className={`retail-why ${p.reason.text.includes('−') ? 'down' : 'up'}`}>
          <span className="rw-ic">{p.reason.emoji}</span>{p.reason.text}
        </div>
      )}
      <div className="sheet-row" style={{ marginTop: 8 }}>
        <span>Налить гостям на</span><b style={{ color: 'var(--gold-2)', fontSize: 16 }}>{fmt(p.total ?? 0)} 🪙</b>
      </div>
      <button className="btn gold" style={{ marginTop: 14 }} disabled={busy}
        onClick={() => onFire('retail_sell', (r) => {
          if (!r.sold) return 'Товар разошёлся'
          const n = r.noble as { name?: string; tip?: number } | null
          const tip = n ? ` · 🎩 +${fmt(n.tip ?? 0)} чаевых` : ''
          return `+${fmt((r.gold as number) ?? 0)} 🪙 · +${r.rep} репутации${tip}`
        })}>
        🍺 Налить гостям
      </button>
      <button className="btn" style={{ marginTop: 9 }} disabled={busy}
        onClick={() => onFire('retail_hold', () => 'Придержал товар')}>
        Придержать товар
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
