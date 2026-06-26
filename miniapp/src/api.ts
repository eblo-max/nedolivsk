import { initData } from './telegram'

// API того же сервиса (aiohttp): в проде — относительный /api, в dev можно
// переопределить через VITE_API_BASE (указать на Railway-домен или локальный бот).
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api'

export class ApiError extends Error {
  code: string
  status: number
  constructor(code: string, status: number) {
    super(code)
    this.code = code
    this.status = status
  }
}

/** POST на /api/<path> с initData в теле. Таймаут 15с (холодный старт Railway/
 *  медленная сеть легко перебивали прежние 6с → ложное «Не вышло»). */
export async function api<T = unknown>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  const ctrl = new AbortController()
  const to = setTimeout(() => ctrl.abort(), 15000)
  try {
    const r = await fetch(`${BASE}/${path}`, {
      method: 'POST',
      signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData: initData(), ...body }),
    })
    const data = await r.json().catch(() => ({}))
    if (!r.ok || (data && data.ok === false)) {
      throw new ApiError((data && data.error) || `http_${r.status}`, r.status)
    }
    return data as T
  } catch (e) {
    if (e instanceof ApiError) throw e
    // таймаут (abort) или сетевой сбой — отдаём распознаваемый код
    const aborted = (e as { name?: string })?.name === 'AbortError'
    throw new ApiError(aborted ? 'timeout' : 'network', 0)
  } finally {
    clearTimeout(to)
  }
}

/** Человеческий текст ошибки по коду ApiError — чтобы вместо «Не вышло» было видно суть. */
export function errText(e: unknown, fallback = 'Не вышло'): string {
  const code = (e as { code?: string })?.code
  switch (code) {
    case 'not_ready': return 'Ещё не готово'
    case 'not_enough': return 'Не хватает сырья'
    case 'busy': return 'Уже работает — дождись'
    case 'auth': return 'Сессия устарела — закрой и открой приложение заново'
    case 'timeout': return 'Сервер не ответил — попробуй ещё раз'
    case 'network': return 'Нет связи — проверь интернет'
    case 'no_tavern': return 'Сначала создай таверну'
    default: return code ? `Ошибка: ${code}` : fallback
  }
}
