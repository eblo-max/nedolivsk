import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

// Спрайт-листы рейд-босса (из FULL-набора). Кадр 288×160. Два «атласа» ради памяти
// (полный 32×12 ≈70МБ тяжёл для Android):
//   demon  — боевой демон, лист 22×8  (<sprite>.png): idle/walk/cleave/smash/fire/cast/hit/death
//   intro  — слизень + превращение, лист 32×4 (<sprite>_intro.png): slime_idle/move/hit + transform
// Анимируем background-position-x шагами steps(N); @keyframes boss-play + --startx/--endx.
const FW = 288, FH = 160
const ATLAS = {
  demon: { suffix: '',       cols: 22, rows: 8 },
  intro: { suffix: '_intro', cols: 32, rows: 4 },
} as const

export type BossAnim =
  | 'idle' | 'walk' | 'cleave' | 'smash' | 'fire' | 'cast' | 'hit' | 'death'
  | 'slime_idle' | 'slime_move' | 'slime_hit' | 'transform'
type Atlas = keyof typeof ATLAS
const DEF: Record<BossAnim, { atlas: Atlas; row: number; frames: number; dur: number; loop: boolean }> = {
  // боевой демон (лист demon)
  idle:       { atlas: 'demon', row: 0, frames: 6,  dur: 0.95, loop: true },
  walk:       { atlas: 'demon', row: 1, frames: 12, dur: 1.0,  loop: true },
  cleave:     { atlas: 'demon', row: 2, frames: 15, dur: 0.85, loop: false },
  smash:      { atlas: 'demon', row: 3, frames: 18, dur: 1.05, loop: false },
  fire:       { atlas: 'demon', row: 4, frames: 21, dur: 1.30, loop: false },  // 🔥 выдох пламени
  cast:       { atlas: 'demon', row: 5, frames: 6,  dur: 0.70, loop: false },  // каст заклинания
  hit:        { atlas: 'demon', row: 6, frames: 5,  dur: 0.40, loop: false },
  death:      { atlas: 'demon', row: 7, frames: 22, dur: 1.70, loop: false },
  // слизень + превращение (лист intro)
  slime_idle: { atlas: 'intro', row: 0, frames: 6,  dur: 0.95, loop: true },
  slime_move: { atlas: 'intro', row: 1, frames: 8,  dur: 0.90, loop: true },
  slime_hit:  { atlas: 'intro', row: 2, frames: 6,  dur: 0.45, loop: false },
  transform:  { atlas: 'intro', row: 3, frames: 32, dur: 2.40, loop: false },  // слизень → демон
}

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
  const h = Math.round(width * FH / FW)
  const a = DEF[anim]
  const at = ATLAS[a.atlas]
  const looping = a.loop || loop
  const count = Math.max(1, frameCount ?? a.frames)
  const dur = durSec ?? (a.dur * count / a.frames)   // темп кадров (или override)
  const src = `${import.meta.env.BASE_URL}boss/${sprite}${at.suffix}.png`
  const style: CSSProperties = {
    width, height: h,
    backgroundImage: `url("${src}")`,
    backgroundRepeat: 'no-repeat',
    backgroundSize: `${at.cols * width}px ${at.rows * h}px`,
    backgroundPositionY: `${-a.row * h}px`,
    imageRendering: 'pixelated',
    animationName: 'boss-play',
    animationDuration: `${dur}s`,
    animationTimingFunction: `steps(${count})`,
    animationIterationCount: looping ? 'infinite' : 1,
    animationFillMode: looping ? 'none' : 'forwards',
    ['--startx' as string]: `${-frameStart * width}px`,
    ['--endx' as string]: `${-(frameStart + count) * width}px`,
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
export function useBossDirector(range = 0) {
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

  // Маршрут патруля: край → ЦЕНТР (там серия боевых взмахов) → другой край → ЦЕНТР
  // (бой) → … Босс реально ОСТАНАВЛИВАЕТСЯ в центре, рубит, потом идёт дальше.
  // beat: {move:x} — дойти до x; {act:'cleave'} — взмах; {act:'idle',dur} — стойка.
  type Beat = { move: number } | { act: BossAnim; dur?: number }
  const route = useMemo<Beat[] | null>(() => {
    if (range <= 4) return null
    // В ЦЕНТРЕ — связка боя: демон ХАРКАЕТ ОГНЁМ, потом тесак/смэш. Огонь — каждый
    // заход (по лору «харкает огнём»), добивка чередуется (cleave ↔ smash).
    const fire = (finisher: BossAnim): Beat[] => [
      { act: 'fire' }, { act: 'idle', dur: 240 }, { act: finisher }, { act: 'idle', dur: 240 },
    ]
    return [
      { move: -range }, { act: 'idle', dur: 480 },   // дошёл до левого края, замер
      { move: 0 }, ...fire('cleave'),                // к центру → ОГОНЬ + тесак
      { move: range }, { act: 'idle', dur: 480 },    // до правого края
      { move: 0 }, ...fire('smash'),                 // к центру → ОГОНЬ + смэш
    ]
  }, [range])

  // следующий «такт» маршрута (шаг → таймер; одношот-приём → onRest; стойка → таймер)
  const next = useCallback(() => {
    if (deadRef.current) return
    clearTimeout(loopT.current)
    if (!route) {                                   // без хода — просто огонь/взмах/стойка
      const r = Math.random()
      if (r < 0.35) set('fire'); else if (r < 0.65) set('cleave')
      else { set('idle'); loopT.current = setTimeout(next, 1100) }
      return
    }
    const beat = route[stepRef.current % route.length]
    stepRef.current += 1
    if ('move' in beat) {
      const target = beat.move
      setFacing(target >= posRef.current ? -1 : 1)  // ногами ПО ходу (не «мунвок»)
      const dist = Math.abs(target - posRef.current)
      const dur = Math.round(760 + dist * 5)
      setMoveMs(dur); posRef.current = target; setPos(target); set('walk')
      loopT.current = setTimeout(next, dur + 120)
    } else if (beat.act === 'idle') {
      set('idle'); loopT.current = setTimeout(next, beat.dur ?? 800)
    } else {
      set(beat.act)                                 // одношот-приём → onRest → следующий такт
    }
  }, [route])

  // конец одношота (cleave/fire/smash/cast/hit) → следующий такт
  const onRest = useCallback(() => { if (!deadRef.current) next() }, [next])

  useEffect(() => { next(); return () => clearTimeout(loopT.current) }, [next])

  const hit = useCallback(() => {
    if (deadRef.current) return
    clearTimeout(loopT.current); set('hit')        // дёрнётся; onRest вернёт в ритм
  }, [])
  const cast = useCallback(() => {
    if (deadRef.current) return
    clearTimeout(loopT.current); set('cast')       // воздел руки; onRest вернёт в ритм
  }, [])
  const kill = useCallback(() => {
    deadRef.current = true; clearTimeout(loopT.current); setDead(true); set('death')
  }, [])
  return { anim, playId, dead, pos, facing, moveMs, hit, cast, kill, onRest }
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
