// Метаданные анимированного пака монстров (miniapp/public/monsters/<key>/<anim>.webp).
// Сгенерировано из исходных спрайт-листов (animal_attak); см. _proc.py.
// Каждый .webp — горизонтальная лента из N кадров fw×fh.
export interface MonMeta { fw: number; fh: number; idle: number; attack: number; hurt: number; death: number; run?: number }

export const MONSTERS: Record<string, MonMeta> = {
  flying_eye: { fw: 150, fh: 150, idle: 6, attack: 6, hurt: 4, death: 5 },
  gargoyle: { fw: 144, fh: 96, idle: 6, attack: 9, hurt: 6, death: 7 },
  medusa: { fw: 150, fh: 125, idle: 6, attack: 6, hurt: 3, death: 6 },
  centaur: { fw: 148, fh: 96, idle: 10, attack: 10, hurt: 6, death: 9 },
  cerberus: { fw: 128, fh: 128, idle: 14, attack: 15, hurt: 6, death: 11 },
  minotaur: { fw: 128, fh: 128, idle: 6, attack: 6, hurt: 5, death: 6 },
  skeleton: { fw: 89, fh: 78, idle: 6, attack: 5, hurt: 5, death: 6 },
  golem: { fw: 220, fh: 96, idle: 13, attack: 20, hurt: 6, death: 10 },
  goblin: { fw: 116, fh: 78, idle: 6, attack: 6, hurt: 3, death: 10 },
  dragon: { fw: 144, fh: 96, idle: 9, attack: 13, hurt: 4, death: 7 },
  harpy: { fw: 96, fh: 96, idle: 6, attack: 9, hurt: 6, death: 7 },
  satyr: { fw: 96, fh: 96, idle: 12, attack: 12, hurt: 6, death: 9 },
  witch: { fw: 125, fh: 125, idle: 6, attack: 6, hurt: 3, death: 7 },
}

// Спрайты, смотрящие ВЛЕВО по умолчанию — их зеркалим, чтобы смотрели на героя (вправо).
export const MON_FLIP: Record<string, boolean> = { medusa: true, dragon: true, harpy: true }

// Герой-гном (тот же персонаж, что hero_static.png) — анимир. спрайт-листы character/hero/<anim>.webp.
// Смотрит вправо по умолчанию → в бою зеркалим (он справа, лицом к монстру слева).
export const HERO: MonMeta = { fw: 255, fh: 240, idle: 10, attack: 10, hurt: 10, death: 10, run: 10 }

// дальнобойные монстры: ключ спрайта → ассет снаряда (miniapp/public/fx/<asset>.webp)
export const RANGED: Record<string, string> = {
  flying_eye: 'proj_flying_eye', witch: 'proj_witch', satyr: 'proj_satyr',
}

export type AnimName = 'idle' | 'attack' | 'hurt' | 'death' | 'run'
