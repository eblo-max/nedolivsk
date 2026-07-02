import { useState } from 'react'
import { api } from '../api'
import { haptic, hapticNotify } from '../telegram'

const REGIONS = [
  { code: 'north_wilds', emoji: '❄️', name: 'Северная глушь', perk: '🪵 дерева по горло', bonus: '+50% 🪵 · −25% 🌿' },
  { code: 'green_valleys', emoji: '🌾', name: 'Зелёные долины', perk: '🌾 зерна хоть лопатой', bonus: '+50% 🌾 · −25% 🪵' },
  { code: 'red_wastes', emoji: '🏜', name: 'Красные пустоши', perk: '🌿 хмель крепче кулака', bonus: '+50% 🌿 · −25% 🌾' },
]

export default function Onboarding({ onCreated }: { onCreated: (st: unknown) => void }) {
  const [step, setStep] = useState<'welcome' | 'name' | 'region'>('welcome')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function create(region: string) {
    if (busy) return
    haptic('medium'); setBusy(true); setErr('')
    try {
      const r = await api<{ state: unknown }>('onboard', { name: name.trim(), region })
      hapticNotify('success'); onCreated(r.state)
    } catch (e) {
      const code = (e as { code?: string })?.code
      setErr(code === 'bad_name' ? 'Название — 2–40 знаков'
        : code === 'bad_region' ? 'Выбери регион'
        : 'Кабак не открылся — попробуй ещё')
      setBusy(false)
    }
  }

  return (
    <div className="onb">
      <div className="rise">
        <div className="title">НЕДОЛИВСК<small>САМЫЙ СКЛОЧНЫЙ ГОРОДОК</small></div>
        <div className="orn"><img className="orn-ic" src={`${import.meta.env.BASE_URL}goods/ale.png`} alt="" /></div>
      </div>

      {step === 'welcome' && (
        <div className="rise" style={{ animationDelay: '.05s' }}>
          <div className="card"><div className="card-b">
            <p className="flavor" style={{ textAlign: 'left', margin: 0 }}>
              Сраный городишко, где эль разбавляют мочой, а за лишний вопрос пересчитают зубы.
              Заводишь свой кабак — и тащишь эту вонючую наливайку в богатейший двор округи:
              гонишь работяг за добром, варишь пойло, спаиваешь сброд и гребёшь золото лопатой.
            </p>
            <p className="flavor" style={{ textAlign: 'left', margin: '10px 0 0' }}>
              И это не дрочильня по таймеру — тут <b style={{ color: 'var(--parch)' }}>живой город</b>:
              жители, заговоры, фракции, пьяные драмы. Каждый твой косяк город запомнит.
            </p>
          </div></div>
          <button className="btn gold" style={{ marginTop: 11 }} onClick={() => { haptic('medium'); setStep('name') }}>
            <img className="btn-ic" src={`${import.meta.env.BASE_URL}goods/ale.png`} alt="" />Завести кабак
          </button>
        </div>
      )}

      {step === 'name' && (
        <div className="rise" style={{ animationDelay: '.02s' }}>
          <div className="card"><div className="card-b">
            <div className="card-q">📜 Как обзовёшь свою забегаловку?</div>
            <input
              className="onb-input" autoFocus maxLength={40} value={name}
              placeholder="Кривая Кружка…" onChange={(e) => setName(e.target.value)}
            />
            <div className="muted" style={{ fontSize: 13, fontStyle: 'italic' }}>
              От 2 до 40 знаков. С этой вывеской тебе жить и спиваться.
            </div>
          </div></div>
          <div style={{ display: 'flex', gap: 9, marginTop: 11 }}>
            <button className="btn" style={{ flex: 1 }} onClick={() => { haptic('light'); setStep('welcome') }}>Назад</button>
            <button className="btn gold" style={{ flex: 2 }} disabled={name.trim().length < 2}
              onClick={() => { haptic('medium'); setStep('region') }}>Дальше →</button>
          </div>
        </div>
      )}

      {step === 'region' && (
        <div className="rise" style={{ animationDelay: '.02s' }}>
          <div className="card-q" style={{ padding: '2px 4px 10px' }}>
            🗺 Где вкопаешь первый столб, <b style={{ color: 'var(--parch)' }}>{name.trim()}</b>?
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {REGIONS.map((r) => (
              <button key={r.code} className="region-card" disabled={busy} onClick={() => create(r.code)}>
                <span className="re">{r.emoji}</span>
                <span className="rt">
                  <b>{r.name}</b>
                  <small>{r.perk}</small>
                  <em>{r.bonus}</em>
                </span>
              </button>
            ))}
          </div>
          {err && <div className="onb-err">{err}</div>}
          <button className="btn" style={{ marginTop: 11 }} disabled={busy}
            onClick={() => { haptic('light'); setStep('name') }}>← Поменять название</button>
          {busy && <div className="center" style={{ marginTop: 14 }}><div className="spin" /></div>}
        </div>
      )}
    </div>
  )
}
