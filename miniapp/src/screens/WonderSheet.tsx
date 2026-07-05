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
interface Item { key: string; name: string; qty: number }
interface Stock { gold: number; res: Item[]; goods: Item[] }
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
  stock: { gold: 4366, res: [{ key: 'wood', name: 'Древесина', qty: 260 }, { key: 'stone', name: 'Камень', qty: 90 }, { key: 'clay', name: 'Глина', qty: 40 }], goods: [{ key: 'ale1', name: 'Эль', qty: 12 }, { key: 'roast', name: 'Жаркое', qty: 7 }] },
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

/** Факелы-окна: зажигаются, когда стройка доросла до их высоты (y в % снизу). */
const TORCHES = [{ x: 100, y: 46 }, { x: 31, y: 40 }, { x: 169, y: 40 }, { x: 62, y: 24 }, { x: 138, y: 24 }]

function merlons(x: number, w: number, top: number, n: number) {
  const mw = w / (n * 2 - 1)
  return Array.from({ length: n }, (_, i) => (
    <rect key={i} x={+(x + i * 2 * mw).toFixed(1)} y={top - 4} width={+mw.toFixed(1)} height={5.4} rx={0.6} />
  ))
}
function CastleShapes() {
  return (
    <>
      <rect x="82" y="40" width="36" height="75" rx="1.5" />{merlons(82, 36, 40, 5)}
      <rect x="42" y="70" width="116" height="45" rx="1.2" />{merlons(42, 116, 70, 11)}
      <rect x="18" y="48" width="28" height="67" rx="1.5" />{merlons(18, 28, 48, 4)}
      <rect x="154" y="48" width="28" height="67" rx="1.5" />{merlons(154, 28, 48, 4)}
      <path d="M90 115 V100 a10 10 0 0 1 20 0 V115 Z" className="wd2-gate" />
    </>
  )
}
function CastleArt({ pct, done }: { pct: number; done: boolean }) {
  const h = 120 * Math.min(100, Math.max(0, pct)) / 100
  const litUntil = 120 - h                       // всё, что ниже (y>litUntil) — построено
  return (
    <svg className="wd2-castle" viewBox="0 0 200 120" preserveAspectRatio="xMidYMax meet">
      <defs>
        <linearGradient id="wstone" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffe9b0" /><stop offset="0.4" stopColor="#e0ac54" />
          <stop offset="0.75" stopColor="#a9793a" /><stop offset="1" stopColor="#6a4d24" />
        </linearGradient>
        <clipPath id="wrise"><rect x="0" y={120 - h} width="200" height={h + 0.5} /></clipPath>
      </defs>
      <g className="wd2-ghost"><CastleShapes /></g>
      <g className="wd2-mason" clipPath="url(#wrise)"><CastleShapes /></g>
      {TORCHES.map((t, i) => t.y > litUntil && (
        <circle key={i} className="wd2-torch" cx={t.x} cy={t.y} r={2} />
      ))}
      {pct > 1 && pct < 100 && <line className="wd2-buildline" x1="8" y1={120 - h} x2="192" y2={120 - h} />}
      {done && <g className="wd2-flag"><line x1="100" y1="40" x2="100" y2="20" /><path d="M100 21 L116 25 L100 30 Z" /></g>}
    </svg>
  )
}

function presets(qty: number): { label: string; n: number }[] {
  const out: { label: string; n: number }[] = []
  for (const n of [10, 50]) if (n < qty) out.push({ label: `${n}`, n })
  if (qty > 0) out.push({ label: 'Всё', n: qty })
  return out
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

  useEffect(() => {
    (DEV ? Promise.resolve(SAMPLE) : api<Resp>('wonder'))
      .then(setD).catch(() => setD({ wonder: null, zodar: 0, stock: null }))
  }, [])

  async function give(key: string, n: number) {
    if (busy || n <= 0) return
    setBusy(true); setErr(''); haptic('medium')
    try {
      const r: Contrib = DEV
        ? { ...SAMPLE, award: 1, zodar: (d?.zodar ?? 0) + 1, wonder: d?.wonder ? { ...d.wonder, progress: d.wonder.progress + n, pct: Math.min(100, Math.round((d.wonder.progress + n) * 100 / d.wonder.target)), mine_pts: d.wonder.mine_pts + n, mine_zodar: d.wonder.mine_zodar + 1 } : null }
        : await api<Contrib>('wonder/contribute', { items: { [key]: n } })
      setD({ wonder: r.wonder, zodar: r.zodar, stock: r.stock })
      setBurst((b) => b + 1)
      hapticNotify(r.award > 0 ? 'success' : 'warning')
    } catch (e) { setErr(errText(e)); hapticNotify('error') }
    finally { setBusy(false) }
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
              <CastleArt pct={w.pct} done={w.sealed} />
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
                    <div className="wd2-give">
                      {(d.stock?.res ?? []).map((it) => (
                        <GiveRow key={it.key} icon={<ResIcon k={it.key} size={28} />} name={it.name} qty={it.qty} busy={busy} onGive={(n) => give(it.key, n)} />
                      ))}
                      {(d.stock?.goods ?? []).map((it) => (
                        <GiveRow key={it.key} icon={<GoodIcon k={it.key} size={28} />} name={it.name} qty={it.qty} busy={busy} onGive={(n) => give(it.key, n)} />
                      ))}
                      <GiveRow icon={<ResIcon k="gold" size={28} />} name="Золото" qty={d.stock?.gold ?? 0} busy={busy} gold onGive={(n) => give('gold', n)} />
                    </div>
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

function GiveRow({ icon, name, qty, busy, gold, onGive }: {
  icon: ReactNode; name: string; qty: number; busy: boolean; gold?: boolean; onGive: (n: number) => void
}) {
  const opts = gold ? goldPresets(qty) : presets(qty)
  return (
    <div className="wd2-grow">
      <span className="wd2-gic">{icon}</span>
      <span className="wd2-gname">{name}<i>{fmt(qty)}</i></span>
      <span className="wd2-gchips">
        {opts.map((o) => (
          <button key={o.n} className="wd2-chip" disabled={busy || o.n <= 0} onClick={() => onGive(o.n)}>{o.label}</button>
        ))}
      </span>
    </div>
  )
}
