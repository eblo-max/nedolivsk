import { useEffect, useState } from 'react'
import { api, errText } from '../api'
import { Zodar } from '../components/icons'
import { haptic, hapticNotify } from '../telegram'

interface Reward {
  id: string; emoji: string; name: string; desc: string
  cost: number; kind: string; owned: boolean; affordable: boolean
  building?: string; effect?: string; tier?: string; style?: string
}
interface Resp { ok?: boolean; zodar: number; catalog: Reward[] }

const DEV = import.meta.env.DEV
const SAMPLE: Resp = {
  zodar: 620,
  catalog: [
    { id: 't_zodchy', emoji: '🔨', name: 'Титул «Зодчий»', desc: 'Первый камень лёг твоей рукой — город запомнил.', cost: 10, kind: 'title', owned: false, affordable: true, style: 'stone' },
    { id: 't_mason', emoji: '🧱', name: 'Титул «Каменщик Недоливска»', desc: 'Цех каменщиков жмёт тебе руку.', cost: 25, kind: 'title', owned: false, affordable: true, style: 'bronze' },
    { id: 't_pillar', emoji: '🏛', name: 'Титул «Столп Общины»', desc: 'На таких, как ты, держится весь город.', cost: 80, kind: 'title', owned: false, affordable: true, style: 'silver' },
    { id: 't_keeper', emoji: '🛡', name: 'Титул «Хранитель Твердыни»', desc: 'Стены стоят твоим радением — Орда обходит город.', cost: 200, kind: 'title', owned: false, affordable: true, style: 'gold' },
    { id: 't_spark', emoji: '⚡', name: 'Титул «Искра Артели»', desc: 'Имя горит электрическим неоном.', cost: 220, kind: 'title', owned: false, affordable: true, style: 'neon' },
    { id: 't_mirage', emoji: '🔮', name: 'Титул «Мираж Недоливска»', desc: 'Имя мерцает, как марево над степью.', cost: 260, kind: 'title', owned: false, affordable: true, style: 'plasma' },
    { id: 't_frost', emoji: '❄', name: 'Титул «Хладный Мастер»', desc: 'Имя дышит инеем — кладка ровна, как лёд.', cost: 300, kind: 'title', owned: false, affordable: true, style: 'frost' },
    { id: 't_ember', emoji: '🔥', name: 'Титул «Пламенный Зодчий»', desc: 'Имя тлеет жаром кузнечного горна.', cost: 320, kind: 'title', owned: false, affordable: true, style: 'ember' },
    { id: 't_void', emoji: '🌑', name: 'Титул «Тень Основания»', desc: 'Имя дышит бездной — ты был у первого камня.', cost: 400, kind: 'title', owned: false, affordable: true, style: 'void' },
    { id: 't_legend', emoji: '👑', name: 'Титул «Вечный Зодчий»', desc: 'Высшее имя — переливается, как самоцвет-голограмма.', cost: 500, kind: 'title', owned: false, affordable: true, style: 'holo' },
    { id: 'f_carved', emoji: '🪵', name: 'Резной фасад', desc: 'Артель вырежет узор по вывеске.', cost: 40, kind: 'facade', owned: false, affordable: true, tier: 'bronze' },
    { id: 'f_gilded', emoji: '✨', name: 'Златая вывеска', desc: 'Сусальное золото по краю — видно за версту.', cost: 120, kind: 'facade', owned: false, affordable: true, tier: 'silver' },
    { id: 'f_crested', emoji: '💎', name: 'Самоцветный герб', desc: 'Герб Артели с самоцветами над дверью.', cost: 300, kind: 'facade', owned: false, affordable: true, tier: 'gold' },
    { id: 'f_blazing', emoji: '🔥', name: 'Пылающий герб Артели', desc: 'Герб, что тлеет вечным углём Твердыни.', cost: 600, kind: 'facade', owned: false, affordable: true, tier: 'legendary' },
    { id: 'r_feast', emoji: '🍗', name: 'Рецепт «Пир зодчих»', desc: 'Чертёж артельного стола. Варишь на КУХНЕ — снедь, что ставит бойца на ноги.', cost: 220, kind: 'recipe', owned: false, affordable: true, building: 'Кухня', effect: '+45 ❤ на бой (лучшая еда в игре)' },
    { id: 'r_loaf', emoji: '🍞', name: 'Рецепт «Каравай каменщика»', desc: 'Чертёж плотного каравая. Печёшь в ПЕКАРНЕ — держит удар и рушит яд.', cost: 240, kind: 'recipe', owned: true, affordable: true, building: 'Пекарня', effect: '+28% уворота и антидот на бой' },
    { id: 'r_nectar', emoji: '🍷', name: 'Рецепт «Артельный нектар»', desc: 'Чертёж крепкого нектара. Гонишь в ВИНОКУРНЕ — рука бьёт без промаха.', cost: 260, kind: 'recipe', owned: false, affordable: true, building: 'Винокурня', effect: '+20% крита на бой' },
    { id: 'r_sbiten', emoji: '⚡', name: 'Рецепт «Громовой сбитень»', desc: 'Чертёж грозового сбитня. Варишь в МЕДОВАРНЕ — удар как обвал стены.', cost: 260, kind: 'recipe', owned: false, affordable: true, building: 'Медоварня', effect: '+22 урона на бой' },
    { id: 'r_hammer', emoji: '⚒', name: 'Чертёж «Молот Зодчего»', desc: 'Чертёж артельного молота. Куёшь в КУЗНИЦЕ — сильнейшее оружие Недоливска, надел и владеешь.', cost: 450, kind: 'recipe', owned: false, affordable: false, building: 'Кузница', effect: 'Оружие: урон 50, крит 15 (БиС)' },
  ],
}

const RAR_LABEL: Record<string, string> = {
  bronze: 'обычный', silver: 'редкий', gold: 'эпический', legendary: 'легендарный',
}
const STYLE_LABEL: Record<string, string> = {
  stone: 'камень', bronze: 'медь', silver: 'серебро', gold: 'золото',
  neon: 'неон', plasma: 'плазма', frost: 'иней', ember: 'жар', void: 'бездна', holo: 'голограмма',
}

/** Лавка Артели зодчих — трата редкой валюты «Зодар» на престиж. */
export default function ArtelSheet({ onClose }: { onClose: () => void }) {
  const [d, setD] = useState<Resp | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    (DEV ? Promise.resolve(SAMPLE) : api<Resp>('artel'))
      .then(setD).catch(() => setD({ zodar: 0, catalog: [] }))
  }, [])

  async function buy(r: Reward) {
    if (busy || r.owned || !r.affordable) return
    setBusy(true); setErr(''); haptic('medium')
    try {
      const res: Resp = DEV
        ? { zodar: d!.zodar - r.cost, catalog: d!.catalog.map((x) => x.id === r.id ? { ...x, owned: true } : x) }
        : await api<Resp>('artel/buy', { id: r.id })
      setD(res); hapticNotify('success')
    } catch (e) { setErr(errText(e)); hapticNotify('error') }
    finally { setBusy(false) }
  }

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="ar-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="ar-head">
          <span className="ar-title"><Zodar size={18} /> Лавка Артели зодчих</span>
          <span className="ar-bal" title="Зодары — только за стройки">{d?.zodar ?? 0} <Zodar /></span>
        </div>
        <p className="ar-lore">«Зодар не купишь и не пропьёшь — его вручают за руки, что подняли чудеса города.»</p>

        {d === null ? (
          <div className="center" style={{ padding: '40px 0' }}><div className="spin" /></div>
        ) : (
          <>
            {(['recipe', 'prestige'] as const).map((sec) => {
              const rows = d.catalog.filter((r) =>
                sec === 'recipe' ? r.kind === 'recipe' : r.kind !== 'recipe')
              if (!rows.length) return null
              return (
                <div key={sec} className="ar-group">
                  <div className="ar-sec">
                    {sec === 'recipe' ? '📜 Эксклюзив-рецепты' : '🏛 Престиж'}
                    <small>{sec === 'recipe'
                      ? 'Купил чертёж — варишь/куёшь навсегда'
                      : 'Звания и облик — видно всему городу'}</small>
                  </div>
                  <div className="ar-list">
                    {rows.map((r) => (
                      <div key={r.id} className={`ar-card${r.owned ? ' owned' : ''}${r.kind === 'recipe' ? ' recipe' : ''}${r.style ? ' s-' + r.style : ''}${r.tier ? ' t-' + r.tier : ''}`}>
                        <span className="ar-emo">{r.emoji}</span>
                        <div className="ar-body">
                          <div className="ar-head-row">
                            <div className="ar-name">
                              {r.name}
                              {r.style
                                ? <span className={`ar-rar st-${r.style}`}>{STYLE_LABEL[r.style] || ''}</span>
                                : r.tier && <span className={`ar-rar rar-${r.tier}`}>{RAR_LABEL[r.tier] || ''}</span>}
                            </div>
                            {r.owned ? (
                              <span className="ar-have">✓ есть</span>
                            ) : (
                              <button className="btn ar-buy" disabled={busy || !r.affordable}
                                onClick={() => buy(r)}>{r.cost} <Zodar size={13} /></button>
                            )}
                          </div>
                          {r.kind === 'recipe' && r.effect && (
                            <div className="ar-eff">💥 {r.effect}</div>
                          )}
                          <div className="ar-desc">{r.desc}</div>
                          {r.kind === 'recipe' && r.building && (
                            <div className="ar-where">🏭 {r.building}</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </>
        )}

        {err && <div className="wd-err">⚠ {err}<small>Попробуй снова</small></div>}
        <button className="btn gold" style={{ marginTop: 10 }} onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
