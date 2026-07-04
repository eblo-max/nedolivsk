import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import CoachTour, { useFirstVisitTour, type Step } from './CoachTour'

// Онбординг первой встречи с ордой (показ 1 раз, флаг localStorage tour_orda):
// объясняет суть, зачем ФРОНТ и как контрить слабость орды стойкой.
const ORDA_STEPS: Step[] = [
  { emoji: '🪓', title: 'Орда орков идёт', body: 'Волна нашествия на весь Недоливск — обороняемся сообща. За окно сбора подними войско: чем больше дружина, тем крепче отпор.' },
  { sel: '[data-tour="orda-trait"]', place: 'bottom', emoji: '💀', title: 'Слабость орды', body: 'У каждой орды своя слабость. Закрой её нужной стойкой (отмечена ★) — тогда способности орка бьют слабее.' },
  { sel: '[data-tour="orda-ready"]', place: 'bottom', emoji: '🛡', title: 'Держи строй', body: 'Нужен ФРОНТ — бойцы в стойке «В строй». Без строя орда прорвётся и выкосит стрелков. Полоска покажет, хватает ли сил.' },
  { sel: '[data-tour="orda-stances"]', place: 'top', emoji: '⚔️', title: 'Встань в бой', body: 'Выбери роль: щит держит фронт, атака рубит, обход чистит проклятья, резерв — надёжная линия. Потом жми «Встать в строй».' },
]

// ── ФАЗА 1: панель сбора «Орда орков» — выбор СТОЙКИ (роли), слабость орды
// (варлорд-трейт) и доска готовности. Автобой; агентность — в композиции. ──
interface Stance { id: string; emoji: string; name: string; blurb: string; role: string; counter: boolean }
interface Comp { tank: number; archer: number; scout: number; ratnik: number; front: number; n: number }
interface Trait { id: string; emoji: string; name: string; counter: string; blurb: string }
interface Prep { id: string; emoji: string; name: string; cost: Record<string, number>; bonus: string; blurb: string }
interface State {
  ok: boolean; active: boolean; n?: number; ready?: number; gather_left?: number
  registered?: boolean; my_stance?: string | null
  trait?: Trait; comp?: Comp; hint?: string; stances?: Stance[]
  preps?: Prep[]; my_preps?: string[]; have?: Record<string, number>
}

const ROLE_EMO: Record<string, string> = { tank: '🛡', archer: '⚔️', scout: '🔭', ratnik: '🗡' }
const RES_EMO: Record<string, string> = { wood: '🪵', grain: '🌾', ore: '⛏️', stone: '🪨' }

// Что делает выбранная стойка против заклинаний орды (для тактической подсказки).
const STANCE_TIP: Record<string, string> = {
  front: '🛡 В строю ты принимаешь удар орды на себя и держишь фронт против 🗣 ярости и 🏹 осады.',
  strike: '⚔️ Твой крит пробивает 🛡 щиты орды, а стрелы рвут призванных 🐺 волков вдвое.',
  flank: '🔭 В обходе ты чистишь 💀 проклятье шамана — дружина не теряет урон.',
  line: '🗡 Надёжная линия строя: держишь удар вместе с фронтом, без слабых мест.',
}

// Тактические подсказки бойцу, пока идёт сбор (крутятся по кругу): роль → заклинания
// орды → слабость → приготовления → явка. Зависят от выбранной стойки и трейта.
function buildTips(d: State): string[] {
  const t: string[] = []
  const st = d.my_stance ? STANCE_TIP[d.my_stance] : ''
  if (st) t.push(st)
  t.push('🪓 По ходу боя орда поднимет 🛡 щит, призовёт 🐺 волков, наложит 💀 проклятье и к концу впадёт в 🗣 ярость.')
  if (d.trait) {
    const cs = d.stances?.find((s) => s.counter)
    t.push(`⚡ Слабость этой орды — ${d.trait.emoji} ${d.trait.name}.` + (cs ? ` Закрыть её поможет стойка «${cs.name}» (★).` : ''))
  }
  if ((d.preps?.length ?? 0) > (d.my_preps?.length ?? 0)) {
    t.push('🛠 Пока есть время — усиль дружину: 🪵 частокол (броня), 🍖 провизия (HP), 🗡 оружейная (урон).')
  }
  t.push('📣 Зови соратников — чем больше и разнообразнее дружина, тем крепче отпор орде.')
  return t
}

function fmt(s: number) { const m = (s / 60) | 0, ss = (s | 0) % 60; return `${m}:${ss < 10 ? '0' : ''}${ss}` }

export default function InvasionSheet({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<State | null>(null)
  const [busy, setBusy] = useState(false)
  const [pick, setPick] = useState<string>('')
  const [left, setLeft] = useState(0)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)
  const tour = useFirstVisitTour('orda')   // онбординг первой орды (1 раз)
  const [tipI, setTipI] = useState(0)      // индекс ротирующейся тактической подсказки
  const navigate = useNavigate()
  const wasReg = useRef(false)

  // Подсказки крутятся раз в 7с, пока боец в строю и идёт сбор.
  useEffect(() => {
    if (!d?.registered) return
    const id = setInterval(() => setTipI((i) => i + 1), 7000)
    return () => clearInterval(id)
  }, [d?.registered])

  // Сбор перешёл в бой (был active+записан → стал не active): уводим бойца на карту
  // смотреть бой и закрываем панель — иначе он видит «орда не идёт» и думает, что орда
  // ушла впустую, хотя бой ИДЁТ на карте.
  useEffect(() => {
    if (d?.active && d?.registered) wasReg.current = true
    else if (wasReg.current && d && !d.active) {
      wasReg.current = false
      navigate('/map')
      onClose()
    }
  }, [d?.active, d?.registered, navigate, onClose])

  async function load() {
    try { const r = await api<State>('invasion/state', {}); setD(r); if (r.gather_left != null) setLeft(r.gather_left) } catch { /* keep */ }
  }
  useEffect(() => {
    load(); const t = setInterval(load, 5000)
    timer.current = setInterval(() => setLeft((v) => Math.max(0, v - 1)), 1000)
    return () => { clearInterval(t); if (timer.current) clearInterval(timer.current) }
  }, [])

  async function join(stance: string) {
    if (busy) return; setBusy(true); haptic('medium')
    try {
      const r = await api<State & { error?: string }>('invasion/join', { stance })
      if (r.ok) { hapticNotify('success'); await load() }
      else hapticNotify('warning')
    } catch { hapticNotify('warning') } finally { setBusy(false) }
  }

  async function prepare(prep: string) {   // ФАЗА 2: усилить дружину ресурсами
    if (busy) return; setBusy(true); haptic('medium')
    try {
      const r = await api<{ ok: boolean; error?: string }>('invasion/prepare', { prep })
      if (r.ok) { hapticNotify('success'); await load() }
      else hapticNotify('warning')
    } catch { hapticNotify('warning') } finally { setBusy(false) }
  }

  const active = d?.active
  const trait = d?.trait
  const comp = d?.comp
  const ready = Math.max(0, Math.min(1, d?.ready ?? 0))
  const win = ready >= 0.7

  return createPortal(
    <>
    <div className="sv-backdrop" onClick={onClose}>
      <div className="chron-sheet" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 4px 8px' }}>
          <span style={{ fontSize: 24 }}>🪓</span>
          <b style={{ fontSize: 17, color: '#e9c98a' }}>Орда орков</b>
          {active && <span style={{ marginLeft: 'auto', color: '#bfa775', fontSize: 13 }}>сбор {fmt(left)}</span>}
          <button onClick={onClose} style={{ marginLeft: active ? 8 : 'auto', background: 'none',
            border: 'none', color: '#a99676', fontSize: 20, cursor: 'pointer', lineHeight: 1 }}>✕</button>
        </div>

        {!active ? (
          <div style={{ padding: '20px 20px 24px', textAlign: 'center', color: '#c2b594' }}>
            <div style={{ fontSize: 40, marginBottom: 8 }}>🏞</div>
            <div style={{ fontWeight: 700, color: '#e9dcc2', marginBottom: 4 }}>Сейчас орда не наступает.</div>
            Последнюю волну отбивали всем миром. Как двинется новая — позовём в чат и сюда.
            <br /><span style={{ fontSize: 12.5, color: '#8a795c' }}>Готовь дружину: снаряга, репутация, ресурсы на приготовления.</span>
          </div>
        ) : (
          <div style={{ padding: '4px 14px 14px' }}>
            {/* Слабость орды (варлорд-трейт) */}
            {trait && (
              <div data-tour="orda-trait" style={{ margin: '8px 0', padding: '10px 12px', borderRadius: 12,
                background: 'rgba(120,40,30,.25)', border: '1px solid #7a3a2a' }}>
                <div style={{ fontWeight: 800, color: '#ffcf9a' }}>{trait.emoji} {trait.name}</div>
                <div style={{ fontSize: 12.5, color: '#d8bfa0', marginTop: 3 }}>{trait.blurb}</div>
              </div>
            )}

            {/* Доска готовности */}
            <div data-tour="orda-ready" style={{ margin: '10px 0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, color: '#bfa775', marginBottom: 4 }}>
                <span>Готовность дружины · {d?.n ?? 0} бойцов</span>
                <span style={{ color: win ? '#8fd14f' : '#e0a94a', fontWeight: 700 }}>{win ? 'победа в кармане' : 'мало сил'}</span>
              </div>
              <div style={{ height: 12, borderRadius: 8, background: '#241a12', overflow: 'hidden', border: '1px solid #4a3420' }}>
                <div style={{ height: '100%', width: `${Math.round(ready * 100)}%`, transition: 'width .5s',
                  background: win ? 'linear-gradient(90deg,#4a8f2a,#8fd14f)' : 'linear-gradient(90deg,#8a4a1a,#e0a94a)' }} />
              </div>
              {d?.hint && <div style={{ marginTop: 6, fontSize: 12.5, fontWeight: 700,
                color: d.hint.includes('НУЖЕН') || d.hint.includes('нужны') ? '#ffb060' : '#9fd07a' }}>{d.hint}</div>}
            </div>

            {/* Состав по ролям */}
            {comp && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '8px 0 12px', justifyContent: 'center' }}>
                {(['tank', 'archer', 'scout', 'ratnik'] as const).map((r) => (
                  <span key={r} style={{ padding: '4px 9px', borderRadius: 999, background: '#241a12',
                    border: '1px solid #4a3420', fontSize: 13, color: comp[r] ? '#e9dcc2' : '#6a5a44' }}>
                    {ROLE_EMO[r]} {comp[r]}
                  </span>
                ))}
              </div>
            )}

            {/* Запись / выбор стойки */}
            {d?.registered ? (
              <>
                <div style={{ textAlign: 'center', padding: '10px 0 6px', color: '#8fd14f', fontWeight: 700 }}>
                  ✅ Ты в строю ({d.stances?.find((s) => s.id === d.my_stance)?.name || 'в резерве'}) · до боя {fmt(left)}
                </div>

                {/* Уйти на карту смотреть сбор/бой (чтобы не залипать в панели) */}
                <button className="btn" onClick={() => { haptic('light'); navigate('/map'); onClose() }}
                  style={{ width: '100%', margin: '0 0 8px', background: 'rgba(38,54,82,.5)', border: '1px solid #37516e', color: '#cfe0f0' }}>
                  🗺 Смотреть на карте
                </button>

                {/* Тактическая подсказка (крутится, пока идёт сбор) */}
                {(() => {
                  const tips = buildTips(d)
                  return tips.length ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 9, minHeight: 46, margin: '2px 0 4px',
                      padding: '9px 12px', borderRadius: 12, background: 'rgba(38,54,82,.3)', border: '1px solid #37516e' }}>
                      <span style={{ fontSize: 18, flex: 'none' }}>💡</span>
                      <span key={tipI} style={{ fontSize: 12.5, color: '#d8e4f0', lineHeight: 1.4, animation: 'sv-fade .4s ease' }}>
                        {tips[tipI % tips.length]}
                      </span>
                    </div>
                  ) : null
                })()}

                {/* ФАЗА 2: военные приготовления — усилить свою дружину до боя */}
                {(d.preps?.length ?? 0) > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: '#bfa775', marginBottom: 7 }}>
                      <span>🛠 Военные приготовления</span>
                      <span style={{ fontSize: 11.5, color: '#8a795c' }}>усиль дружину до боя</span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {d.preps!.map((p) => {
                        const owned = (d.my_preps || []).includes(p.id)
                        const afford = Object.entries(p.cost).every(([r, q]) => (d.have?.[r] ?? 0) >= q)
                        const dis = busy || owned || !afford
                        return (
                          <button key={p.id} disabled={dis} onClick={() => prepare(p.id)}
                            style={{ display: 'flex', alignItems: 'center', gap: 11, textAlign: 'left', width: '100%',
                              padding: '10px 12px', borderRadius: 13, cursor: dis ? 'default' : 'pointer',
                              opacity: (!afford && !owned) ? 0.55 : 1,
                              background: owned ? 'rgba(60,120,40,.22)' : '#1c1610',
                              border: `1.5px solid ${owned ? '#6a9a3a' : '#4a3420'}` }}>
                            <span style={{ fontSize: 22 }}>{p.emoji}</span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontWeight: 700, color: '#e9dcc2' }}>{p.name}
                                <span style={{ color: '#8fd14f', fontSize: 12, fontWeight: 800 }}> {p.bonus}</span></div>
                              <div style={{ fontSize: 11.5, color: '#a99676', marginTop: 1, overflow: 'hidden',
                                textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.blurb}</div>
                            </div>
                            <div style={{ flex: 'none', textAlign: 'right' }}>
                              {owned
                                ? <span style={{ color: '#8fd14f', fontWeight: 700, fontSize: 13 }}>✅ Готово</span>
                                : <span style={{ fontSize: 12.5, whiteSpace: 'nowrap', color: afford ? '#e9dcc2' : '#d88a6a' }}>
                                    {Object.entries(p.cost).map(([r, q]) => `${RES_EMO[r] || r}${q}`).join(' ')}</span>}
                            </div>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <>
                <div style={{ fontSize: 13, color: '#bfa775', marginBottom: 6 }}>Выбери, кем встать в бой:</div>
                <div data-tour="orda-stances" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  {(d?.stances || []).map((s) => (
                    <button key={s.id} disabled={busy} onClick={() => setPick(s.id)}
                      style={{ textAlign: 'left', padding: '9px 11px', borderRadius: 12, cursor: 'pointer',
                        background: pick === s.id ? 'rgba(90,150,50,.22)' : '#1c1610',
                        border: `1.5px solid ${pick === s.id ? '#8fd14f' : (s.counter ? '#c79a44' : '#4a3420')}` }}>
                      <div style={{ fontWeight: 700, color: '#e9dcc2' }}>{s.emoji} {s.name}
                        {s.counter && <span style={{ color: '#ffd27a', fontSize: 11 }}> ★ против орды</span>}</div>
                      <div style={{ fontSize: 11.5, color: '#a99676', marginTop: 2 }}>{s.blurb}</div>
                    </button>
                  ))}
                </div>
                <button className="btn gold" disabled={busy || !pick} onClick={() => join(pick)}
                  style={{ width: '100%', marginTop: 12, opacity: pick ? 1 : 0.5 }}>
                  ⚔️ Встать в строй
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
    {active && tour.show && <CoachTour steps={ORDA_STEPS} onDone={tour.finish} endLabel="⚔️ В бой!" />}
    </>,
    document.body,
  )
}
