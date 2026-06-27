// Фоновая музыка мини-аппа: ротация треков по сценам, плавные переходы, mute с памятью.
// Автоплей в вебвью запрещён до жеста пользователя → стартуем по первому тапу (см. MusicToggle).
type Scene = 'tavern' | 'night'

// Сцены: трактир — уютные/дорожные; ночь (ходка) — тёмно-эпичные.
const TRACKS: Record<Scene, string[]> = {
  tavern: ['reveler', 'journey', 'traveler'],
  night: ['hymn', 'heroes'],
}
const VOL = 0.32                                   // фон — негромко
const url = (name: string) => `${import.meta.env.BASE_URL}music/${name}.mp3`

class Music {
  private audio: HTMLAudioElement | null = null
  private scene: Scene = 'tavern'
  private order: string[] = []
  private idx = 0
  private fadeTimer: number | null = null
  muted = false
  started = false
  private subs = new Set<() => void>()

  constructor() {
    try { this.muted = localStorage.getItem('nd_music_muted') === '1' } catch { /* */ }
  }
  subscribe(cb: () => void) { this.subs.add(cb); return () => { this.subs.delete(cb) } }
  private emit() { this.subs.forEach((f) => f()) }

  private ensure() {
    if (this.audio) return
    const a = new Audio()
    a.preload = 'auto'; a.volume = 0
    a.addEventListener('ended', () => this.advance())
    this.audio = a
  }
  private reshuffle() {
    const list = [...TRACKS[this.scene]]
    for (let i = list.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1));[list[i], list[j]] = [list[j], list[i]] }
    this.order = list; this.idx = 0
  }
  private fade(to: number, ms = 1400, after?: () => void) {
    if (!this.audio) return
    if (this.fadeTimer) { clearInterval(this.fadeTimer); this.fadeTimer = null }
    const a = this.audio, from = a.volume, steps = 28, dt = ms / steps
    let i = 0
    this.fadeTimer = window.setInterval(() => {
      i++; const v = from + (to - from) * (i / steps)
      a.volume = Math.max(0, Math.min(1, v))
      if (i >= steps) { if (this.fadeTimer) clearInterval(this.fadeTimer); this.fadeTimer = null; after?.() }
    }, dt)
  }
  private async playCurrent(fadeIn = true) {
    if (!this.audio || this.muted) return
    const name = this.order[this.idx]
    this.audio.src = url(name)
    this.audio.volume = fadeIn ? 0 : VOL
    try { await this.audio.play(); if (fadeIn) this.fade(VOL) } catch { /* нужен жест — стартанём позже */ }
  }
  private advance() {                              // трек доиграл → следующий (с пере-перемешиванием по кругу)
    this.idx++
    if (this.idx >= this.order.length) this.reshuffle()
    this.playCurrent(false)
  }

  /** Старт по первому жесту пользователя. */
  start() {
    if (this.started) return
    this.started = true
    this.ensure(); this.reshuffle()
    if (!this.muted) this.playCurrent()
    this.emit()
  }
  /** Сменить сцену (трактир ⇄ ночная ходка) — плавный кроссфейд на новый набор. */
  setScene(scene: Scene) {
    if (scene === this.scene) return
    this.scene = scene
    if (!this.started || this.muted) { this.reshuffle(); return }
    this.fade(0, 900, () => { this.reshuffle(); this.playCurrent() })
  }
  toggleMute() {
    this.muted = !this.muted
    try { localStorage.setItem('nd_music_muted', this.muted ? '1' : '0') } catch { /* */ }
    if (this.muted) { this.fade(0, 600, () => this.audio?.pause()) }
    else { this.ensure(); if (this.order.length === 0) this.reshuffle(); this.started = true; this.playCurrent() }
    this.emit()
  }
  /** Пауза/возобновление при сворачивании приложения. */
  setHidden(hidden: boolean) {
    if (!this.audio || this.muted || !this.started) return
    if (hidden) this.audio.pause()
    else this.audio.play().catch(() => { /* */ })
  }
}

export const music = new Music()
