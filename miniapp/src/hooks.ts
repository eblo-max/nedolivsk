import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

interface State<T> { data: T | null; loading: boolean; error: string | null }

/** Загрузка состояния экрана с сервера. fallback — данные ТОЛЬКО для локальной
 * разработки (vite dev), чтобы экран рисовался без бэкенда. В собранном приложении
 * (прод) fallback НЕ подставляется никогда — иначе при сбое (auth/timeout/пустой
 * initData) игрок увидел бы чужую демо-таверну вместо своей. */
export function useApi<T>(path: string, fallback?: T) {
  const [s, setS] = useState<State<T>>({ data: null, loading: true, error: null })

  const reload = useCallback(() => {
    setS((p) => ({ ...p, loading: true }))
    api<T>(path)
      .then((d) => setS({ data: d, loading: false, error: null }))
      .catch((e) => setS({
        // демо подставляем ТОЛЬКО в dev-сборке; в проде — null (экран покажет
        // «повтор»), иначе у игрока вместо его таверны видна чужая «Кривая Кружка».
        data: import.meta.env.DEV ? (fallback ?? null) : null,
        loading: false,
        error: String(e?.code || e),
      }))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  useEffect(() => { reload() }, [reload])
  // позволяем экрану подменить данные локально (после действия) без перезагрузки
  const set = useCallback((d: T) => setS((p) => ({ ...p, data: d })), [])
  return { ...s, reload, set }
}
