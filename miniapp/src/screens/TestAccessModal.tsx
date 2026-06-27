import { haptic, openTgLink } from '../telegram'

const CHANNEL = 'https://t.me/nedolivsk'

/** Дисклеймер раннего доступа — показывается при КАЖДОМ входе в мини-апп.
 * Поясняет, что часть механик ещё в текстовом боте, и зовёт репортить баги в канал. */
export default function TestAccessModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="ta-backdrop">
      <div className="ta-card">
        <div className="ta-badge">⚠️ РАННИЙ ДОСТУП</div>
        <div className="ta-title">Тестовая версия</div>
        <p className="ta-text">
          Это ранний тестовый доступ к Недоливску. Часть механик пока работает
          только в текстовом боте — <b>Торг</b> и <b>Мировая карта</b> ещё в разработке.
        </p>
        <p className="ta-text">
          Поймал баг или несуразицу? Приложи <b>скриншот</b> в комментарии в нашем
          канале — так мы быстрее отшлифуем кабак.
        </p>
        <button className="btn ta-chan" onClick={() => { haptic('light'); openTgLink(CHANNEL) }}>
          📣 Наш канал — @nedolivsk
        </button>
        <button className="btn gold ta-ok" onClick={() => { haptic('medium'); onClose() }}>
          🍺 Понятно, наливай!
        </button>
      </div>
    </div>
  )
}
