import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { haptic } from '../telegram'

interface Note { text: string; ago: string; read: boolean }

// HTML-теги бота (<b>,<a>…) убираем, базовые сущности раскодируем — выводим как текст (без инъекций).
function plain(t: string): string {
  return (t || '')
    .replace(/<[^>]*>/g, '')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&')
}

/** Раздел «Уведомления» — зеркало ВСЕХ DM-нотификаций бота. При открытии гасим бейдж.
 *  Для админа — кнопка засеять все типы уведомлений (тест ленты). */
export default function NotificationsSheet({ admin, onClose }: { admin?: boolean; onClose: () => void }) {
  const [items, setItems] = useState<Note[] | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api<{ items: Note[] }>('notifications').then((r) => setItems(r.items || [])).catch(() => setItems([]))
  }, [])

  useEffect(() => {
    load()
    api('notifications/read').catch(() => {})   // отметить прочитанными при открытии
  }, [load])

  async function seedAll() {
    if (busy) return
    setBusy(true); haptic('medium')
    try { await api('notifications/seed_all'); load() } catch { /* ignore */ }
    finally { setBusy(false) }
  }

  return (
    <div className="sv-backdrop" onClick={onClose}>
      <div className="chron-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="chron-head">🔔 Уведомления</div>
        {admin && (
          <button className="btn" disabled={busy} style={{ marginBottom: 10 }} onClick={seedAll}>
            {busy ? 'Сею…' : '🧪 Засеять все типы (тест)'}
          </button>
        )}
        {items === null ? (
          <div className="center" style={{ padding: '34px 0' }}><div className="spin" /></div>
        ) : items.length === 0 ? (
          <p className="chron-empty">«Тихо, как в погребе на рассвете. Ни одной вести — знать, мир тебя пока бережёт.»</p>
        ) : (
          <div className="chron-list">
            {items.map((e, i) => (
              <div key={i} className={`chron-row nf-row${e.read ? '' : ' nf-unread'}`}>
                <span className="chron-dot" />
                <div className="chron-body">
                  <p className="chron-text">{plain(e.text)}</p>
                  {e.ago && <span className="chron-ago">{e.ago}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
        <button className="btn gold chron-close" onClick={() => { haptic('light'); onClose() }}>← Закрыть</button>
      </div>
    </div>
  )
}
