import { useEffect, useRef, useState, useCallback } from 'react'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'
import { fmt } from '../components/icons'
import BossSprite, { FireProjectile, useBossDirector, bossCfg } from '../components/BossSprite'

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
  pit_n?: number; pit_who?: string[]; tenure_pct?: number     // 🔒 острог + 📖 стаж
  my_cd?: number; my_stunned?: boolean; my_pit?: number
  report?: boolean; won?: boolean; top?: Fighter[]; my_gold?: number; i_fought?: boolean
  flask?: { drunk?: string[] | null; options: { key: string; name: string; emoji: string; label: string; qty: number }[] }
  barks?: Record<string, string>   // реплики босса-субтитры: intro/ward/curse/summon/roar/death
  lore?: string[]                  // лор-реплики на сборе (речевое облако, цикл)
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
const demoBoss = (key = 'demon_slime'): RaidState => {
  const base: RaidState = {
    id: 1, key: 'demon_slime', name: 'Адский Слизень', emoji: '😈', sprite: 'demon_slime',
    flask: { drunk: null, options: [
      { key: 'ale3', name: 'Эль выдержанный', emoji: '🍺', label: '+7 урона', qty: 3 },
      { key: 'wine', name: 'Вино', emoji: '🍷', label: '+6% крита', qty: 2 },
      { key: 'sbiten', name: 'Сбитень', emoji: '🫖', label: 'снимает проклятье', qty: 1 },
    ] },
    blurb: 'Выперло из преисподней прямо посреди торга — туша смолы с рогами, харкает огнём и плодит из себя мелких бесов. Ползёт на кабаки, оставляя выжженный след.',
    armor: 11, status: 'gathering', n: 3, me_registered: false,
    roster: [{ name: 'Гриша Кабан', dmg: 0, hits: 0, mine: false }, { name: 'Авдотья', dmg: 0, hits: 0, mine: false }, { name: 'Прохор', dmg: 0, hits: 0, mine: false }],
    gear_pct: 4, loot: [
      { icon: '⛏️', label: 'Руда ×30–55', pct: 43 }, { icon: '🔩', label: 'Слитки ×15–28', pct: 32 },
      { icon: '🪙', label: '220–420 золота', pct: 21 }, { icon: '🛡', label: 'Эксклюзивная снаряга', pct: 4, gear: true },
    ],
    gather_left: 16, preview_hp: 4200,
  }
  if (key === 'jailer') return {
    ...base, key: 'jailer', name: 'Батог Мясомял', emoji: '🔨', sprite: 'jailer',
    armor: 16, preview_hp: 5200, barks: JAILER_BARKS, lore: JAILER_LORE, gear_pct: 6,
    blurb: 'Тридцать лет он держал лучшую корчму на тракте — пока не схоронил жену да малую дочь, а с ними и всё людское. Ныне Батог Мясомял, городской кат, знает один закон: кто пил да гулял — тот виновен. Из ямы под ратушей он встаёт с дубиной, что валит быка, и связкой кандалов на буянов; земля гудит под его поступью, стража сползается на рёв. В одиночку не суйся — закуёт, засадит и запорет до костей. Только всем Недоливском свалим ката.',
    // ЗЕРКАЛО _raid_loot_dto('jailer') → bot/game/raid.py BOSSES['jailer'].loot. Держать в синхроне!
    loot: [
      { icon: '🪵', label: 'Древесина ×45–80', pct: 39.5 }, { icon: '📦', label: 'Слитки ×24–44', pct: 34 },
      { icon: '🪙', label: '360–660 золота', pct: 20.5 }, { icon: '🛡', label: 'Эксклюзивная снаряга', pct: 6, gear: true },
    ],
  }
  return base
}
// Лор-реплики Тюремщика на сборе (демо; в проде — из raid.py Boss.lore)
const JAILER_LORE: string[] = [
  'Думаете, Батог с колыбели такой? Тридцать годков держал я корчму «Тёплый Очаг» — лучшую на тракте.',
  'Марьюшка, жёнушка, разливала гостям — от одной её улыбки и хмель слаще казался.',
  'А доченька, Алёнка, семи годков, меж столов порхала: каждому — кружку да ласковое словцо.',
  'Вечерами клала головку мне на плечо: „Тятя, спой“. И голосок её — что колокольчик по первому снегу.',
  'В ту осень заехали гуляки — сытые, злые, хмельные. Крушили всё. Я сказал: будет, по домам.',
  'Они лишь смеялись. А в ночь подпёрли двери снаружи колом… и пустили по крыше красного петуха.',
  'Проснулся в дыму. Рвусь в горницу — балка рухнула поперёк. Слышу: „Тя-тя-а!“ — Алёнка зовёт…',
  '…и звала, пока не смолкла. Я не добрался. Не добрался, слышите вы?',
  'Наутро выгреб из золы два колечка — своё да её, совсем крохотное. Всё, что осталось от «Очага».',
  'Так и стал катом. Двадцать годков в остроге отстоял — насмотрелся на вас, гуляк, на десять жизней.',
  'Батог мой не простой: что зарубка — то чья-то пьяная ночка. Живого места на нём уже нет.',
  'Э, да что душу травить. Раз уж ждём народ — потешу вас, каких дурней сюда волокли.',
  'Мужик по пьяни в чужую избу забрёл, лёг да уснул. Хозяйка утром: „Ты чей будешь?“ — „Твой, Люба, твой!“ А её Клавдией звать.',
  'Другой сам в камеру просился — от жены хоронился. „У вас, — грит, — хоть сковородой не достанет.“ Неделю жил, за уши не выволочь.',
  'Третий у соседа забор свёл — свой чинить. У того самого соседа, с кем за этот забор третий год и грызётся.',
  'Бабка самогон гнала — до того забористый, что петух с одного глотка по-людски заговорил. Забрал обоих: и бабку, и петуха-свидетеля.',
  'Один нарочно окно в управе высадил — чтоб посадили. „Три годика, — молит, — дай, от тёщи отдохну!“',
  'Штраф мне гусём принёс. Гусь вырвался, мэра за ляжку — цап! Мэр гуся и помиловал: „Хоть кто-то, — грит, — в городе при деле.“',
  'Бабу — мужа хватилась, пропал! Через три дня в соседской бане отрыли. „Я, — грит, — в отъезде был, по делам.“ Три дня в бане.',
  'Сборщику податей палец откусил — „за колбасу, — грит, — принял“. Тот теперь подати в перчатках считает.',
  'А отчего Недоливск-то? Шинкарь на палец недолил — ему кружкой в лоб. С того и повелось: что ни день — недолив да мордобой.',
  'Ну да посмеялись — и будет. Батог не за смехом пришёл. За Алёнку пришёл. Готовьтесь, голубчики.',
]
// Реплики Тюремщика (демо; в проде — из raid.py Boss.barks)
const JAILER_BARKS: Record<string, string> = {
  intro: 'Догулялись, пьянь. Батог пришёл — всех перепишу да в яму.',
  ward: 'Дубьём меня? А ну к стенке, пёс!',
  curse: 'Держи кандалы, гуляка!',
  summon: 'Стража-а! Волоки всю ораву сюда!',
  pit: 'Тебя, буян, — в острог! Волоки за решётку, к остальным!',
  death: 'Кто ж… теперь… стеречь будет… голытьбу…',
}
let _demo: RaidState | null = null
const _fired = new Set<string>()                  // DEV: какие касты уже сработали
const DEMO_BOSSES: BossOpt[] = [
  { key: 'jailer', name: 'Батог Мясомял', emoji: '🔨', sprite: 'jailer' },
  { key: 'demon_slime', name: 'Адский Слизень', emoji: '😈', sprite: 'demon_slime' },
  { key: 'rat_king', name: 'Крысиный Король', emoji: '🐀', sprite: '' },
  { key: 'bog_troll', name: 'Болотный Тролль', emoji: '👹', sprite: '' },
  { key: 'dragon', name: 'Древний Змей', emoji: '🐲', sprite: '' },
]
function demoApi(path: string, _body: Record<string, unknown>): Promise<unknown> {
  // старт — «босса нет» (admin), чтобы прощёлкать призыв → сбор → бой
  if (path === 'raid') return Promise.resolve({ ok: true, raid: _demo ? { ..._demo } : null, admin: true, bosses: DEMO_BOSSES })
  if (path === 'raid/summon') { _demo = demoBoss(String(_body.key || 'demon_slime')); _fired.clear(); return Promise.resolve({ ok: true, raid: { ..._demo }, admin: true }) }
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
    const ten = b.key === 'jailer' ? (b.tenure_pct ?? 0) : 0   // 📖 стаж режет урон (как на сервере)
    const dmg = Math.round((crit ? 520 : 260) * (0.8 + Math.random() * 0.4) * (1 - ten / 100))
    b.hp = Math.max(0, (b.hp ?? 0) - dmg)
    b.hp_pct = Math.round(100 * b.hp / (b.max_hp ?? 1))
    const me = b.roster.find((r) => r.mine); if (me) { me.dmg += dmg; me.hits++ }
    b.phase = b.hp_pct > 66 ? 1 : b.hp_pct > 33 ? 2 : 3
    b.roster = [...b.roster].sort((x, y) => y.dmg - x.dmg)
    // затухание активных эффектов + бой по бесам
    b.ward_left = Math.max(0, (b.ward_left ?? 0) - 9)
    b.curse_left = Math.max(0, (b.curse_left ?? 0) - 9)
    b.stun_left = Math.max(0, (b.stun_left ?? 0) - 9)
    b.my_pit = Math.max(0, (b.my_pit ?? 0) - 9); b.my_cd = Math.max(0, (b.my_cd ?? 0) - 9)
    if (!b.my_pit) { b.pit_n = 0; b.pit_who = [] }
    if (b.key === 'jailer') b.tenure_pct = Math.min(30, (b.tenure_pct ?? 0) + 3)   // 📖 стаж растёт
    if ((b.adds_hp ?? 0) > 0) { b.adds_hp = Math.max(0, (b.adds_hp ?? 0) - dmg); b.adds_pct = Math.round(100 * (b.adds_hp ?? 0) / Math.max(1, (b.max_hp ?? 1) * 0.1)) }
    // касты по порогам HP (зеркалит boss.script; у ката roar → pit «В острог!»)
    const casts: string[] = []
    const fire = (id: string, pct: number, fn: () => void) => { if (b.hp_pct! <= pct && !_fired.has(id)) { _fired.add(id); fn(); casts.push(id) } }
    fire('ward', 84, () => { b.ward_left = 45 })
    fire('summon', 64, () => { b.adds_hp = Math.round((b.max_hp ?? 1) * 0.1); b.adds_pct = 100 })
    if (b.key === 'jailer') fire('pit', 46, () => { b.my_pit = 10; b.my_cd = 10; b.pit_n = 3; b.pit_who = ['Гриша Кабан', 'Авдотья', 'Ты'] })
    else fire('roar', 46, () => { b.stun_left = 45 })
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
  const [cd, setCd] = useState(0)              // мой локальный кулдаун/оглушение/острог
  const [stunned, setStunned] = useState(false)
  const [pitted, setPitted] = useState(false)  // 🔒 я в остроге (личный лок)
  const [floats, setFloats] = useState<Float[]>([])
  const [toast, setToast] = useState<string>('')
  const [flaskSel, setFlaskSel] = useState<string[]>([])
  // диапазон хода босса к краям — от ширины экрана (босс реально доходит до бортов)
  const [paceRange] = useState(() => Math.round(Math.min(window.innerWidth, 640) * 0.3))
  const sprite = st?.sprite || victory?.sprite || ''
  const emoji = st?.emoji || victory?.emoji || '😈'
  const boss = useBossDirector(paceRange, bossCfg(sprite).combat)   // «характер» боя из реестра
  const floatId = useRef(0)
  const termRef = useRef(false)        // достигли финала (победа/уход) → стоп-поллинг

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
    const i = setInterval(() => setCd((x) => { const n = Math.max(0, x - 1); if (n === 0) { setStunned(false); setPitted(false) } return n }), 1000)
    return () => clearInterval(i)
  }, [cd])

  // синхронизуем мой кулдаун/острог с сервером при апдейте состояния
  useEffect(() => {
    if (st?.status === 'active' && (st.my_cd ?? 0) > 0) {
      setCd(st.my_cd!); setStunned(!!st.my_stunned); setPitted((st.my_pit ?? 0) > 0)
    }
  }, [st?.my_cd, st?.my_stunned, st?.my_pit, st?.status])

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

  // АДМИН: тихо поднять Орду орков (без анонсов/пушей) — обкатка карты /world.
  async function summonOrc() {
    if (busy) return
    setBusy(true); haptic('medium')
    try {
      const r = await raidApi<{ ok: boolean; error?: string }>('invasion/seed', {})
      if (r.ok) { setToast('🪓 Орда поднята тихо — открой «Карту мира»!'); hapticNotify('success') }
      else { setToast(r.error === 'busy' ? 'Орда/босс уже идёт' : 'Не вышло'); hapticNotify('warning') }
      setTimeout(() => setToast(''), 2800)
    } catch { hapticNotify('warning') }
    finally { setBusy(false) }
  }

  async function hit() {
    if (busy || cd > 0 || boss.dead) return
    setBusy(true); haptic('rigid')
    try {
      const r = await raidApi<HitResp>('raid/hit', st?.flask?.drunk == null && flaskSel.length ? { flask: flaskSel } : {})
      if (r.dead && r.victory) {
        termRef.current = true; boss.kill(); thud(true); hapticNotify('success')
        setTimeout(() => { setVictory(r.victory!); onGold?.() }, 1100)
        return
      }
      if (r.hit) {
        boss.hit(!!r.crit); thud(!!r.crit)   // крит → большой отлёт (whacked, если есть у босса)
        if (r.dmg) pushFloat(`${r.crit ? '💥' : ''}−${r.dmg}`, !!r.crit)
        if (r.toast) { setToast(r.toast); setTimeout(() => setToast(''), 1400) }
        if (r.second_wind) hapticNotify('warning')   // у ката = острог топ-урона, не общий стан
        if (r.raid) {
          setSt(r.raid)
          const rc = r.raid
          if ((rc.my_cd ?? 0) > 0) { setCd(rc.my_cd!); setStunned(!!rc.my_stunned); setPitted((rc.my_pit ?? 0) > 0) }
        }
      } else if (r.wait) {                 // рано (оглушение/острог/кулдаун) — мягко
        setCd(r.wait); setStunned(!!r.stunned); setPitted(((r.raid?.my_pit) ?? 0) > 0); if (r.raid) setSt(r.raid)
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
          {sprite ? <BossSprite sprite={sprite} anim={bossCfg(sprite).deadAnim ?? 'death'} playId={1} loop frameStart={bossCfg(sprite).dead.start} frameCount={bossCfg(sprite).dead.count} durSec={0.95} width={Math.min(Math.round(window.innerWidth * 1.5), 560)} /> : <div className="raid-emo">{emoji}</div>}
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
              <button className="raid-summon-b" disabled={busy} onClick={summonOrc}
                style={{ gridColumn: '1 / -1', borderColor: '#6ea83a' }}>
                <span className="raid-summon-emo">🪓</span>
                <span className="raid-summon-nm">Орда орков — тихо (тест карты)</span>
              </button>
            </div>
            <p className="raid-summon-sub" style={{ marginTop: 6, opacity: .8 }}>
              🪓 тихий призыв: без анонсов и пушей, только тебе. Подними → открой «Карту мира».</p>
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
      st={st} cd={cd} stunned={stunned} pitted={pitted} busy={busy} floats={floats} toast={toast}
      boss={boss} onHit={hit} onClose={() => { haptic('light'); onClose() }} sprite={sprite} emoji={emoji}
      flaskSel={flaskSel} onFlask={(k) => setFlaskSel((cur) => cur.includes(k) ? cur.filter((x) => x !== k) : cur.length < 2 ? [...cur, k] : cur)}
    />
  )
}

// Речевое облако у рта босса на сборе: печатает ОДНУ реплику (управляется GatherView,
// который синхронит рот-анимацию с печатью). Скорость печати — CHAR_MS.
const LORE_CHAR_MS = 33
function LoreBubble({ text }: { text: string }) {
  const [n, setN] = useState(1)
  useEffect(() => {
    setN(1)
    const t = setInterval(() => setN((x) => (x >= text.length ? x : x + 1)), LORE_CHAR_MS)
    return () => clearInterval(t)
  }, [text])
  return (
    <div className="raid-lore">
      <span className="raid-lore-tx">{text.slice(0, n)}{n < text.length && <span className="raid-lore-cur">▌</span>}</span>
      <span className="raid-lore-tail" aria-hidden />
    </div>
  )
}

// ── Экран сбора ──────────────────────────────────────────────────────────────
function GatherView({ st, busy, onJoin, onClose, sprite, emoji }: {
  st: RaidState; busy: boolean; onJoin: () => void; onClose: () => void; sprite: string; emoji: string
}) {
  const left = useTicker(st.gather_left)
  const cfg = bossCfg(sprite)
  const lore = st.lore ?? []
  const sayAnim = cfg.gatherAnims?.[0] ?? cfg.gather        // «говорит» (рот двигается)
  const waitList = cfg.gatherAnims?.slice(1) ?? []          // паузы: переминается/усмехается/зыркает
  const [line, setLine] = useState(0)                       // текущая реплика лора
  const [speaking, setSpeaking] = useState(true)
  const [waitAnim, setWaitAnim] = useState(waitList[0] ?? cfg.gather)
  // синхрон: пока реплика печатается+читается — «говорит»; потом пауза с анимацией
  // ожидания; затем следующая реплика. Рот двигается ровно когда идёт речь.
  useEffect(() => {
    if (!lore.length || !cfg.gatherAnims) return
    const text = lore[line] ?? ''
    setSpeaking(true)
    const sayMs = 300 + text.length * LORE_CHAR_MS + 2400   // печать + время дочитать
    const gapMs = 2600                                      // пауза-переминание перед след. репликой
    const t1 = setTimeout(() => {
      setSpeaking(false)
      if (waitList.length) setWaitAnim(waitList[Math.floor(Math.random() * waitList.length)])
    }, sayMs)
    const t2 = setTimeout(() => setLine((x) => (x + 1) % lore.length), sayMs + gapMs)
    return () => { clearTimeout(t1); clearTimeout(t2) }
    // ВАЖНО: зависим от ДЛИНЫ лора, а не от массива st.lore — опрос сервера каждые 3с
    // отдаёт новый массив (та же длина), и завязка на ссылку сбрасывала бы таймер
    // смены реплики (t2 ~5–9с) раньше срабатывания → босс залипал и «молчал».
  }, [line, lore.length])   // eslint-disable-line react-hooks/exhaustive-deps
  const gAnim = (lore.length && cfg.gatherAnims) ? (speaking ? sayAnim : waitAnim) : cfg.gather
  return (
    <div className="raid-root">
      <div className="raid-vign" />
      <button className="raid-x" onClick={onClose}>✕</button>
      <div className="raid-gather">
        <div className={`raid-stage gather big${cfg.gatherCrop ? ' slimebox' : ''}`}>
          {sprite && lore.length > 0 && <LoreBubble key={line} text={lore[line]} />}
          {sprite ? <BossSprite sprite={sprite} anim={gAnim} width={Math.min(Math.round(window.innerWidth * cfg.gatherW), cfg.gatherCap)} /> : <div className="raid-emo">{emoji}</div>}
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

// Реплика босса — субтитр с эффектом печати (появляется на входе, кастах, смерти).
function BossBark({ text, name }: { text: string; name: string }) {
  const [n, setN] = useState(1)
  useEffect(() => {
    setN(1)
    const t = setInterval(() => setN((x) => (x >= text.length ? x : x + 1)), 34)
    return () => clearInterval(t)
  }, [text])
  const done = n >= text.length
  return (
    <div className="raid-bark">
      <span className="raid-bark-nm">{name.split(' ')[0]}:</span>
      <span className="raid-bark-tx">«{text.slice(0, n)}{done ? '»' : <span className="raid-bark-cur">▌</span>}</span>
    </div>
  )
}

// ── Экран битвы ──────────────────────────────────────────────────────────────
function BattleView({ st, cd, stunned, pitted, busy, floats, toast, boss, onHit, onClose, sprite, emoji, flaskSel, onFlask }: {
  st: RaidState; cd: number; stunned: boolean; pitted: boolean; busy: boolean; floats: Float[]; toast: string
  boss: ReturnType<typeof useBossDirector>; onHit: () => void; onClose: () => void; sprite: string; emoji: string
  flaskSel: string[]; onFlask: (k: string) => void
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
  const attacking = ['cleave', 'smash', 'fire', 'stab', 'punch'].includes(boss.anim)  // приём → тряхнём сцену
  const firing = boss.anim === 'fire' && bossCfg(sprite).proj   // выдох огня → вспышка (только у боссов со снарядом)
  // ИНТРО: вход босса (демон — transform слизень→демон, Тюремщик — «говорит»), потом
  // патруль. Одношот-вход снимает intro по onRest; зацикленный (talking) — по таймеру.
  const [intro, setIntro] = useState(true)
  useEffect(() => {
    if (!intro) return
    const t = setTimeout(() => setIntro(false), bossCfg(sprite).enterMs)
    return () => clearTimeout(t)
  }, [intro, sprite])
  // кольцо-удар: щёлкает на каждый take_hit (playId меняется при ударе)
  const [impact, setImpact] = useState(0)
  useEffect(() => { if (!intro && boss.anim === 'hit') setImpact((x) => x + 1) }, [boss.playId, boss.anim, intro])
  // ФАЕРБОЛ: на выдох огня вылетает снаряд из пасти и летит в сторону струи (огонь
  // в спрайте идёт ПРОТИВ facing), потом взрыв. Дальность — чтобы остаться в кадре.
  const [proj, setProj] = useState<{ id: number; dir: number; x0: number } | null>(null)
  useEffect(() => {
    if (!intro && boss.anim === 'fire' && bossCfg(sprite).proj) {
      const dir = -boss.facing
      setProj({ id: Date.now(), dir, x0: boss.pos + dir * 38 })
    }
  }, [boss.playId, boss.anim, intro, boss.facing, boss.pos, sprite])
  // КАСТЫ: ловим МОМЕНТ появления каждого заклинания (своё/чужое — через поллинг) →
  // босс воздевает руки (анимация cast) + драматичный баннер. Знаем КОНКРЕТНО какое.
  const wardOn = (st.ward_left ?? 0) > 0, curseOn = (st.curse_left ?? 0) > 0
  const addsOn = (st.adds_hp ?? 0) > 0, stunOn = (st.stun_left ?? 0) > 0
  const pitOn = (st.pit_n ?? 0) > 0            // 🔒 кто-то в остроге
  const prevSpell = useRef({ ward: wardOn, curse: curseOn, adds: addsOn, stun: stunOn, pit: pitOn })
  const [castBanner, setCastBanner] = useState<{ id: number; k: string; t: string } | null>(null)
  // РЕПЛИКИ-СУБТИТРЫ босса (barks): вход, касты, смерть. Пусто у боссов без barks.
  const [bark, setBark] = useState<{ id: number; text: string } | null>(null)
  const sayBark = (ev: string) => {
    const line = st.barks?.[ev]
    if (line) setBark({ id: Date.now(), text: line })
  }
  useEffect(() => {
    const p = prevSpell.current
    prevSpell.current = { ward: wardOn, curse: curseOn, adds: addsOn, stun: stunOn, pit: pitOn }
    if (intro || boss.dead) return
    const pitTxt = '🔒 В ОСТРОГ' + (st.pit_who?.length ? ': ' + st.pit_who.join(', ') : '!')
    const fired = (wardOn && !p.ward) ? { k: 'ward', t: '🛡 ЩИТ ВОЗДВИГНУТ' }
      : (curseOn && !p.curse) ? { k: 'curse', t: '💀 ПРОКЛЯТЬЕ' }
      : (addsOn && !p.adds) ? { k: 'adds', t: '👹 ПРИЗЫВ БЕСОВ' }
      : (pitOn && !p.pit) ? { k: 'pit', t: pitTxt }
      : (stunOn && !p.stun) ? { k: 'roar', t: '🗣 ОГЛУШАЮЩИЙ РЁВ' } : null
    if (fired) {
      // призыв стражи — подрыв (jbomb); острог — хватает и слэмит (smash); прочее — вскинул руки
      if (fired.k === 'adds' && bossCfg(sprite).defs.jbomb) boss.play('jbomb')
      else if (fired.k === 'pit' && bossCfg(sprite).defs.smash) boss.play('smash')
      else boss.cast()
      setCastBanner({ id: Date.now(), ...fired })
      sayBark(fired.k === 'adds' ? 'summon' : fired.k)     // босс приговаривает
      const tm = setTimeout(() => setCastBanner(null), 1700)
      return () => clearTimeout(tm)
    }
  }, [wardOn, curseOn, addsOn, stunOn, pitOn, intro, boss, sprite])   // eslint-disable-line react-hooks/exhaustive-deps
  // реплика на входе (пока играет анимация появления) и на смерти
  useEffect(() => { if (intro) sayBark('intro') }, [])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (boss.dead) sayBark('death') }, [boss.dead])   // eslint-disable-line react-hooks/exhaustive-deps
  // автоскрытие субтитра (время ∝ длине реплики)
  useEffect(() => {
    if (!bark) return
    const t = setTimeout(() => setBark(null), Math.min(6000, 1900 + bark.text.length * 45))
    return () => clearTimeout(t)
  }, [bark])
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
  if (pitOn) fx.push({ k: 'pit', icon: '🔒', label: 'В остроге', sub: `${st.pit_n}` })
  if (addsOn) fx.push({ k: 'adds', icon: '👹', label: 'Бесы', sub: `${st.adds_pct}%` })
  if (wardOn) fx.push({ k: 'ward', icon: '🛡', label: 'Щит', sub: `${fxT.ward}с` })
  if (curseOn) fx.push({ k: 'curse', icon: '💀', label: 'Проклятье', sub: `${fxT.curse}с` })
  if ((st.tenure_pct ?? 0) > 0) fx.push({ k: 'tenure', icon: '📖', label: 'Стаж', sub: `−${st.tenure_pct}%` })
  const adds = addsOn

  return (
    <div className={`raid-root battle ph${phase}`}>
      <div className="raid-vign" />
      <div className={`raid-fxflash${attacking ? ' on' : ''}${firing ? ' fire' : ''}`} aria-hidden />
      {!intro && wardOn && <div className="raid-aura ward" aria-hidden />}
      {!intro && curseOn && <div className="raid-aura curse" aria-hidden />}
      {pbanner && <div key={`pb${pbanner.id}`} className={`raid-pbanner${pbanner.rage ? ' rage' : ''}`}>{pbanner.text}</div>}
      {castBanner && <div key={`cb${castBanner.id}`} className={`raid-castbanner ${castBanner.k}`}>{castBanner.t}</div>}
      {bark && <BossBark key={`bk${bark.id}`} text={bark.text} name={st.name} />}
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
                <BossSprite sprite={sprite} anim={bossCfg(sprite).enter} playId={1} width={bw} onRest={() => setIntro(false)} />
                <div className="raid-shadow big" />
              </div>
            </div>
          ) : (
            <>
              <div className="raid-mover" style={{ transform: `translateX(${boss.pos}px)`, transition: `transform ${boss.moveMs}ms ease-in-out` }}>
                <div className="raid-facer" style={{ transform: `scaleX(${boss.facing})` }}>
                  {/* пока ward активен — держит глухую защиту (dpose); НО реакцию удара
                      (whacked-звёздочки / hit) пропускаем ПОВЕРХ щита и без затемнения,
                      иначе оглушение-в-звёздочки почти не видно (ward висит долго). */}
                  {wardOn && bossCfg(sprite).defs.dpose && boss.anim !== 'whacked' && boss.anim !== 'hit'
                    ? <BossSprite sprite={sprite} anim="dpose" playId={-1} width={bw} dim />
                    : <BossSprite sprite={sprite} anim={boss.anim} playId={boss.playId} width={bw} onRest={boss.onRest} dim={wardOn && boss.anim !== 'whacked' && boss.anim !== 'hit'} />}
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
        {st.flask && st.flask.drunk == null && st.flask.options.length > 0 && (
          <div className="raid-flask">
            <span className="raid-flask-h">🍺 Хлебнуть на бой (до 2):</span>
            {st.flask.options.map((f) => (
              <button key={f.key} className={`raid-flask-chip${flaskSel.includes(f.key) ? ' on' : ''}`}
                onClick={() => { haptic('light'); onFlask(f.key) }}>
                {f.emoji} {f.label} <em>×{f.qty}</em>
              </button>
            ))}
          </div>
        )}
        {st.flask && (st.flask.drunk?.length ?? 0) > 0 && (
          <div className="raid-flask drunk">🍺 Выпито на бой: {st.flask.drunk!.length} порц. — действует до конца битвы</div>
        )}
        {cd > 0 ? (
          <button className={`btn raid-hit wait${pitted ? ' pit' : ''}`} disabled>
            {pitted ? `🔒 Ты в остроге — ${secsLabel(cd)}` : stunned ? `😵 Оглушён — ${secsLabel(cd)}` : `⏳ Передышка — ${secsLabel(cd)}`}
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
