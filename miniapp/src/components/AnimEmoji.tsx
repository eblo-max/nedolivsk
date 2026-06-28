import { useEffect, useRef, useState } from 'react'
import lottie from 'lottie-web/build/player/lottie_light'

// id мирового события → slug нативного анимированного эмодзи Telegram (public/event/<slug>.tgs)
const SLUG: Record<string, string> = {   // только реально выгруженные (остальные — фолбэк на эмодзи)
  clear: 'sun', goldrush: 'coin', rain: 'rain', frost: 'snow',
  drought: 'fire', plague: 'virus', fashion: 'fire', fire: 'fire',
}

/** Нативный анимированный эмодзи Telegram (TGS/Lottie, зациклен). Фолбэк — обычный эмодзи. */
export default function AnimEmoji({ id, fallback, size = 40 }: { id: string; fallback: string; size?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const [fail, setFail] = useState(false)
  const slug = SLUG[id]
  useEffect(() => {
    if (!slug || !ref.current) { setFail(true); return }
    let anim: ReturnType<typeof lottie.loadAnimation> | null = null
    let cancelled = false
    fetch(`${import.meta.env.BASE_URL}event/${slug}.tgs`)
      .then((r) => { if (!r.ok) throw new Error('no emoji'); return r.body!.pipeThrough(new DecompressionStream('gzip')) })
      .then((s) => new Response(s).json())
      .then((data) => { if (cancelled || !ref.current) return; anim = lottie.loadAnimation({ container: ref.current, renderer: 'svg', loop: true, autoplay: true, animationData: data }) })
      .catch(() => setFail(true))
    return () => { cancelled = true; anim?.destroy() }
  }, [slug])
  if (fail || !slug) return <span style={{ fontSize: Math.round(size * 0.82), lineHeight: 1 }}>{fallback}</span>
  return <div ref={ref} style={{ width: size, height: size, flex: 'none' }} aria-hidden="true" />
}
