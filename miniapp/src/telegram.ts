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

/** Нативная кнопка «назад» Telegram — навешиваем на колбэк (для стек-навигации).
 * Снимаем прошлый обработчик перед новым, иначе onClick копит хендлеры и «назад»
 * срабатывает многократно. */
let _backCb: (() => void) | null = null
export function setBackButton(onClick: (() => void) | null) {
  const b = tg?.BackButton
  if (!b) return
  if (_backCb) { b.offClick(_backCb); _backCb = null }
  if (onClick) { _backCb = onClick; b.onClick(onClick); b.show() }
  else b.hide()
}

/** Нативная нижняя кнопка Telegram (MainButton) — для главного действия экрана.
 * Возвращает true, если кнопка доступна (есть Telegram), иначе false — тогда
 * рисуем свою кнопку в интерфейсе. Цвет под наш «золотой» CTA. */
let _mainCb: (() => void) | null = null
export function setMainButton(opts: { text: string; onClick: () => void; enabled?: boolean } | null): boolean {
  const b = tg?.MainButton
  if (!b) return false
  if (_mainCb) { b.offClick(_mainCb); _mainCb = null }
  if (opts) {
    b.setParams({ text: opts.text, color: '#cf9a3c', text_color: '#241501',
                  is_active: opts.enabled !== false, is_visible: true })
    _mainCb = opts.onClick; b.onClick(opts.onClick)
  } else {
    b.hide()
  }
  return true
}
