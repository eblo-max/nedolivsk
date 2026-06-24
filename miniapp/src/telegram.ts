// Тонкая типизированная обёртка над официальным window.Telegram.WebApp
// (грузится через telegram-web-app.js в index.html). Полный контроль, без тяжёлых SDK.

type HapticStyle = 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'

interface TgWebApp {
  initData: string
  initDataUnsafe: { user?: { id: number; first_name?: string; username?: string } }
  version: string
  colorScheme: 'light' | 'dark'
  themeParams: Record<string, string>
  isExpanded: boolean
  viewportStableHeight: number
  contentSafeAreaInset?: { top: number; bottom: number; left: number; right: number }
  safeAreaInset?: { top: number; bottom: number; left: number; right: number }
  ready(): void
  expand(): void
  close(): void
  isVersionAtLeast(v: string): boolean
  setHeaderColor(c: string): void
  setBackgroundColor(c: string): void
  setBottomBarColor?(c: string): void
  disableVerticalSwipes?(): void
  enableClosingConfirmation?(): void
  HapticFeedback?: { impactOccurred(s: HapticStyle): void; notificationOccurred(t: 'success' | 'warning' | 'error'): void; selectionChanged(): void }
  BackButton?: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void }
  MainButton?: {
    setText(t: string): void; show(): void; hide(): void; enable(): void; disable(): void
    onClick(cb: () => void): void; offClick(cb: () => void): void
    setParams(p: { text?: string; color?: string; text_color?: string; is_active?: boolean; is_visible?: boolean }): void
  }
  onEvent(e: string, cb: () => void): void
  offEvent(e: string, cb: () => void): void
}

declare global {
  interface Window { Telegram?: { WebApp?: TgWebApp } }
}

export const tg: TgWebApp | undefined = window.Telegram?.WebApp

/** Безопасная проверка версии (старые клиенты — фичу не трогаем). */
export const atLeast = (v: string) => !!tg?.isVersionAtLeast?.(v)

/** Инициализация: вызвать один раз на старте. Тема/фон/safe-area/жесты. */
export function initTelegram() {
  if (!tg) return
  try {
    tg.ready()
    tg.expand()
    if (atLeast('7.7')) tg.disableVerticalSwipes?.()
    if (atLeast('6.1')) {
      tg.setHeaderColor('#0b0703')
      tg.setBackgroundColor('#0b0703')
    }
    if (atLeast('7.10')) tg.setBottomBarColor?.('#0b0703')
    applySafeArea()
    tg.onEvent('safeAreaChanged', applySafeArea)
    tg.onEvent('contentSafeAreaChanged', applySafeArea)
  } catch { /* старый клиент — игнор */ }
}

/** Прокидываем safe-area клиента в CSS-переменные (челки/навбар/шапка Telegram). */
function applySafeArea() {
  const r = document.documentElement.style
  const c = tg?.contentSafeAreaInset
  const s = tg?.safeAreaInset
  r.setProperty('--sa-top', `${(s?.top ?? 0) + (c?.top ?? 0)}px`)
  r.setProperty('--sa-bottom', `${(s?.bottom ?? 0) + (c?.bottom ?? 0)}px`)
}

export const initData = () => tg?.initData ?? ''
export const tgUser = () => tg?.initDataUnsafe?.user

/** Тактильный отклик (крафт/удар/переход). Молча игнорит, если не поддержано. */
export function haptic(style: HapticStyle = 'light') {
  try { tg?.HapticFeedback?.impactOccurred(style) } catch { /* */ }
}
export function hapticNotify(type: 'success' | 'warning' | 'error') {
  try { tg?.HapticFeedback?.notificationOccurred(type) } catch { /* */ }
}

/** Нативная кнопка «назад» Telegram — СТЕК обработчиков (под-экран → панель → …).
 * Активен верх стека; пусто — кнопка скрыта. pushBack при входе, popBack при выходе.
 * Снимаем прошлый onClick перед новым (иначе хендлеры копятся). */
const _backStack: (() => void)[] = []
let _backCb: (() => void) | null = null
function _applyBack() {
  const b = tg?.BackButton
  if (!b) return
  if (_backCb) { b.offClick(_backCb); _backCb = null }
  const top = _backStack[_backStack.length - 1]
  if (top) { _backCb = top; b.onClick(top); b.show() }
  else b.hide()
}
export function pushBack(cb: () => void) { _backStack.push(cb); _applyBack() }
export function popBack(cb: () => void) {
  const i = _backStack.lastIndexOf(cb)
  if (i >= 0) _backStack.splice(i, 1)
  _applyBack()
}
