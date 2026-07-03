import { haptic, openTgLink } from '../telegram'

const CHANNEL = 'https://t.me/nedolivsk'

/** Промо канала — обновления и вопросы. Показывается раз в сутки (гейт в App). */
export default function ChannelModal({ onClose }: { onClose: () => void }) {
  const open = () => { haptic('medium'); openTgLink(CHANNEL); onClose() }
  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="chan-card" onClick={(e) => e.stopPropagation()}>
        <div className="chan-emoji">📣</div>
        <div className="chan-title">Вести из Недоливска</div>
        <p className="chan-text">
          Обновления, новые механики и розыгрыши — в нашем канале.
          Там же можно задать вопрос и предложить идею.
        </p>
        <button className="btn gold chan-go" onClick={open}>🔔 Подписаться на канал</button>
        <button className="chan-later" onClick={() => { haptic('light'); onClose() }}>Позже</button>
      </div>
    </div>
  )
}
