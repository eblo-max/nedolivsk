import { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { fmt } from '../components/icons'
import BossSprite, { FireProjectile, useBossDirector } from '../components/BossSprite'

// ── Типы (зеркалят DTO из webapp._raid_dto / _api_raid_hit) ──────────────────
interface RaidLoot { icon: string; label: string; pct: number; gear?: boolean }
interface Fighter { name: string; dmg: number; hits: number; mine: boolean }
export interface RaidState {
  id: number; key: string; name: string; emoji: string; sprite: string; blurb: string
  armor: number; status: 'gathering' | 'active' | 'dead' | 'expired'
  n: number; me_registered: boolean; roster: Fighter[]
  gear_pct: number; loot: RaidLoot[]
  gather_left?: number; preview_hp?: number
  hp?: number; max_hp?: number; hp_pct?: number; phase?: number; ends_left?: number
  stun_left?: number; ward_left?: number; curse_left?: number; adds_hp?: number; adds_pct?: number
  my_cd?: number; my_stunned?: boolean
  report?: boolean; won?: boolean; top?: Fighter[]; my_gold?: number; i_fought?: boolean
}
interface Victory {
  name: string; emoji: string; sprite: string; top: Fighter[]
  my_gold: number; winner?: string | null; drop?: string; i_killed?: boolean
}
interface BossOpt { key: string; name: string; emoji: string; sprite: string }
interface HitResp {
  ok: boolean; hit?: boolean; wait?: number; stunned?: boolean
  toast?: string; second_wind?: boolean; crit?: boolean; casts?: string[]
  dmg?: number; adds_dmg?: number; adds_hit?: boolean
  raid?: RaidState | null; dead?: boolean; victory?: Victory
}

const DEV = import.meta.env.DEV

// ── DEV-демо: в превью нет Telegram-подписи → бэкенд не пускает. Локальный бой
// в памяти, чтобы прощёлкать сбор → битву → победу. В прод-сборке вырезается. ──
const demoBoss = (): RaidState => ({
  id: 1, key: 'demon_slime', name: 'Адский Слизень', emoji: '😈', sprite: 'demon_slime',
  blurb: 'Выперло из преисподней прямо посреди торга — туша смолы с рогами, харкает огнём и плодит из себя мелких бесов. Ползёт на кабаки, оставляя выжженный след.',
  armor: 11, status: 'gathering', n: 3, me_registered: false,
  roster: [{ name: 'Гриша Кабан', dmg: 0, hits: 0, mine: false }, { name: 'Авдотья', dmg: 0, hits: 0, mine: false }, { name: 'Прохор', dmg: 0, hits: 0, mine: false }],
  gear_pct: 4, loot: [
    { icon: '⛏️', label: 'Руда ×30–55', pct: 43 }, { icon: '🔩', label: 'Слитки ×15–28', pct: 32 },
    { icon: '🪙', label: '220–420 золота', pct: 21 }, { icon: '🛡', label: 'Эксклюзивная снаряга', pct: 4, gear: true },
  ],
  gather_left: 16, preview_hp: 4200,
})
let _demo: RaidState | null = null
const _fired = new Set<string>()                  // DEV: какие касты уже сработали
const DEMO_BOSSES: BossOpt[] = [
  { key: 'demon_slime', name: 'Адский Слизень', emoji: '😈', sprite: 'demon_slime' },
  { key: 'rat_king', name: 'Крысиный Король', emoji: '🐀', sprite: '' },
  { key: 'bog_troll', name: 'Болотный Тролль', emoji: '👹', sprite: '' },
  { key: 'dragon', name: 'Древний Змей', emoji: '🐲', sprite: '' },
]
function demoApi(path: string, _body: Record<string, unknown>): Promise<unknown> {
  // старт — «босса нет» (admin), чтобы прощёлкать призыв → сбор → бой
  if (path === 'raid') return Promise.resolve({ ok: true, raid: _demo ? { ..._demo } : null, admin: true, bosses: DEMO_BOSSES })
  if (path === 'raid/summon') { _demo = demoBoss(); _fired.clear(); return Promise.resolve({ ok: true, raid: { ..._demo }, admin: true }) }
  if (!_demo) { _demo = demoBoss(); _fired.clear() }
  const b = _demo
  if (path === 'raid/join') {
    b.me_registered = true; b.n = 4
    b.roster = [...b.roster, { name: 'Ты', dmg: 0, hits: 0, mine: true }]
    b.status = 'active'; b.max_hp = 4200; b.hp = 4200; b.hp_pct = 100; b.phase = 1
    b.ends_left = 3600; b.my_cd = 0; b.stun_left = 0; b.ward_left = 0; b.curse_left = 0; b.adds_hp = 0
    return Promise.resolve({ ok: true, raid: { ...b } })
  }
  if (path === 'raid/hit') {
    const crit = Math.random() < 0.25
    const dmg = Math.round((crit ? 520 : 260) * (0.8 + Math.random() * 0.4))
    b.hp = Math.max(0, (b.hp ?? 0) - dmg)
    b.hp_pct = Math.round(100 * b.hp / (b.max_hp ?? 1))
    const me = b.roster.find((r) => r.mine); if (me) { me.dmg += dmg; me.hits++ }
    b.phase = b.hp_pct > 66 ? 1 : b.hp_pct > 33 ? 2 : 3
    b.roster = [...b.roster].sort((x, y) => y.dmg - x.dmg)
    // затухание активных эффектов + бой по бесам
    b.ward_left = Math.max(0, (b.ward_left ?? 0) - 9)
    b.curse_left = Math.max(0, (b.curse_left ?? 0) - 9)
    b.stun_left = Math.max(0, (b.stun_left ?? 0) - 9)
    if ((b.adds_hp ?? 0) > 0) { b.adds_hp = Math.max(0, (b.adds_hp ?? 0) - dmg); b.adds_pct = Math.round(100 * (b.adds_hp ?? 0) / Math.max(1, (b.max_hp ?? 1) * 0.1)) }
    // касты по порогам HP (зеркалит boss.script реального демона)
    const casts: string[] = []
    const fire = (id: string, pct: number, fn: () => void) => { if (b.hp_pct! <= pct && !_fired.has(id)) { _fired.add(id); fn(); casts.push(id) } }
    fire('ward', 84, () => { b.ward_left = 45 })
    fire('summon', 64, () => { b.adds_hp = Math.round((b.max_hp ?? 1) * 0.1); b.adds_pct = 100 })
    fire('roar', 46, () => { b.stun_left = 45 })
    fire('curse', 30, () => { b.curse_left = 45 })
    if (b.hp <= 0) {
      b.status = 'dead'
      const victory: Victory = {
        name: b.name, emoji: b.emoji, sprite: b.sprite, top: b.roster.slice(0, 6),
        my_gold: 600, winner: 'Ты', drop: '🔶 РЕДКИЙ — 🪙 320', i_killed: true,
      }
      return Promise.resolve({ ok: true, hit: true, dead: true, victory })
    }
    return Promise.resolve({ ok: true, hit: true, crit, dmg, casts, toast: `${crit ? '💥 КРИТ! ' : '🗡 '}−${dmg} HP`, raid: { ...b } })
  }
  return Promise.resolve({ ok: true })
}
function raidApi<T = unknown>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  if (DEV) return demoApi(path, body) as Promise<T>
  return api<T>(path, body)
}

// низкий «удар» через Web Audio (тихо, без ассетов)
function thud(strong = false) {
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    const ac = new AC(); const t = ac.currentTime
    const o = ac.createOscillator(), g = ac.createGain()
    o.type = 'triangle'; o.frequency.setValueAtTime(strong ? 150 : 110, t)
    o.frequency.exponentialRampToValueAtTime(40, t + 0.18)
    g.gain.setValueAtTime(strong ? 0.5 : 0.32, t); g.gain.exponentialRampToValueAtTime(0.0008, t + 0.26)
    o.connect(g); g.connect(ac.destination); o.start(t); o.stop(t + 0.28)
    setTimeout(() => ac.close(), 400)
  } catch { /* без звука — ок */ }
}

function secsLabel(s: number): string {
  if (s <= 0) return '0:00'
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60
  const p = (x: number) => String(x).padStart(2, '0')
  return h > 0 ? `${h}:${p(m)}:${p(ss)}` : `${m}:${p(ss)}`
}
/** Локальный тикающий таймер от стартовых секунд (для отсчёта сбора/боя). */
function useTicker(start: number | undefined, on = true): number {
  const [left, setLeft] = useState(start ?? 0)
  useEffect(() => { setLeft(start ?? 0) }, [start])
  useEffect(() => {
    if (!on) return
    const i = setInterval(() => setLeft((x) => Math.max(0, x - 1)), 1000)
    return () => clearInterval(i)
  }, [on])
  return left
}

type Float = { id: number; text: string; crit: boolean; dx: number }

export default function RaidSheet({ onClose, onGold }: { onClose: () => void; onGold?: () => void }) {
  const [st, setSt] = useState<RaidState | null>(null)
  const [loading, setLoading] = useState(true)
  const [gone, setGone] = useState(false)
  const [victory, setVictory] = useState<Victory | null>(null)
  const [busy, setBusy] = useState(false)
  const [admin, setAdmin] = useState(false)                 // показать админ-призыв
  const [bosses, setBosses] = useState<BossOpt[]>([])       // список боссов для призыва
  const [cd, setCd] = useState(0)              // мой локальный кулдаун/оглушение
  const [stunned, setStunned] = useState(false)
  const [floats, setFloats] = useState<Float[]>([])
  const [toast, setToast] = useState<string>('')
  // диапазон хода босса к краям — от ширины экрана (босс реально доходит до бортов)
  const [paceRange] = useState(() => Math.round(Math.min(window.innerWidth, 640) * 0.3))
  const boss = useBossDirector(paceRange)
  const floatId = useRef(0)
  const termRef = useRef(false)        // достигли финала (победа/уход) → стоп-поллинг

  const sprite = st?.sprite || victory?.sprite || ''
  const emoji = st?.emoji || victory?.emoji || '😈'

  const pushFloat = useCallback((text: string, crit: boolean) => {
    const id = ++floatId.current
    setFloats((f) => [...f.slice(-4), { id, text, crit, dx: (Math.random() - 0.5) * 90 }])
    setTimeout(() => setFloats((f) => f.filter((x) => x.id !== id)), 900)
  }, [])

  // загрузка + лайв-поллинг (синхрон чужих ударов); на финале — стоп (termRef)
  const load = useCallback(async () => {
    if (termRef.current) return
    try {
      const r = await raidApi<{ ok: boolean; raid: RaidState | null; admin?: boolean; bosses?: BossOpt[] }>('raid')
      if (r.admin != null) setAdmin(r.admin)
      if (r.bosses) setBosses(r.bosses)
      if (termRef.current) return
      if (!r.raid) { termRef.current = true; setGone(true); setSt(null) }
      else if (r.raid.report) {
        termRef.current = true
        if (r.raid.status === 'dead') setVictory({ name: r.raid.name, emoji: r.raid.emoji, sprite: r.raid.sprite, top: r.raid.top || [], my_gold: r.raid.my_gold || 0, i_killed: false })
        else setGone(true)
      } else { setSt(r.raid) }
    } catch { /* сеть моргнула — оставим прежнее */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    load()
    const i = setInterval(load, 3000)
    return () => clearInterval(i)
  }, [load])

  // сбор истекает ровно сейчас — перезагрузить сразу к 0:00 (бэкенд переведёт в бой),
  // не ждать до 3с следующего поллинга
  useEffect(() => {
    if (st?.status !== 'gathering' || (st.gather_left ?? 0) <= 0) return
    const t = setTimeout(load, ((st.gather_left ?? 0) + 1) * 1000)
    return () => clearTimeout(t)
  }, [st?.status, st?.gather_left, load])

  // кулдаун-тик
  useEffect(() => {
    if (cd <= 0) return
    const i = setInterval(() => setCd((x) => { const n = Math.max(0, x - 1); if (n === 0) setStunned(false); return n }), 1000)
    return () => clearInterval(i)
  }, [cd])

  // синхронизуем мой кулдаун с сервером при апдейте состояния
  useEffect(() => {
    if (st?.status === 'active' && (st.my_cd ?? 0) > 0) { setCd(st.my_cd!); setStunned(!!st.my_stunned) }
  }, [st?.my_cd, st?.my_stunned, st?.status])

  async function join() {
    if (busy) return
    setBusy(true); haptic('medium')
    try {
      const r = await raidApi<{ ok: boolean; raid: RaidState; already?: boolean }>('raid/join')
      if (r.raid) setSt(r.raid)
      hapticNotify('success')
    } catch { /* покажем по перезагрузке */ load() }
    finally { setBusy(false) }
  }

  async function summon(key: string) {
    if (busy) return
    setBusy(true); haptic('medium')
    try {
      const r = await raidApi<{ ok: boolean; raid?: RaidState; error?: string }>('raid/summon', { key })
      if (r.ok && r.raid) {
        termRef.current = false; setGone(false); setVictory(null); setSt(r.raid); hapticNotify('success')
      } else { setToast(r.error === 'busy' ? 'Босс уже есть' : 'Не вышло'); setTimeout(() => setToast(''), 1800); hapticNotify('warning') }
    } catch { hapticNotify('warning') }
    finally { setBusy(false) }
  }

  async function hit() {
    if (busy || cd > 0 || boss.dead) return
    setBusy(true); haptic('rigid')
    try {
      const r = await raidApi<HitResp>('raid/hit', {})
      if (r.dead && r.victory) {
        termRef.current = true; boss.kill(); thud(true); hapticNotify('success')
        setTimeout(() => { setVictory(r.victory!); onGold?.() }, 1100)
        return
      }
      if (r.hit) {
        boss.hit(); thud(!!r.crit)
        if (r.dmg) pushFloat(`${r.crit ? '💥' : ''}−${r.dmg}`, !!r.crit)
        if (r.toast) { setToast(r.toast); setTimeout(() => setToast(''), 1400) }
        if (r.second_wind) { setCd(45); setStunned(true); hapticNotify('warning') }
        if (r.raid) setSt(r.raid)
      } else if (r.wait) {                 // рано (оглушение/кулдаун) — мягко
        setCd(r.wait); setStunned(!!r.stunned); if (r.raid) setSt(r.raid)
        haptic('light')
      }
    } catch (e) {
      const code = (e as { code?: string })?.code
      if (code === 'gone') { termRef.current = false; boss.kill(); hapticNotify('success'); load() }  // босса уже добили — показать сводку «ПОВЕРЖЕН» (а не «Босса нет»)
      else if (code === 'not_started') { load() }   // ещё сбор — вернёмся к экрану сбора
      else if (code === 'not_registered') { setToast('Ты не в строю — запишись в следующий сбор'); setTimeout(() => setToast(''), 1800) }
    } finally { setBusy(false) }
  }

  // ── РЕНДЕР ────────────────────────────────────────────────────────────────
  const wrap = (inner: React.ReactNode) => (
    <div className="raid-root">
      <div className="raid-vign" />
      {inner}
      <button className="raid-x" onClick={() => { haptic('light'); onClose() }}>✕</button>
    </div>
  )

  if (loading) return wrap(<div className="raid-load">Высматриваем тварь…</div>)

  if (victory) {
    const top = victory.top || []
    return wrap(
      <div className="raid-end win">
        <div className="raid-stage dead big">
          {sprite ? <BossSprite sprite={sprite} anim="death" playId={1} loop frameStart={3} frameCount={6} durSec={0.95} width={Math.min(Math.round(window.innerWidth * 1.5), 560)} /> : <div className="raid-emo">{emoji}</div>}
          <div className="raid-burst" />
        </div>
        <div className="raid-end-ttl">{victory.name.toUpperCase()} ПОВЕРЖЕН!</div>
        <p className="raid-end-sub">Всем миром завалили зверюгу — кабаки гудят.</p>
        {victory.my_gold > 0 && <div className="raid-reward">🪙 Твоя доля: <b>+{fmt(victory.my_gold)}</b></div>}
        {victory.drop && victory.i_killed && <div className="raid-drop">{victory.winner ? `${victory.winner}: ` : ''}{victory.drop}</div>}
        {!victory.i_killed && <p className="raid-note">Награда и трофей — в мошне и уведомлениях.</p>}
        {top.length > 0 && (
          <div className="raid-board">
            <div className="raid-board-h">Кто рубился</div>
            {top.slice(0, 6).map((f, i) => (
              <div key={i} className={`raid-row${f.mine ? ' mine' : ''}`}>
                <span className="raid-rk">{i + 1}</span><span className="raid-nm">{f.name}</span>
                <span className="raid-dm">{fmt(f.dmg)}</span>
              </div>
            ))}
          </div>
        )}
        <button className="btn gold raid-done" onClick={() => { haptic('light'); onClose() }}>🍺 Готово</button>
      </div>
    )
  }

  if (gone || !st) {
    return wrap(
      <div className="raid-end">
        <div className="raid-emo big">🌫️</div>
        <div className="raid-end-ttl">Босса нет</div>
        <p className="raid-end-sub">Либо уже завалили, либо тварь уползла зализывать раны. В другой раз шевелись живее.</p>
        {admin && bosses.length > 0 && (
          <div className="raid-summon">
            <div className="raid-summon-h">⚔️ Призвать босса <em>админ</em></div>
            <p className="raid-summon-sub">Сбор 20 мин · анонс во все чаты + пуш в ЛС активным за 7 дней.</p>
            <div className="raid-summon-grid">
              {bosses.map((b) => (
                <button key={b.key} className="raid-summon-b" disabled={busy} onClick={() => summon(b.key)}>
                  <span className="raid-summon-emo">{b.emoji}</span>
                  <span className="raid-summon-nm">{b.name}</span>
                </button>
              ))}
            </div>
            {toast && <div className="raid-toast">{toast}</div>}
          </div>
        )}
        <button className="btn gold raid-done" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    )
  }

  // ── ФАЗА СБОРА ──
  if (st.status === 'gathering') {
    return <GatherView st={st} busy={busy} onJoin={join} onClose={() => { haptic('light'); onClose() }} sprite={sprite} emoji={emoji} />
  }

  // ── ФАЗА БИТВЫ ──
  return (
    <BattleView
      st={st} cd={cd} stunned={stunned} busy={busy} floats={floats} toast={toast}
      boss={boss} onHit={hit} onClose={() => { haptic('light'); onClose() }} sprite={sprite} emoji={emoji}
    />
  )
}

// ── Экран сбора ──────────────────────────────────────────────────────────────
function GatherView({ st, busy, onJoin, onClose, sprite, emoji }: {
  st: RaidState; busy: boolean; onJoin: () => void; onClose: () => void; sprite: string; emoji: string
}) {
  const left = useTicker(st.gather_left)
  return (
    <div className="raid-root">
      <div className="raid-vign" />
      <button className="raid-x" onClick={onClose}>✕</button>
      <div className="raid-gather">
        <div className="raid-stage gather big slimebox">
          {sprite ? <BossSprite sprite={sprite} anim="slime_move" width={Math.min(Math.round(window.innerWidth * 2.2), 860)} /> : <div className="raid-emo">{emoji}</div>}
          <div className="raid-shadow" />
        </div>
        <div className="raid-name">{emoji} {st.name}</div>
        <div className="raid-tag">⚔️ приближается — поднимай весь Недоливск</div>
        <p className="raid-blurb">{st.blurb}</p>

        <div className="raid-meta">
          <div className="raid-meta-i"><span className="k">До битвы</span><b className={left < 60 ? 'hot' : ''}>{secsLabel(left)}</b></div>
          <div className="raid-meta-i"><span className="k">В строю</span><b>{st.n}</b></div>
          <div className="raid-meta-i"><span className="k">Шанс снаряги</span><b>{st.gear_pct}%</b></div>
        </div>

        <LootBox loot={st.loot} />
        {st.roster.length > 0 && (
          <div className="raid-roster">
            {st.roster.slice(0, 8).map((f, i) => <span key={i} className={`raid-chip${f.mine ? ' mine' : ''}`}>⚔️ {f.name}</span>)}
          </div>
        )}
        <p className="raid-rule">Награду берёт тот, кто реально дрался — один тап мимо. Бить можно прямо отсюда, как тварь дойдёт.</p>

        {st.me_registered ? (
          <button className="btn raid-joined" disabled>✓ Ты в строю — жди начала битвы</button>
        ) : (
          <button className="btn gold raid-join" disabled={busy} onClick={onJoin}>⚔️ Встать в строй</button>
        )}
      </div>
    </div>
  )
}

// ── Экран битвы ──────────────────────────────────────────────────────────────
function BattleView({ st, cd, stunned, busy, floats, toast, boss, onHit, onClose, sprite, emoji }: {
  st: RaidState; cd: number; stunned: boolean; busy: boolean; floats: Float[]; toast: string
  boss: ReturnType<typeof useBossDirector>; onHit: () => void; onClose: () => void; sprite: string; emoji: string
}) {
  const ends = useTicker(st.ends_left)
  const phase = st.phase ?? 1
  const hpPct = st.hp_pct ?? 0
  // босс ДОМИНИРУЕТ сцену — кадр шире экрана, прозрачные поля уходят за края
  const [bw, setBw] = useState(() => Math.min(Math.round(window.innerWidth * 1.42), 620))
  useEffect(() => {
    const f = () => setBw(Math.min(Math.round(window.innerWidth * 1.42), 620))
    window.addEventListener('resize', f); return () => window.removeEventListener('resize', f)
  }, [])
  const attacking = boss.anim === 'cleave' || boss.anim === 'smash' || boss.anim === 'fire'  // приём → тряхнём сцену
  const firing = boss.anim === 'fire'           // выдох огня → багрово-огненная вспышка
  // ИНТРО: слизень оборачивается демоном (transform) при входе в бой, потом — патруль
  const [intro, setIntro] = useState(true)
  // кольцо-удар: щёлкает на каждый take_hit (playId меняется при ударе)
  const [impact, setImpact] = useState(0)
  useEffect(() => { if (!intro && boss.anim === 'hit') setImpact((x) => x + 1) }, [boss.playId, boss.anim, intro])
  // ФАЕРБОЛ: на выдох огня вылетает снаряд из пасти и летит в сторону струи (огонь
  // в спрайте идёт ПРОТИВ facing), потом взрыв. Дальность — чтобы остаться в кадре.
  const [proj, setProj] = useState<{ id: number; dir: number; x0: number } | null>(null)
  useEffect(() => {
    if (!intro && boss.anim === 'fire') {
      const dir = -boss.facing
      setProj({ id: Date.now(), dir, x0: boss.pos + dir * 38 })
    }
  }, [boss.playId, boss.anim, intro, boss.facing, boss.pos])
  // КАСТЫ: ловим МОМЕНТ появления каждого заклинания (своё/чужое — через поллинг) →
  // босс воздевает руки (анимация cast) + драматичный баннер. Знаем КОНКРЕТНО какое.
  const wardOn = (st.ward_left ?? 0) > 0, curseOn = (st.curse_left ?? 0) > 0
  const addsOn = (st.adds_hp ?? 0) > 0, stunOn = (st.stun_left ?? 0) > 0
  const prevSpell = useRef({ ward: wardOn, curse: curseOn, adds: addsOn, stun: stunOn })
  const [castBanner, setCastBanner] = useState<{ id: number; k: string; t: string } | null>(null)
  useEffect(() => {
    const p = prevSpell.current
    prevSpell.current = { ward: wardOn, curse: curseOn, adds: addsOn, stun: stunOn }
    if (intro || boss.dead) return
    const fired = (wardOn && !p.ward) ? { k: 'ward', t: '🛡 ЩИТ ВОЗДВИГНУТ' }
      : (curseOn && !p.curse) ? { k: 'curse', t: '💀 ПРОКЛЯТЬЕ' }
      : (addsOn && !p.adds) ? { k: 'adds', t: '👹 ПРИЗЫВ БЕСОВ' }
      : (stunOn && !p.stun) ? { k: 'roar', t: '🗣 ОГЛУШАЮЩИЙ РЁВ' } : null
    if (fired) {
      boss.cast(); setCastBanner({ id: Date.now(), ...fired })
      const tm = setTimeout(() => setCastBanner(null), 1700)
      return () => clearTimeout(tm)
    }
  }, [wardOn, curseOn, addsOn, stunOn, intro, boss])
  // живой обратный отсчёт активных эффектов (тикает локально, освежается поллингом)
  const [fxT, setFxT] = useState({ ward: 0, curse: 0, stun: 0 })
  useEffect(() => { setFxT({ ward: st.ward_left ?? 0, curse: st.curse_left ?? 0, stun: st.stun_left ?? 0 }) },
    [st.ward_left, st.curse_left, st.stun_left])
  useEffect(() => {
    const i = setInterval(() => setFxT((t) => ({ ward: Math.max(0, t.ward - 1), curse: Math.max(0, t.curse - 1), stun: Math.max(0, t.stun - 1) })), 1000)
    return () => clearInterval(i)
  }, [])
  // баннер смены фазы (1→2 разъярён, 2→3 бешенство) — РАЗ НА ФАЗУ: трекаем МАКСИМУМ,
  // чтобы хил «второго дыхания» (фаза 3→2→снова 3) не повторял баннер (как анонс в чате)
  const maxPhase = useRef(phase)
  const [pbanner, setPanner] = useState<{ id: number; text: string; rage: boolean } | null>(null)
  useEffect(() => {
    if (phase > maxPhase.current) {
      maxPhase.current = phase
      setPanner({ id: Date.now(), text: phase >= 3 ? '🔥 БЕШЕНСТВО' : '🔥 РАЗЪЯРЁН', rage: phase >= 3 })
      const t = setTimeout(() => setPanner(null), 1500)
      return () => clearTimeout(t)
    }
  }, [phase])
  // статус-эффекты (модерн-пилюли с живым отсчётом / процентом миньонов)
  const fx: { k: string; icon: string; label: string; sub: string }[] = []
  if (stunOn) fx.push({ k: 'roar', icon: '😵', label: 'Оглушение', sub: `${fxT.stun}с` })
  if (addsOn) fx.push({ k: 'adds', icon: '👹', label: 'Бесы', sub: `${st.adds_pct}%` })
  if (wardOn) fx.push({ k: 'ward', icon: '🛡', label: 'Щит', sub: `${fxT.ward}с` })
  if (curseOn) fx.push({ k: 'curse', icon: '💀', label: 'Проклятье', sub: `${fxT.curse}с` })
  const adds = addsOn

  return (
    <div className={`raid-root battle ph${phase}`}>
      <div className="raid-vign" />
      <div className={`raid-fxflash${attacking ? ' on' : ''}${firing ? ' fire' : ''}`} aria-hidden />
      {!intro && wardOn && <div className="raid-aura ward" aria-hidden />}
      {!intro && curseOn && <div className="raid-aura curse" aria-hidden />}
      {pbanner && <div key={`pb${pbanner.id}`} className={`raid-pbanner${pbanner.rage ? ' rage' : ''}`}>{pbanner.text}</div>}
      {castBanner && <div key={`cb${castBanner.id}`} className={`raid-castbanner ${castBanner.k}`}>{castBanner.t}</div>}
      <button className="raid-x" onClick={onClose}>✕</button>

      <div className="raid-hud-top">
        <div className="raid-name sm">{emoji} {st.name}</div>
        {phase >= 2 && <div className={`raid-phaseband p${phase}`}>{phase >= 3 ? '☠ БЕШЕНСТВО' : '🔥 РАЗЪЯРЁН'}</div>}
        <div className="raid-sub">бронь {st.armor} · в деле {st.n} · уйдёт {secsLabel(ends)}</div>
      </div>

      <div className="raid-embers" aria-hidden>
        {Array.from({ length: 7 }).map((_, i) => <span key={i} className="raid-ember" />)}
      </div>

      <div className={`raid-arena${attacking ? ' attacking' : ''}${firing ? ' firing' : ''}`}>
        <div className={`raid-stage battle big${boss.dead ? ' dead' : ''}${wardOn ? ' warded' : ''}${curseOn ? ' cursed' : ''}`}>
          {sprite ? (intro ? (
            // заставка: слизень оборачивается демоном (по центру, без хода)
            <div className="raid-mover">
              <div className="raid-facer">
                <BossSprite sprite={sprite} anim="transform" playId={1} width={bw} onRest={() => setIntro(false)} />
                <div className="raid-shadow big" />
              </div>
            </div>
          ) : (
            <>
              <div className="raid-mover" style={{ transform: `translateX(${boss.pos}px)`, transition: `transform ${boss.moveMs}ms ease-in-out` }}>
                <div className="raid-facer" style={{ transform: `scaleX(${boss.facing})` }}>
                  <BossSprite sprite={sprite} anim={boss.anim} playId={boss.playId} width={bw} onRest={boss.onRest} dim={(st.ward_left ?? 0) > 0} />
                  <div className="raid-shadow big" />
                </div>
              </div>
              {proj && <FireProjectile key={proj.id} x0={proj.x0} dir={proj.dir}
                fly={Math.round(window.innerWidth * 0.3)} y={Math.round(bw * 160 / 288 * 0.4)}
                size={Math.round(bw * 0.18)} onDone={() => setProj((p) => (p && p.id === proj.id ? null : p))} />}
            </>
          )) : <div className="raid-emo huge">{emoji}</div>}
          {impact > 0 && <div key={impact} className="raid-impact" />}
          {floats.map((f) => (
            <span key={f.id} className={`raid-float${f.crit ? ' crit' : ''}`} style={{ ['--dx' as string]: `${f.dx}px` } as React.CSSProperties}>{f.text}</span>
          ))}
          {adds && <div className="raid-adds">👹×{Math.max(1, Math.round((st.adds_pct ?? 0) / 20))}</div>}
        </div>

        <div className="raid-hpwrap">
          <div className={`raid-hpbar ph${phase}`}>
            <div className="raid-hp-ghost" style={{ width: `${hpPct}%` }} />
            <div className="raid-hp-fill" style={{ width: `${hpPct}%` }} />
            {(st.ward_left ?? 0) > 0 && <div className="raid-hp-ward" />}
            <span className="raid-hp-txt">{fmt(Math.max(0, st.hp ?? 0))} / {fmt(st.max_hp ?? 0)} · {hpPct}%</span>
          </div>
        </div>

        {fx.length > 0 && (
          <div className="raid-fx">
            {fx.map((e) => (
              <span key={e.k} className={`raid-fxchip ${e.k}`}>
                <i className="raid-fxchip-i">{e.icon}</i>
                <b>{e.label}</b><em>{e.sub}</em>
              </span>
            ))}
          </div>
        )}

        {toast && <div className="raid-toast">{toast}</div>}
      </div>

      <div className="raid-action">
        {st.roster.length > 0 && (
          <div className="raid-mini">
            {st.roster.slice(0, 3).map((f, i) => (
              <span key={i} className={`raid-mini-i${f.mine ? ' mine' : ''}`}>{i + 1}. {f.name} · {fmt(f.dmg)}</span>
            ))}
          </div>
        )}
        {cd > 0 ? (
          <button className="btn raid-hit wait" disabled>
            {stunned ? `😵 Оглушён — ${secsLabel(cd)}` : `⏳ Передышка — ${secsLabel(cd)}`}
          </button>
        ) : (
          <button className={`btn raid-hit${adds ? ' adds' : ''}`} disabled={busy} onClick={onHit}>
            {adds ? '👹 БЕЙ БЕСОВ' : '⚔ БЕЙ'}
          </button>
        )}
      </div>
    </div>
  )
}

function LootBox({ loot }: { loot: RaidLoot[] }) {
  if (!loot?.length) return null
  return (
    <div className="raid-loot">
      <div className="raid-loot-h">🎁 С туши падёт</div>
      {loot.map((l, i) => (
        <div key={i} className={`raid-loot-i${l.gear ? ' gear' : ''}`}>
          <span className="li">{l.icon}</span><span className="ll">{l.label}</span><span className="lp">{l.pct}%</span>
        </div>
      ))}
    </div>
  )
}
