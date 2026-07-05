import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { api, errText } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { GoodIcon, ResIcon, fmt } from '../components/icons'

interface Board { name: string; pts: number; zodar: number }
interface Phase { key: string; title: string }
interface Wonder {
  key: string; name: string; emoji: string; blurb: string; bonus: string
  phase: number; phases: Phase[]; phase_title: string
  progress: number; target: number; pct: number; sealed: boolean
  mine_pts: number; mine_zodar: number; board: Board[]
}
interface Item { key: string; name: string; qty: number; pts?: number }
interface Stock { gold: number; gold_pts?: number; res: Item[]; goods: Item[] }
interface Resp { ok?: boolean; wonder: Wonder | null; zodar: number; stock: Stock | null }
interface Contrib extends Resp { award: number }

const DEV = import.meta.env.DEV
const SAMPLE: Resp = {
  wonder: {
    key: 'wall', name: 'Твердыня', emoji: '🏯',
    blurb: 'Недоливск одевается в камень: ров, стены, ворота и детинец — теперь Орде так просто не пройти.',
    bonus: 'Орда приходит слабее — всему городу легче отбиться',
    phase: 1, phases: [{ key: 'foundation', title: 'Ров и фундамент' }, { key: 'walls', title: 'Стены и ворота' }, { key: 'keep', title: 'Башни и детинец' }],
    phase_title: 'Ров и фундамент', progress: 18400, target: 51600, pct: 36, sealed: false,
    mine_pts: 1240, mine_zodar: 6,
    board: [{ name: 'Синий Гоблин', pts: 3400, zodar: 18 }, { name: 'Wendigo', pts: 2100, zodar: 11 }, { name: 'Елена', pts: 1240, zodar: 6 }],
  },
  zodar: 6,
  stock: { gold: 4366, gold_pts: 0.5, res: [{ key: 'wood', name: 'Древесина', qty: 260, pts: 2 }, { key: 'stone', name: 'Камень', qty: 90, pts: 2.5 }, { key: 'clay', name: 'Глина', qty: 40, pts: 2 }], goods: [{ key: 'ale1', name: 'Эль', qty: 12, pts: 5 }, { key: 'roast', name: 'Жаркое', qty: 7, pts: 12 }] },
}

/** Кинетический счётчик: плавно догоняет значение (rAF, ease-out). */
function useCountUp(value: number, ms = 650): number {
  const [n, setN] = useState(value)
  const from = useRef(value)
  useEffect(() => {
    const start = performance.now(); const a = from.current; const b = value
    if (a === b) { setN(b); return }
    let raf = 0
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / ms); const e = 1 - Math.pow(1 - p, 3)
      setN(Math.round(a + (b - a) * e))
      if (p < 1) raf = requestAnimationFrame(tick); else from.current = b
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, ms])
  return n
}

/** Части крепости в порядке возведения. th — % готовности, когда часть «встаёт». */
const CASTLE_ORDER = ['base', 'wall', 'towers', 'keep', 'flag'] as const
const CASTLE_TH: Record<string, number> = { base: 0, wall: 18, towers: 42, keep: 68, flag: 90 }
function partStates(pct: number): Record<string, string> {
  const st: Record<string, string> = {}
  let nowSet = false
  for (const k of CASTLE_ORDER) {
    if (pct >= CASTLE_TH[k]) st[k] = 'built'
    else if (!nowSet) { st[k] = 'now'; nowSet = true }
    else st[k] = 'ghost'
  }
  return st
}
/** Зубцы (мерлоны): n сплошных блоков по ширине w, вырезы между ними. */
function crest(x: number, w: number, topY: number, n: number, mh = 5) {
  const u = w / (n * 2 - 1)
  return Array.from({ length: n }, (_, i) => (
    <rect key={i} className="cp-stone" x={+(x + i * 2 * u).toFixed(2)} y={topY - mh} width={+u.toFixed(2)} height={mh + 0.6} rx="0.5" />
  ))
}

/** Крепость-чудо: части возводятся по мере готовности (стена → башни → донжон →
    знамя). Тёплый камень с объёмом (теневая грань), зубцы, окна-огни, светящиеся
    ворота; знамя загорается по финалу. Не «торт» — читаемый силуэт крепости. */
function Castle({ pct, done }: { pct: number; done: boolean }) {
  const s = partStates(pct)
  return (
    <svg className="wd2-castle" viewBox="0 0 200 128" preserveAspectRatio="xMidYMax meet">
      <defs>
        <linearGradient id="cFace" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f0cd85" /><stop offset="0.35" stopColor="#c99a4c" />
          <stop offset="0.72" stopColor="#8f6531" /><stop offset="1" stopColor="#5a3e1e" />
        </linearGradient>
        <linearGradient id="cShade" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#000" stopOpacity="0.42" /><stop offset="0.6" stopColor="#000" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="cAO" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#000" stopOpacity="0" /><stop offset="1" stopColor="#000" stopOpacity="0.5" />
        </linearGradient>
        <radialGradient id="cGate" cx="50%" cy="32%" r="78%">
          <stop offset="0" stopColor="#ffe6a2" /><stop offset="0.5" stopColor="#d9852a" /><stop offset="1" stopColor="#2a1606" />
        </radialGradient>
        <radialGradient id="cGround" cx="50%" cy="50%" r="50%">
          <stop offset="0" stopColor="#ffb14a" stopOpacity="0.45" /><stop offset="1" stopColor="#ffb14a" stopOpacity="0" />
        </radialGradient>
      </defs>

      <ellipse className="cp-ground" cx="100" cy="120" rx="92" ry="10" fill="url(#cGround)" />

      {/* платформа-основание */}
      <g className={`cp ${s.base}`}>
        <path className="cp-stone" d="M16 121 L184 121 L177 109 L23 109 Z" />
        <rect className="cp-rim" x="24" y="108.4" width="152" height="1.4" rx="0.7" />
      </g>

      {/* крепостная стена с зубцами */}
      <g className={`cp ${s.wall}`}>
        <rect className="cp-stone" x="50" y="88" width="100" height="22" />
        {crest(50, 100, 88, 9)}
        <rect x="50" y="103" width="100" height="7" fill="url(#cAO)" />
      </g>

      {/* фланговые башни */}
      <g className={`cp ${s.towers}`}>
        <rect className="cp-stone" x="28" y="64" width="28" height="46" />
        {crest(28, 28, 64, 4)}
        <rect x="28" y="64" width="11" height="46" fill="url(#cShade)" />
        <rect className="cp-win" x="38.5" y="78" width="3" height="6" rx="1.4" />
        <rect className="cp-win" x="38.5" y="92" width="3" height="6" rx="1.4" />
        <rect className="cp-stone" x="144" y="64" width="28" height="46" />
        {crest(144, 28, 64, 4)}
        <rect x="144" y="64" width="11" height="46" fill="url(#cShade)" />
        <rect className="cp-win" x="158.5" y="78" width="3" height="6" rx="1.4" />
        <rect className="cp-win" x="158.5" y="92" width="3" height="6" rx="1.4" />
      </g>

      {/* центральный донжон + ворота */}
      <g className={`cp ${s.keep}`}>
        <rect className="cp-stone" x="78" y="42" width="44" height="68" />
        {crest(78, 44, 42, 5)}
        <rect x="78" y="42" width="16" height="68" fill="url(#cShade)" />
        <path className="cp-gate" d="M91 110 V99 a9 9 0 0 1 18 0 V110 Z" />
        <rect className="cp-win" x="98" y="56" width="4" height="9" rx="2" />
        <rect className="cp-win" x="86" y="74" width="3.4" height="7" rx="1.6" />
        <rect className="cp-win" x="110.6" y="74" width="3.4" height="7" rx="1.6" />
      </g>

      {/* знамя на донжоне */}
      <g className={`cp ${s.flag} ${done ? 'lit' : ''}`}>
        <line className="cp-pole" x1="100" y1="42" x2="100" y2="21" />
        <path className="cp-flag" d="M100 22 L117 26.5 L100 31 Z" />
      </g>
    </svg>
  )
}

function goldPresets(g: number): { label: string; n: number }[] {
  const out: { label: string; n: number }[] = []
  for (const n of [100, 500]) if (n < g) out.push({ label: `${n}`, n })
  if (g > 0) out.push({ label: 'Всё', n: g })
  return out
}

export default function WonderSheet({ onClose, onOpenArtel, page }: {
  onClose: () => void; onOpenArtel: () => void; page?: boolean
}) {
  const [d, setD] = useState<Resp | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [burst, setBurst] = useState(0)          // ключ ре-триггера вспышки при вкладе
  const [pick, setPick] = useState<Record<string, number>>({})   // обоз: {ключ: сколько грузим}

  useEffect(() => {
    (DEV ? Promise.resolve(SAMPLE) : api<Resp>('wonder'))
      .then(setD).catch(() => setD({ wonder: null, zodar: 0, stock: null }))
  }, [])

  /** Вклад — один атомарный вызов на весь словарь {ключ: кол-во} (сырьё/блюда/золото). */
  async function contribute(items: Record<string, number>) {
    const n = Object.values(items).reduce((a, b) => a + (b || 0), 0)
    if (busy || n <= 0) return
    setBusy(true); setErr(''); haptic('medium')
    try {
      const r: Contrib = DEV
        ? { ...SAMPLE, award: 1, zodar: (d?.zodar ?? 0) + 1, wonder: d?.wonder ? { ...d.wonder, progress: d.wonder.progress + n, pct: Math.min(100, Math.round((d.wonder.progress + n) * 100 / d.wonder.target)), mine_pts: d.wonder.mine_pts + n, mine_zodar: d.wonder.mine_zodar + 1 } : null }
        : await api<Contrib>('wonder/contribute', { items })
      setD({ wonder: r.wonder, zodar: r.zodar, stock: r.stock })
      setBurst((b) => b + 1); setPick({})
      hapticNotify(r.award > 0 ? 'success' : 'warning')
    } catch (e) { setErr(errText(e)); hapticNotify('error') }
    finally { setBusy(false) }
  }

  /** Ставим на грузе ровно n единиц (клампим к остатку). */
  function setLoad(key: string, n: number, qty: number) {
    setPick((p) => ({ ...p, [key]: Math.max(0, Math.min(qty, Math.round(n))) }))
  }

  const w = d?.wonder ?? null
  const pct = useCountUp(w?.pct ?? 0)
  const zodar = useCountUp(d?.zodar ?? 0)
  const mine = useCountUp(w?.mine_pts ?? 0)

  return (
    <div className={page ? 'wd2-page' : 'sv-backdrop'} onClick={page ? undefined : onClose}>
      <div className="wd2" onClick={(e) => e.stopPropagation()}>
        {d === null ? (
          <div className="center" style={{ padding: '80px 0' }}><div className="spin" /></div>
        ) : !w ? (
          <div className="wd2-empty">
            <div className="wd2-empty-ic">🏛</div>
            <p>Сейчас в городе ничего не строят.<br />Артель зодчих ждёт большого дела.</p>
            <button className="btn gold" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
          </div>
        ) : (
          <>
            {/* ── HERO: кинематографичная живая стройка ── */}
            <div className="wd2-hero">
              <div className="wd2-aurora" />
              <div className="wd2-sun" />
              <div className="wd2-stars" />
              <div className="wd2-embers">{Array.from({ length: 11 }, (_, i) => (
                <span key={i} style={{ left: `${7 + i * 8.3}%`, animationDelay: `${(i * 0.7) % 6}s`, animationDuration: `${5 + (i % 4)}s` }} />
              ))}</div>
              <Castle pct={w.pct} done={w.sealed} />
              {burst > 0 && (
                <div key={burst} className="wd2-burst">
                  <i className="wd2-ring" />
                  {Array.from({ length: 7 }, (_, i) => (
                    <b key={i} style={{ '--a': `${i * 51}deg` } as CSSProperties} />
                  ))}
                </div>
              )}
              <div className="wd2-hero-fade" />
              <button className="wd2-x" onClick={() => { haptic('light'); onClose() }} aria-label="Закрыть">✕</button>
            </div>

            <div className="wd2-body">
              {/* заголовок + крупный % — на солидной полосе, не на крепости */}
              <div className="wd2-head2">
                <div className="wd2-h2l">
                  <div className="wd2-name">{w.emoji} {w.name}</div>
                  <div className="wd2-phase">Фаза {w.phase} из {w.phases.length} · {w.phase_title}</div>
                </div>
                <div className="wd2-pct2">{pct}<i>%</i></div>
              </div>

              {/* таймлайн фаз */}
              <div className="wd2-timeline">
                {w.phases.map((p, i) => {
                  const st = i < w.phase - 1 ? 'done' : i === w.phase - 1 ? 'now' : 'wait'
                  const fill = i < w.phase - 1 ? 100 : i === w.phase - 1 ? w.pct : 0
                  return (
                    <div key={p.key} className={`wd2-seg ${st}`} title={p.title}>
                      <i style={{ width: `${fill}%` }} /><span>{st === 'done' ? '✓' : i + 1}</span>
                    </div>
                  )
                })}
              </div>

              <div className="wd2-substats">
                <span>Собрано <b>{fmt(w.progress)}</b> из {fmt(w.target)}</span>
                <span>Вклад <b>{fmt(mine)}</b></span>
                <span>Заработано <b>{zodar} ⚒</b></span>
              </div>

              <div className="wd2-plaque">{w.blurb}</div>
              <div className="wd2-bonus"><span>🎁</span> По готовности: {w.bonus}</div>

              {err && <div className="wd2-err">⚠ {err}<small>Артель ждёт — попробуй снова</small></div>}

              {w.sealed ? (
                <div className="wd2-sealed">🏛 Возведено! Артель раздаёт зодары вкладчикам…</div>
              ) : (
                <>
                  <div className="wd2-lbl">Неси в стройку</div>
                  {(!d.stock || (!d.stock.res.length && !d.stock.goods.length && !d.stock.gold)) ? (
                    <p className="wd2-note">Погреб и склад пусты — добудь ресурсов или свари снеди для стройки.</p>
                  ) : (
                    <>
                      <div className="wd2-treasury">
                        <span className="wd2-tr-ic"><ResIcon k="gold" size={26} /></span>
                        <span className="wd2-tr-meta"><i>Казна</i><b>{fmt(d.stock?.gold ?? 0)}</b></span>
                        <span className="wd2-tr-chips">
                          {goldPresets(d.stock?.gold ?? 0).map((o) => (
                            <button key={o.n} className="wd2-chip" disabled={busy || o.n <= 0} onClick={() => contribute({ gold: o.n })}>{o.label}</button>
                          ))}
                        </span>
                      </div>
                      {(d.stock?.gold ?? 0) > 0 && (
                        <div className="wd2-goldhint">🪙 Золото ценится вполовину: 100 = {Math.round(100 * (d.stock?.gold_pts ?? 0.5))} в стройку</div>
                      )}

                      {((d.stock?.res.length ?? 0) + (d.stock?.goods.length ?? 0)) > 0 && (() => {
                        const items = [...(d.stock?.res ?? []), ...(d.stock?.goods ?? [])]
                        const units = Object.values(pick).reduce((a, b) => a + (b || 0), 0)
                        const value = Math.trunc(Object.entries(pick).reduce(
                          (a, [k, v]) => a + (v || 0) * (items.find((i) => i.key === k)?.pts ?? 0), 0))
                        return (
                          <>
                            <div className="wd2-lbl2">Загрузи обоз — сколько чего</div>
                            <div className="wd2-loaders">
                              {(d.stock?.res ?? []).map((it) => (
                                <Loader key={it.key} icon={<ResIcon k={it.key} size={28} />} name={it.name} qty={it.qty} val={pick[it.key] || 0} busy={busy} onSet={(n) => setLoad(it.key, n, it.qty)} />
                              ))}
                              {(d.stock?.goods ?? []).map((it) => (
                                <Loader key={it.key} icon={<GoodIcon k={it.key} size={28} />} name={it.name} qty={it.qty} val={pick[it.key] || 0} busy={busy} onSet={(n) => setLoad(it.key, n, it.qty)} />
                              ))}
                            </div>
                            <div className="wd2-send">
                              <span className="wd2-send-sum">В стройку <b>{fmt(value)}</b> ценности <i>({fmt(units)} ед.)</i></span>
                              <button className="wd2-send-go" disabled={busy || units <= 0} onClick={() => contribute(pick)}>🐎 Отправить</button>
                            </div>
                          </>
                        )
                      })()}
                    </>
                  )}
                </>
              )}

              {w.board.length > 0 && (
                <>
                  <div className="wd2-lbl">Больше всех вложили</div>
                  <div className="wd2-board">
                    {w.board.map((b, i) => (
                      <div key={i} className={`wd2-brow r${i + 1}`}>
                        <span className="wd2-medal">{['🥇', '🥈', '🥉'][i] ?? i + 1}</span>
                        <span className="wd2-bname">{b.name}</span>
                        <span className="wd2-bpts">{fmt(b.pts)}</span>
                        <span className="wd2-bz">{b.zodar} ⚒</span>
                      </div>
                    ))}
                  </div>
                </>
              )}

              <button className="wd2-artel" onClick={() => { haptic('light'); onOpenArtel() }}>
                <span className="wd2-artel-ic">⚒</span>
                <span>Лавка Артели</span>
                <small>потратить зодары на престиж</small>
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/** Погрузка ресурса: слайдер задаёт, сколько единиц грузим (0…остаток). Число на
    ползунке = ровно то, что уедет (сумма всех → вклад) → показ=действие. */
function Loader({ icon, name, qty, val, busy, onSet }: {
  icon: ReactNode; name: string; qty: number; val: number; busy: boolean; onSet: (n: number) => void
}) {
  const pctFill = qty > 0 ? Math.round((val / qty) * 100) : 0
  return (
    <div className={`wd2-load${val > 0 ? ' on' : ''}`}>
      <span className="wd2-load-ic">{icon}</span>
      <div className="wd2-load-body">
        <div className="wd2-load-top">
          <span className="wd2-load-name">{name}</span>
          <span className="wd2-load-val"><b>{fmt(val)}</b><i>/{fmt(qty)}</i></span>
        </div>
        <div className="wd2-load-row">
          <input className="wd2-range" type="range" min={0} max={qty} value={val} disabled={busy}
            style={{ ['--p' as string]: `${pctFill}%` }}
            onChange={(e) => onSet(+e.target.value)} />
          <button className="wd2-max" disabled={busy} onClick={() => onSet(val >= qty ? 0 : qty)}>{val >= qty ? '0' : 'Всё'}</button>
        </div>
      </div>
    </div>
  )
}
