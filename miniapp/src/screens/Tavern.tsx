import { useApi } from '../hooks'

interface TavernState {
  ok: boolean
  tavern_name: string
  name: string
  level: number
  gold: number
  res: Record<string, number>
  income_rate: number
  income_ready: number      // накоплено к сбору
  next_upgrade?: Record<string, number>
}

// образец для оффлайн-превью (пока нет /api/state или вне Telegram)
const SAMPLE: TavernState = {
  ok: true, tavern_name: 'Кривая Кружка', name: 'Хозяин', level: 2,
  gold: 1340, res: { wood: 60, grain: 80, hops: 45, ingot: 6 },
  income_rate: 18, income_ready: 126,
  next_upgrade: { gold: 715, wood: 220, grain: 180, hops: 120 },
}

const RES_META: Record<string, [string, string]> = {
  wood: ['🪵', 'Дерево'], grain: ['🌾', 'Зерно'], hops: ['🌿', 'Хмель'],
  stone: ['🪨', 'Камень'], ore: ['⛏', 'Руда'], clay: ['🟤', 'Глина'], ingot: ['🔩', 'Слиток'],
}

export default function Tavern() {
  const { data, loading } = useApi<TavernState>('state', SAMPLE)

  if (loading && !data) return <div className="center" style={{ flex: 1 }}><div className="spin" /></div>
  const t = data ?? SAMPLE

  return (
    <>
      <div className="rise">
        <div className="title">{(t.tavern_name || 'НЕДОЛИВСК').toUpperCase()}<small>УРОВЕНЬ {t.level}</small></div>
        <div className="orn"><b>✦</b></div>
      </div>

      <div className="panel rise" style={{ animationDelay: '.05s' }}>
        <div className="ph">КАЗНА</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '12px 13px', justifyContent: 'center' }}>
          <Coin emoji="🪙" v={t.gold} gold />
          {Object.entries(t.res).filter(([, v]) => v > 0).map(([k, v]) => (
            <Coin key={k} emoji={RES_META[k]?.[0] ?? '•'} v={v} />
          ))}
        </div>
      </div>

      <div className="panel rise" style={{ animationDelay: '.1s' }}>
        <div className="ph">ДОХОД</div>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <span className="muted" style={{ fontStyle: 'italic' }}>Гости пьют, монета капает</span>
          <span style={{ fontFamily: 'var(--num)', fontWeight: 700, color: 'var(--gold)' }}>+{t.income_rate}/ч</span>
        </div>
        <div style={{ padding: '0 13px 13px' }}>
          <button className="btn gold" disabled={t.income_ready <= 0}>
            {t.income_ready > 0 ? `Собрать +${t.income_ready} 🪙` : 'Пока пусто'}
          </button>
        </div>
      </div>

      {t.next_upgrade && (
        <div className="panel rise" style={{ animationDelay: '.15s' }}>
          <div className="ph">УЛУЧШИТЬ ТАВЕРНУ</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '12px 13px', justifyContent: 'center' }}>
            {Object.entries(t.next_upgrade).map(([k, v]) => (
              <Coin key={k} emoji={k === 'gold' ? '🪙' : RES_META[k]?.[0] ?? '•'} v={v}
                gold={k === 'gold'} have={k === 'gold' ? t.gold : t.res[k] ?? 0} />
            ))}
          </div>
          <div style={{ padding: '0 13px 13px' }}>
            <button className="btn">⬆ Улучшить до ур. {t.level + 1}</button>
          </div>
        </div>
      )}

      <div className="flavor rise" style={{ animationDelay: '.2s' }}>
        «Кабак не строится за ночь — но и не пропьётся, коль хозяин с головой.»
      </div>
    </>
  )
}

function Coin({ emoji, v, gold, have }: { emoji: string; v: number; gold?: boolean; have?: number }) {
  const short = have !== undefined && have < v   // не хватает на апгрейд → красным
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 5, padding: '5px 9px', borderRadius: 7,
      fontFamily: 'var(--num)', fontWeight: 700, fontSize: 14,
      background: 'linear-gradient(#2c1e0d,#191007)', border: '1px solid var(--line2)',
      color: short ? '#d8694e' : gold ? '#f0d37a' : 'var(--parch)',
      boxShadow: 'inset 0 1px 0 #ffffff12,0 2px 6px #0006',
    }}>
      <b style={{ fontSize: 15 }}>{emoji}</b>{have !== undefined ? `${have}/${v}` : v}
    </div>
  )
}
