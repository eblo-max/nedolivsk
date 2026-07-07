import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

// Реестр спрайт-боссов. У каждого свой лист(ы), размер кадра и раскладка анимаций.
// Лист <sprite>.png (+ опц. <sprite>_intro.png): строка = анимация, столбец = кадр.
// Два «атласа» ради памяти Android (один большой ≈70МБ роняет вкладку). Анимируем
// background-position-x шагами steps(N); @keyframes boss-play + --startx/--endx.
type AtlasCfg = { suffix: string; cols: number; rows: number }
// start — с какого кадра строки (для поз-одиночек, живущих в общей строке-строке поз)
type AnimCfg = { atlas: string; row: number; frames: number; dur: number; loop?: boolean; start?: number }
// Боевой «характер» босса для useBossDirector — из него строится маршрут патруля.
// Нет combat → демон: [cleave,smash] с опенером 'fire'. Богатый набор (Тюремщик):
type CombatCfg = {
  attacks: string[]                     // одиночные приёмы в центре
  opener?: string                       // перед приёмом (демон — огонь, Тюремщик — бросок кандалов)
  telegraph?: Record<string, string>    // приём → замах перед ним (smash→prep, stab→trans)
  combo?: string[]                      // мульти-аним спец-связка в центре (прыжок-обвал)
  charge?: { run: string; atk: string } // забег к центру + атака в движении (run + runatk)
  moveAtk?: string                      // ход-с-ударом на подходе (walk_attacking)
  taunts?: string[]                     // idle-варианты в стойке (gloat/bored/front)
  hitHeavy?: string                     // take-hit на КРИТ (большой отлёт whacked)
}
type SpriteCfg = {
  fw: number; fh: number                     // размер одного кадра (px)
  pixel: boolean                             // пиксель-арт (nearest) или гладкий даунскейл
  atlases: Record<string, AtlasCfg>
  defs: Record<string, AnimCfg>
  gather: string                             // анимация на экране сбора (луп, «приближается»)
  gatherAnims?: string[]                      // чередование анимаций ожидания на сборе (луп-ы); нет → один gather
  gatherW: number; gatherCap: number         // ширина спрайта на сборе (×innerWidth, кап px)
  gatherCrop: boolean                        // низ-кроп (для приземистых, как слизень); иначе фигура целиком
  enter: string                              // вход в бой, потом патруль
  enterMs: number                            // сколько длится вход (для зацикленных enter — по таймеру)
  deadAnim?: string                          // анимация «труп» на победе (по умолч. 'death')
  dead: { start: number; count: number }     // кадры трупа (start/count в строке deadAnim)
  proj?: boolean                             // летит ли снаряд на анимацию 'fire'
  combat?: CombatCfg                         // «характер» боя (нет → как демон: cleave/smash + fire)
}

// Единые ИМЕНА боевых анимаций у всех боссов (idle/walk/cleave/smash/fire/cast/hit/
// death) — тогда useBossDirector и RaidSheet работают с любым боссом без правок.
// Флейвор задаёт лист: у демона fire=выдох огня, у Тюремщика fire=бросок кандалов,
// cast=глухая защита. Интро/спец-анимации — свои у каждого.
const SPRITES: Record<string, SpriteCfg> = {
  demon_slime: {
    fw: 288, fh: 160, pixel: true,
    atlases: { demon: { suffix: '', cols: 22, rows: 8 }, intro: { suffix: '_intro', cols: 32, rows: 4 } },
    defs: {
      idle:   { atlas: 'demon', row: 0, frames: 6,  dur: 0.95, loop: true },
      walk:   { atlas: 'demon', row: 1, frames: 12, dur: 1.0,  loop: true },
      cleave: { atlas: 'demon', row: 2, frames: 15, dur: 0.85 },
      smash:  { atlas: 'demon', row: 3, frames: 18, dur: 1.05 },
      fire:   { atlas: 'demon', row: 4, frames: 21, dur: 1.30 },   // 🔥 выдох пламени
      cast:   { atlas: 'demon', row: 5, frames: 6,  dur: 0.70 },   // каст заклинания
      hit:    { atlas: 'demon', row: 6, frames: 5,  dur: 0.40 },
      death:  { atlas: 'demon', row: 7, frames: 22, dur: 1.70 },
      slime_idle: { atlas: 'intro', row: 0, frames: 6,  dur: 0.95, loop: true },
      slime_move: { atlas: 'intro', row: 1, frames: 8,  dur: 0.90, loop: true },
      slime_hit:  { atlas: 'intro', row: 2, frames: 6,  dur: 0.45 },
      transform:  { atlas: 'intro', row: 3, frames: 32, dur: 2.40 },   // слизень → демон
    },
    gather: 'slime_move', gatherW: 2.2, gatherCap: 860, gatherCrop: true,
    enter: 'transform', enterMs: 2600, dead: { start: 3, count: 6 }, proj: true,
  },
  // Батог Мясомял — тюремщик-палач. ВСЕ 34 анимации пака в деле, 3 атласа:
  //   main  (18×8, 300×200) — главный бой, чётко.  intro (12×14, 240×160) — стоячие
  //   экстра+позы.  jump (12×7, 240×160) — прыжок/полёт со своим bbox. Экстра/спецы —
  //   чуть меньшим разрешением (в движении незаметно, ради памяти Android).
  jailer: {
    fw: 300, fh: 200, pixel: false,
    atlases: {
      main:  { suffix: '',       cols: 18, rows: 8 },
      intro: { suffix: '_intro', cols: 12, rows: 14 },
      jump:  { suffix: '_jump',  cols: 12, rows: 7 },
    },
    defs: {
      // — main —
      idle:   { atlas: 'main', row: 0, frames: 12, dur: 1.15, loop: true },
      walk:   { atlas: 'main', row: 1, frames: 8,  dur: 0.95, loop: true },
      cleave: { atlas: 'main', row: 2, frames: 6,  dur: 0.70 },    // взмах дубиной
      smash:  { atlas: 'main', row: 3, frames: 18, dur: 1.15 },    // тяжёлый удар с руки
      fire:   { atlas: 'main', row: 4, frames: 10, dur: 0.95 },    // метнул связку кандалов
      cast:   { atlas: 'main', row: 5, frames: 6,  dur: 0.60 },    // вскинул защиту (ward)
      hit:    { atlas: 'main', row: 6, frames: 6,  dur: 0.40 },
      death:  { atlas: 'main', row: 7, frames: 7,  dur: 1.20 },
      // — intro/extra (стоячие) —
      talking: { atlas: 'intro', row: 0,  frames: 12, dur: 1.60, loop: true },  // орёт (вход/реплики)
      stab:    { atlas: 'intro', row: 1,  frames: 8,  dur: 0.65 },  // тычок дубиной
      punch:   { atlas: 'intro', row: 2,  frames: 8,  dur: 0.60 },  // джеб
      whacked: { atlas: 'intro', row: 3,  frames: 12, dur: 0.75 },  // большой отлёт (крит)
      gloat:   { atlas: 'intro', row: 4,  frames: 10, dur: 1.50, loop: true },  // злорадствует (тонт)
      bored:   { atlas: 'intro', row: 5,  frames: 10, dur: 1.80, loop: true },  // скучает в затишье (тонт)
      front:   { atlas: 'intro', row: 6,  frames: 10, dur: 1.60, loop: true },  // разворот к камере (тонт)
      walkatk: { atlas: 'intro', row: 7,  frames: 8,  dur: 0.95, loop: true },  // удар в движении
      run:     { atlas: 'intro', row: 8,  frames: 8,  dur: 0.70, loop: true },  // бег (забег/ярость)
      runatk:  { atlas: 'intro', row: 9,  frames: 8,  dur: 0.75 },  // наскок в беге
      climb:   { atlas: 'intro', row: 10, frames: 8,  dur: 1.30 },  // вылезает из ямы-острога (вход)
      prep:    { atlas: 'intro', row: 11, frames: 8,  dur: 0.55 },  // замах перед тяжёлым (телеграф)
      trans:   { atlas: 'intro', row: 12, frames: 4,  dur: 0.30 },  // подводка к тычку (телеграф)
      pose_f:  { atlas: 'intro', row: 13, frames: 1,  dur: 0.5, start: 0 },   // база-фронт (брейс перед прыжком)
      pose_s:  { atlas: 'intro', row: 13, frames: 1,  dur: 0.7, start: 1 },   // база-профиль (грозная замерка)
      dpose:   { atlas: 'intro', row: 13, frames: 1,  dur: 0.5, start: 2 },   // держит щит (пока ward)
      corpse:  { atlas: 'intro', row: 13, frames: 1,  dur: 0.5, start: 3, loop: true },  // труп (победа)
      // — jump (прыжок-обвал + подрыв) —
      jstart:  { atlas: 'jump', row: 0, frames: 6,  dur: 0.45 },    // присед-разбег
      jcycle:  { atlas: 'jump', row: 1, frames: 12, dur: 0.60 },    // в полёте
      jslam:   { atlas: 'jump', row: 2, frames: 10, dur: 0.70 },    // обрушился
      jend:    { atlas: 'jump', row: 3, frames: 7,  dur: 0.55 },    // отходит от удара
      jbomb:   { atlas: 'jump', row: 4, frames: 12, dur: 1.00 },    // подрыв — на призыв стражи (summon)
      falling: { atlas: 'jump', row: 5, frames: 10, dur: 0.55 },    // падение перед обвалом
      apex:    { atlas: 'jump', row: 6, frames: 1,  dur: 0.18, start: 0 },  // зависание в верхней точке
      ascend:  { atlas: 'jump', row: 6, frames: 1,  dur: 0.18, start: 1 },  // взмыл перед обвалом
    },
    gather: 'talking', gatherW: 1.32, gatherCap: 540, gatherCrop: false,
    // на сборе чередует: рассказывает (talking ×вес), переминается, усмехается, зыркает в толпу
    gatherAnims: ['talking', 'talking', 'talking', 'bored', 'gloat', 'front'],
    enter: 'climb', enterMs: 1600, deadAnim: 'corpse', dead: { start: 3, count: 1 }, proj: false,
    combat: {
      attacks: ['cleave', 'smash', 'stab', 'punch'], opener: 'fire',
      telegraph: { smash: 'prep', stab: 'trans' },              // замах перед тяжёлым/тычком
      combo: ['pose_f', 'jstart', 'jcycle', 'apex', 'falling', 'ascend', 'jslam', 'jend'],  // прыжок-обвал
      charge: { run: 'run', atk: 'runatk' },                    // забег + наскок
      moveAtk: 'walkatk', taunts: ['gloat', 'bored', 'front', 'pose_s'], hitHeavy: 'whacked',
    },
  },
}

export type BossAnim = string
export function bossCfg(sprite: string): SpriteCfg { return SPRITES[sprite] ?? SPRITES.demon_slime }

export default function BossSprite({
  sprite, anim, playId = 0, width = 300, onRest, dim, loop = false, frameStart = 0, frameCount, durSec,
}: {
  sprite: string
  anim: BossAnim
  playId?: number      // меняется → перезапуск одношотовой анимации (remount по key)
  width?: number
  onRest?: () => void  // конец одношота (hit/cleave) → родитель вернёт в idle
  dim?: boolean        // притушить (пауза/щит)
  loop?: boolean       // принудительно зациклить (напр. смерть на экране победы)
  frameStart?: number  // с какого кадра строки играть (по умолч. 0)
  frameCount?: number  // сколько кадров (по умолч. вся строка) — напр. петля без хвоста
  durSec?: number      // переопределить длительность (для медленной драматичной петли)
}) {
  const cfg = bossCfg(sprite)
  const h = Math.round(width * cfg.fh / cfg.fw)
  const a = cfg.defs[anim] ?? cfg.defs.idle
  const at = cfg.atlases[a.atlas]
  const looping = a.loop || loop
  const count = Math.max(1, frameCount ?? a.frames)
  const fstart = frameStart || a.start || 0          // база строки (позы-одиночки — свой start)
  const dur = durSec ?? (a.dur * count / a.frames)   // темп кадров (или override)
  const src = `${import.meta.env.BASE_URL}boss/${sprite}${at.suffix}.png`
  const style: CSSProperties = {
    width, height: h,
    backgroundImage: `url("${src}")`,
    backgroundRepeat: 'no-repeat',
    backgroundSize: `${at.cols * width}px ${at.rows * h}px`,
    backgroundPositionY: `${-a.row * h}px`,
    imageRendering: cfg.pixel ? 'pixelated' : 'auto',
    animationName: 'boss-play',
    animationDuration: `${dur}s`,
    animationTimingFunction: `steps(${count})`,
    animationIterationCount: looping ? 'infinite' : 1,
    animationFillMode: looping ? 'none' : 'forwards',
    ['--startx' as string]: `${-fstart * width}px`,
    ['--endx' as string]: `${-(fstart + count) * width}px`,
    filter: dim ? 'grayscale(.55) brightness(.65)' : undefined,
  } as CSSProperties

  return (
    <div
      key={`${anim}-${playId}`}
      className="boss-sprite"
      style={style}
      onAnimationEnd={() => { if (!looping) onRest?.() }}
    />
  )
}

// Боевой «режиссёр»: пока босс жив, он НЕПРЕРЫВНО играет — idle/walk/cleave по
// случайному ритму (живой, грозный), а на удар игрока рвётся в take_hit и возвращается
// в ритм. Смерть (kill) останавливает всё. Одношоты (cleave/hit) сменяются по
// onAnimationEnd (точно по кадрам), петли (idle/walk) — по таймеру.
const DEMON_ATTACKS = ['cleave', 'smash']   // дефолт-пул (демон), стабильная ссылка

export function useBossDirector(range = 0, combat?: CombatCfg) {
  const [anim, setAnim] = useState<BossAnim>('idle')
  const [playId, bump] = useState(0)
  const [dead, setDead] = useState(false)
  const [pos, setPos] = useState(0)        // горизонт. смещение спрайта, px
  const [facing, setFacing] = useState(1)  // 1 / -1 (зеркало по ходу)
  const [moveMs, setMoveMs] = useState(0)  // длительность текущего перехода
  const deadRef = useRef(false)
  const posRef = useRef(0)
  const stepRef = useRef(0)                  // индекс по маршруту
  const loopT = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const set = (a: BossAnim) => { setAnim(a); bump((x) => x + 1) }

  // «Характер» боя. Нет combat → как демон: [cleave,smash] с опенером 'fire'.
  const attacks = combat?.attacks ?? DEMON_ATTACKS
  const opener = combat ? combat.opener : 'fire'
  const taunts = combat?.taunts
  const telegraph = combat?.telegraph
  const combo = combat?.combo
  const charge = combat?.charge
  const moveAtk = combat?.moveAtk
  const hitHeavy = combat?.hitHeavy
  const pickAtk = () => attacks[Math.floor(Math.random() * attacks.length)]
  const pickIdle = () => (taunts && Math.random() < 0.34)
    ? taunts[Math.floor(Math.random() * taunts.length)] : 'idle'

  // Маршрут патруля: край → ЦЕНТР (связка) → другой край → … На заход — свой приём
  // из пула (перебор). Перед тяжёлым — замах-телеграф; изредка забег-наскок и
  // спец-связка (прыжок-обвал) в центре. beat: {move[,atk,run]} / {act[,dur]}.
  type Beat = { move: number; atk?: boolean; run?: boolean } | { act: BossAnim; dur?: number }
  const route = useMemo<Beat[] | null>(() => {
    if (range <= 4) return null
    const beats: Beat[] = []
    attacks.forEach((a, i) => {
      const tel = telegraph?.[a]
      beats.push({ move: i % 2 === 0 ? -range : range }, { act: 'idle', dur: 460 },
        { move: 0, atk: i === 1 && !!moveAtk })                       // один заход — ход-с-ударом
      if (tel) beats.push({ act: tel }, { act: a }, { act: 'idle', dur: 240 })          // замах → приём
      else if (opener) beats.push({ act: opener }, { act: 'idle', dur: 220 }, { act: a }, { act: 'idle', dur: 240 })
      else beats.push({ act: a }, { act: 'idle', dur: 300 })
    })
    if (charge) beats.push({ move: -range }, { act: 'idle', dur: 300 }, { move: 0, run: true },
      { act: charge.atk }, { act: 'idle', dur: 240 })                 // забег + наскок
    if (combo) beats.push({ move: 0 }, ...combo.map((c) => ({ act: c })), { act: 'idle', dur: 300 })  // прыжок-обвал
    return beats
  }, [range, attacks, opener, telegraph, combo, charge, moveAtk])

  // следующий «такт» маршрута (шаг → таймер; одношот-приём → onRest; стойка → таймер)
  const next = useCallback(() => {
    if (deadRef.current) return
    clearTimeout(loopT.current)
    if (!route) {                                   // тесный экран без хода — приём/опенер/стойка
      const r = Math.random()
      if (opener && r < 0.3) set(opener); else if (r < 0.68) set(pickAtk())
      else { set(pickIdle()); loopT.current = setTimeout(next, 1100) }
      return
    }
    const beat = route[stepRef.current % route.length]
    stepRef.current += 1
    if ('move' in beat) {
      const target = beat.move
      setFacing(target >= posRef.current ? -1 : 1)  // ногами ПО ходу (не «мунвок»)
      const dist = Math.abs(target - posRef.current)
      const dur = Math.round((beat.run && charge ? 520 : 760) + dist * (beat.run ? 3 : 5))
      const moveAnim = beat.run && charge ? charge.run : (beat.atk && moveAtk ? moveAtk : 'walk')
      setMoveMs(dur); posRef.current = target; setPos(target); set(moveAnim)  // бег/ход-с-ударом/ходьба
      loopT.current = setTimeout(next, dur + 120)
    } else if (beat.act === 'idle') {
      set(pickIdle()); loopT.current = setTimeout(next, beat.dur ?? 800)      // изредка тонт (gloat/bored/…)
    } else {
      set(beat.act)                                 // одношот-приём/связка → onRest → следующий такт
    }
  }, [route, opener, charge, moveAtk])   // eslint-disable-line react-hooks/exhaustive-deps

  // конец одношота (cleave/fire/smash/cast/hit) → следующий такт
  const onRest = useCallback(() => { if (!deadRef.current) next() }, [next])

  useEffect(() => { next(); return () => clearTimeout(loopT.current) }, [next])

  const hit = useCallback((heavy = false) => {
    if (deadRef.current) return
    clearTimeout(loopT.current)
    // крит → всегда «в звёздочки» (whacked); обычный удар — часто тоже оглушаем в звёзды,
    // иначе редкая, но эффектная поза почти не показывалась. onRest вернёт в ритм.
    const stars = hitHeavy && (heavy || Math.random() < 0.5)
    set(stars ? hitHeavy : 'hit')
  }, [hitHeavy])
  const cast = useCallback(() => {
    if (deadRef.current) return
    clearTimeout(loopT.current); set('cast')       // воздел руки; onRest вернёт в ритм
  }, [])
  const play = useCallback((a: BossAnim) => {
    if (deadRef.current) return
    clearTimeout(loopT.current); set(a)            // произвольный одношот-каст; onRest вернёт в ритм
  }, [])
  const kill = useCallback(() => {
    deadRef.current = true; clearTimeout(loopT.current); setDead(true); set('death')
  }, [])
  return { anim, playId, dead, pos, facing, moveMs, hit, cast, play, kill, onRest }
}

// Фаербол выдоха: летит в сторону dir от стартовой точки к краю арены, потом взрыв.
// Лист demon_slime_proj.png — 11×2, кадр 32×32: строка 0 idle (3 кадра, полёт),
// строка 1 explosion (10 кадров). Переиспользует @keyframes boss-play (bg-pos-x).
const PROJ_COLS = 11
export function FireProjectile({ x0, fly, y, dir, size = 72, onDone }: {
  x0: number       // старт по X (px от центра арены)
  fly: number      // дальность полёта (px, всегда положит.)
  y: number        // вертикаль (px от верха сцены)
  dir: number      // 1 / -1 — куда летит (и зеркало спрайта)
  size?: number
  onDone: () => void
}) {
  const [phase, setPhase] = useState<'fly' | 'boom'>('fly')
  const [moved, setMoved] = useState(false)
  const FLY = 560
  useEffect(() => {
    const r = requestAnimationFrame(() => setMoved(true))
    const t1 = setTimeout(() => setPhase('boom'), FLY)
    const t2 = setTimeout(onDone, FLY + 460)        // взрыв ~10 кадров
    return () => { cancelAnimationFrame(r); clearTimeout(t1); clearTimeout(t2) }
  }, [onDone])
  const src = `${import.meta.env.BASE_URL}boss/demon_slime_proj.png`
  const x = phase === 'boom' ? x0 + dir * fly : (moved ? x0 + dir * fly : x0)
  const base: CSSProperties = {
    position: 'absolute', left: '50%', top: y, width: size, height: size, marginLeft: -size / 2,
    backgroundImage: `url("${src}")`, backgroundRepeat: 'no-repeat',
    backgroundSize: `${PROJ_COLS * size}px ${2 * size}px`, imageRendering: 'pixelated',
    pointerEvents: 'none', zIndex: 3, animationName: 'boss-play',
  }
  const style: CSSProperties = phase === 'fly' ? {
    ...base, backgroundPositionY: '0px',
    animationDuration: '.27s', animationTimingFunction: 'steps(3)', animationIterationCount: 'infinite',
    ['--startx' as string]: '0px', ['--endx' as string]: `${-3 * size}px`,
    transform: `translateX(${x}px) scaleX(${dir})`, transition: `transform ${FLY}ms linear`,
  } as CSSProperties : {
    ...base, backgroundPositionY: `${-size}px`,
    animationDuration: '.46s', animationTimingFunction: 'steps(10)', animationIterationCount: 1,
    animationFillMode: 'forwards', ['--startx' as string]: '0px', ['--endx' as string]: `${-10 * size}px`,
    transform: `translateX(${x}px)`,
  } as CSSProperties
  return <div className="boss-proj" style={style} />
}
