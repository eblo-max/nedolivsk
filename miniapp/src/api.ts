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

/** POST на /api/<path> с initData в теле. Таймаут 6с → не виснем на белом экране. */
export async function api<T = unknown>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  const ctrl = new AbortController()
  const to = setTimeout(() => ctrl.abort(), 6000)
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
  } finally {
    clearTimeout(to)
  }
}
