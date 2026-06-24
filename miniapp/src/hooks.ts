import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

interface State<T> { data: T | null; loading: boolean; error: string | null }

/** Загрузка состояния экрана с сервера. fallback — данные для оффлайн-превью
 * (когда нет initData/бэкенда), чтобы экран рисовался при локальной разработке. */
export function useApi<T>(path: string, fallback?: T) {
  const [s, setS] = useState<State<T>>({ data: null, loading: true, error: null })

  const reload = useCallback(() => {
    setS((p) => ({ ...p, loading: true }))
    api<T>(path)
      .then((d) => setS({ data: d, loading: false, error: null }))
      .catch((e) => setS({ data: fallback ?? null, loading: false, error: String(e?.code || e) }))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  useEffect(() => { reload() }, [reload])
  // позволяем экрану подменить данные локально (после действия) без перезагрузки
  const set = useCallback((d: T) => setS((p) => ({ ...p, data: d })), [])
  return { ...s, reload, set }
}
