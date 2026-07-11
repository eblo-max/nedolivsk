import { useState, useEffect, useMemo, useRef } from 'react'
import { api, errText } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { ResIcon, GoodIcon } from '../components/icons'

// ── Типы (зеркало bot/webapi/recipes.experiment_dto + карточка) ──────────────
export interface ExpIngredient { key: string; name: string; emoji: string; have: number; value: number; tags: string[] }
export interface CookbookEntry { key: string; name: string; lore: string; label: string; qty: number }
export interface ExperimentDTO {
  palette: ExpIngredient[]; cost_each: number; output: number; min: number; max: number
  cooldown: number; cooldown_left: number; ai: boolean
  budget_base: number; budget_k: number; budget_floor: number; budget_cap: number
  tiers: [number, string][]; cookbook: CookbookEntry[]
}
interface RecipeCard { key: string; name: string; lore: string; label: string; effects: Record<string, number | boolean>; budget: number; qty: number }
interface ExpResult { ok: true; recipe: RecipeCard; experiment: ExperimentDTO; new_to_world: boolean; first_time: boolean }

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

// эффект → иконка/подпись/класс-цвет (боевой словарь Ф0)
const EFF: Record<string, { ic: string; cls: string; fmt: (v: number | boolean) => string }> = {
  dmg: { ic: '⚔', cls: 'dmg', fmt: (v) => `+${v}` },
  crit: { ic: '✦', cls: 'crit', fmt: (v) => `+${v}%` },
  dodge: { ic: '🌀', cls: 'dodge', fmt: (v) => `+${v}%` },
  hp: { ic: '❤', cls: 'hp', fmt: (v) => `+${v}` },
  antidote: { ic: '☘', cls: 'anti', fmt: () => 'яд' },
}
const EFF_ORDER = ['dmg', 'crit', 'dodge', 'hp', 'antidote']
function effChips(effects: Record<string, number | boolean>) {
  return EFF_ORDER.filter((k) => effects[k]).map((k) => ({ k, ...EFF[k], v: effects[k] }))
}

export default function SecretKitchen({ dto, onResult, onFlash }: {
  dto: ExperimentDTO; onResult: (d: ExperimentDTO) => void; onFlash: (m: string) => void
}) {
  const [sel, setSel] = useState<string[]>([])
  const selRef = useRef<string[]>([])          // синхронное зеркало — устойчиво к батчингу быстрых тапов
  const [phase, setPhase] = useState<'idle' | 'brewing' | 'reveal'>('idle')
  const [card, setCard] = useState<RecipeCard | null>(null)
  const [newWorld, setNewWorld] = useState(false)
  const [firstTime, setFirstTime] = useState(false)
  const [busy, setBusy] = useState(false)
  const [cd, setCd] = useState(dto.cooldown_left)
  const byKey = useMemo(() => Object.fromEntries(dto.palette.map((i) => [i.key, i])), [dto.palette])

  // живой кулдаун (синхронизируется со свежим DTO после эксперимента)
  useEffect(() => { setCd(dto.cooldown_left) }, [dto.cooldown_left])
  useEffect(() => {
    if (cd <= 0) return
    const iv = setInterval(() => setCd((c) => Math.max(0, c - 1)), 1000)
    return () => clearInterval(iv)
  }, [cd])

  // живая оценка силы блюда из выбранного (та же формула, что на сервере)
  const est = useMemo(() => {
    if (sel.length < dto.min) return 0
    const worth = sel.reduce((s, k) => s + (byKey[k]?.value || 0), 0)
    const raw = Math.round(dto.budget_base + worth * dto.budget_k)
    return Math.max(dto.budget_floor, Math.min(dto.budget_cap, raw))
  }, [sel, byKey, dto])
  const tier = useMemo(() => (dto.tiers.find(([c]) => est <= c) || dto.tiers[dto.tiers.length - 1])[1], [est, dto.tiers])
  const ringPct = Math.round(Math.min(1, est / dto.budget_cap) * 100)

  const shortfall = (k: string) => (byKey[k]?.have || 0) < dto.cost_each
  const canBrew = sel.length >= dto.min && sel.length <= dto.max && !sel.some(shortfall) && cd <= 0 && !busy

  function apply(next: string[]) { selRef.current = next; setSel(next) }
  function toggle(k: string) {
    if (busy || phase !== 'idle') return
    const cur = selRef.current
    if (cur.includes(k)) { apply(cur.filter((x) => x !== k)); haptic('light'); return }
    if (cur.length >= dto.max) { onFlash(`Не больше ${dto.max} припасов`); return }
    if (shortfall(k)) { onFlash(`Мало «${byKey[k]?.name}» (нужно ${dto.cost_each})`); hapticNotify('warning'); return }
    apply([...cur, k]); haptic('light')
  }

  async function brew() {
    if (!canBrew) return
    setBusy(true); setPhase('brewing'); haptic('medium')
    try {
      const req = api<ExpResult>('recipe/experiment', { ingredients: sel })
      await sleep(900)                              // минимум показать «повар пробует…»
      const res = await req
      setCard(res.recipe); setNewWorld(res.new_to_world); setFirstTime(res.first_time)
      onResult(res.experiment)
      setPhase('reveal'); hapticNotify('success')
    } catch (e) {
      if (import.meta.env.DEV) {                    // превью без бэкенда: демо-ревил
        setCard({ key: 'tr_dev', name: 'Похмельный разносол боярина', budget: est, qty: dto.output,
          lore: 'Тёмное варево из отборных припасов — с одной ложки и сыт, и в драке лих.',
          label: '', effects: { hp: 24, dmg: 5, crit: 3 } })
        setNewWorld(true); setFirstTime(true); setPhase('reveal'); hapticNotify('success')
        return
      }
      setPhase('idle'); hapticNotify('warning')
      const code = (e as { code?: string })?.code
      onFlash(code === 'cooldown' ? 'Повар переводит дух — подожди'
        : code === 'not_enough' ? 'Не хватает припасов'
        : code === 'bad_combo' ? `Возьми ${dto.min}–${dto.max} разных припаса` : errText(e))
    } finally { setBusy(false) }
  }

  function done() { setPhase('idle'); setCard(null); apply([]); haptic('light') }

  // ── Reveal: рецепт-свиток ──────────────────────────────────────────────
  if (phase === 'reveal' && card) {
    return (
      <div className="sk">
        <div className="sk-reveal">
          <div className="sk-scroll">
            <div className="sk-sheen" />
            {newWorld && <div className="sk-badge new">✦ Впервые в Недоливске</div>}
            {!newWorld && firstTime && <div className="sk-badge known">Записано в книгу</div>}
            <div className="sk-dish"><GoodIcon k="pohlebka" size={58} /></div>
            <div className="sk-name">{card.name}</div>
            <div className="sk-lore">{card.lore}</div>
            <div className="sk-effs">
              {effChips(card.effects).map((c) => (
                <span key={c.k} className={`sk-eff ${c.cls}`}><i>{c.ic}</i>{c.fmt(c.v)}</span>
              ))}
            </div>
            <div className="sk-yield">Сварено <b>{card.qty}</b> порций · в погребе тайных блюд</div>
          </div>
          <button className="btn gold sk-done" onClick={done}>В котёл снова</button>
        </div>
      </div>
    )
  }

  // ── Стол алхимика: котёл + палитра + оценка + CTA + книга ───────────────
  const brewing = phase === 'brewing'
  return (
    <div className="sk">
      <div className={`sk-cauldron ${brewing ? 'brew' : ''} ${sel.length ? 'lit' : ''}`}>
        <div className="sk-vessel" style={{ ['--p' as string]: String(ringPct) }}>
          <div className="sk-fire"><i /><i /><i /></div>
          <svg className="sk-iron" viewBox="0 0 210 196" aria-hidden="true">
            <defs>
              <radialGradient id="skIron" cx="50%" cy="26%" r="82%">
                <stop offset="0" stopColor="#524740" /><stop offset="52%" stopColor="#2b2521" /><stop offset="100%" stopColor="#130f0c" />
              </radialGradient>
              <linearGradient id="skRim" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#7a6b5a" /><stop offset="1" stopColor="#2a231e" />
              </linearGradient>
            </defs>
            <path d="M60 148 l-8 22 16 0 z" fill="#161210" />
            <path d="M150 148 l8 22 -16 0 z" fill="#161210" />
            <path d="M105 154 l-8 20 16 0 z" fill="#0f0c0a" />
            <path d="M28 64 C8 60 8 100 27 100" fill="none" stroke="#241e1a" strokeWidth="8" strokeLinecap="round" />
            <path d="M182 64 C202 60 202 100 183 100" fill="none" stroke="#241e1a" strokeWidth="8" strokeLinecap="round" />
            <path d="M28 66 C28 44 182 44 182 66 C182 122 156 160 105 160 C54 160 28 122 28 66 Z"
              fill="url(#skIron)" stroke="#0c0806" strokeWidth="2.5" />
            <path d="M34 94 C64 114 146 114 176 94" fill="none" stroke="#00000055" strokeWidth="7" />
            <path d="M46 74 C64 60 104 58 122 63" fill="none" stroke="#ffffff1c" strokeWidth="5" strokeLinecap="round" />
            <ellipse cx="105" cy="60" rx="80" ry="20" fill="url(#skRim)" stroke="#0c0806" strokeWidth="2.5" />
            <ellipse cx="105" cy="62" rx="71" ry="14" fill="#0d0906" />
          </svg>
          <div className="sk-broth" />
          <div className="sk-bubbles"><i /><i /><i /><i /></div>
          <div className="sk-drop">
            {sel.map((k, i) => (
              <span key={k} className="sk-in" style={{ ['--i' as string]: String(i) }}><ResIcon k={k} size={30} /></span>
            ))}
          </div>
          {brewing && <div className="sk-steam"><i /><i /><i /></div>}
        </div>
        <div className="sk-gauge">
          {sel.length < dto.min ? (
            <span className="sk-hint">Брось {dto.min}–{dto.max} припаса в котёл</span>
          ) : (
            <><span className="sk-power">Сила ~{est}</span><span className="sk-tier">{tier}</span></>
          )}
        </div>
      </div>

      <div className="sk-palette">
        {dto.palette.map((it) => {
          const on = sel.includes(it.key)
          const idx = sel.indexOf(it.key)
          const low = shortfall(it.key)
          return (
            <button key={it.key} className={`sk-tok ${on ? 'on' : ''} ${low && !on ? 'low' : ''}`}
              onClick={() => toggle(it.key)} disabled={busy || brewing}>
              <span className="sk-emo"><ResIcon k={it.key} size={30} /></span>
              <span className="sk-tn">{it.name}</span>
              <span className="sk-have">{it.have}</span>
              {on && <span className="sk-num">{idx + 1}</span>}
            </button>
          )
        })}
      </div>

      <div className="sk-cost">
        <span>Тратит <b>{dto.cost_each}×</b> каждого припаса</span>
        <span className={dto.ai ? 'sk-ai on' : 'sk-ai'}>{dto.ai ? '✧ повар-виртуоз' : 'повар пробует по-своему'}</span>
      </div>

      <button className={`btn sk-cta ${canBrew ? 'go' : ''}`} disabled={!canBrew} onClick={brew}>
        {brewing ? '⚗ Повар пробует…' : cd > 0 ? `Повар отдыхает · ${cd} с` : sel.length < dto.min ? 'Выбери припасы' : '⚗ Испытать рецепт'}
      </button>

      {dto.cookbook.length > 0 && <Cookbook entries={dto.cookbook} />}
    </div>
  )
}

function Cookbook({ entries }: { entries: CookbookEntry[] }) {
  const [open, setOpen] = useState(false)
  const total = entries.length
  const ref = useRef<HTMLDivElement>(null)
  return (
    <div className="sk-book">
      <button className="sk-book-h" onClick={() => setOpen((o) => !o)}>
        <span>📜 Кулинарная книга <em>{total}</em></span>
        <i className={`sk-chev ${open ? 'up' : ''}`}>›</i>
      </button>
      {open && (
        <div className="sk-book-list" ref={ref}>
          {entries.map((e) => (
            <div key={e.key} className="sk-recipe">
              <span className="sk-r-dish"><GoodIcon k="pohlebka" size={30} /></span>
              <div className="sk-r-mid">
                <span className="sk-r-name">{e.name}</span>
                <span className="sk-r-eff">{e.label}</span>
              </div>
              <span className={`sk-r-qty ${e.qty > 0 ? '' : 'zero'}`}>
                {e.qty > 0 ? <>×{e.qty}</> : <ResIcon k="gold" size={11} />}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
