// общие иконки/форматтеры — переиспользуются Таверной и bottom-sheet панелями

export const fmt = (n: number) => (n >= 10000 ? `${(n / 1000).toFixed(1)}к` : `${n}`)

// иконки ресурсов: miniapp/public/res/<ключ>.png (золото/слиток — тоже иконки)
const RES_HAS = new Set([
  'gold', 'ingot', 'wood', 'grain', 'hops', 'stone', 'ore', 'clay',
  'honey', 'milk', 'berries', 'fish', 'game', 'herbs', 'salt', 'water',
  // крафт-компоненты (охота/горн): свои PNG, иначе сыпались в эмодзи-фолбэк
  'hide', 'fang', 'sinew', 'ring', 'pelt', 'tusk', 'chitin', 'orc_scrap', 'malt', 'flour',
])
export function ResIcon({ k, emoji, size }: { k: string; emoji?: string; size?: number }) {
  if (RES_HAS.has(k)) {
    const st = size ? { width: size, height: size } : undefined
    return <img className="ric" style={st} src={`${import.meta.env.BASE_URL}res/${k}.png`} alt="" loading="lazy" />
  }
  return <span className="ric-e">{emoji ?? '•'}</span>
}

// иконки товаров: miniapp/public/goods/<file>.png
const GOOD_ICON: Record<string, string> = {
  ale1: 'ale', ale2: 'ale', ale3: 'ale', mead: 'mead', sbiten: 'sbiten', wine: 'wine',
  roast: 'roast', bread: 'bread', pie: 'pie', cured: 'cured', smoked_fish: 'smoked_fish',
  cheese: 'cheese', butter: 'butter',
  // новые блюда
  kebab: 'kebab', sausage: 'sausage', bliny: 'bliny',
  // эксклюзив-фляги Артели (Ф2b): раньше падали в заглушку 🍽 — теперь свои иконки
  zodchy_feast: 'zodchy_feast', mason_loaf: 'mason_loaf',
  artel_nectar: 'artel_nectar', thunder_sbiten: 'thunder_sbiten',
}
// зодар — валюта чуда: самоцвет вместо ⚒ (miniapp/public/ui/zodar.png)
export function Zodar({ size = 15 }: { size?: number }) {
  return <img className="zic" style={{ width: size, height: size }}
    src={`${import.meta.env.BASE_URL}ui/zodar.png`} alt="зодар" loading="lazy" />
}

export function GoodIcon({ k, size }: { k: string; size?: number }) {
  const st = size ? { width: size, height: size } : undefined
  const f = GOOD_ICON[k]
  if (f) return <img className="ric" style={st} src={`${import.meta.env.BASE_URL}goods/${f}.png`} alt="" loading="lazy" />
  return <span className="ric-e" style={size ? { fontSize: size * 0.8 } : undefined}>🍽</span>
}
