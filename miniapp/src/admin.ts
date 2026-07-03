import { useState, useEffect } from 'react'
import { api } from './api'

// Мягкий гейт «только для админа» на клиенте. Источник правды — серверный флаг
// admin из /api/state (uid == ADMIN_ID). Запрос делаем ОДИН раз на весь апп
// (кэш + in-flight промис), результат разделяют все экраны. Это не безопасность
// (все действия проверяет сервер), а видимость сырых фич до релиза всем.
// В dev (превью без бэка) считаем себя админом — иначе не проверить обучение.
let _cached: boolean | null = null
let _inflight: Promise<boolean> | null = null

export function whoamiAdmin(): Promise<boolean> {
  if (_cached !== null) return Promise.resolve(_cached)
  if (!_inflight) {
    _inflight = api<{ admin?: boolean }>('state')
      .then((s) => { _cached = !!s.admin; return _cached })
      .catch(() => { _cached = import.meta.env.DEV; return _cached })
  }
  return _inflight
}

export function useIsAdmin(): boolean {
  const [v, setV] = useState<boolean>(_cached ?? false)
  useEffect(() => { whoamiAdmin().then(setV) }, [])
  return v
}
