import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Мини-апп отдаётся aiohttp под /app/ (тот же сервис, что бот/карта на Railway).
// base фиксирован, чтобы пути к ассетам были /app/assets/... .
export default defineConfig({
  base: '/app/',
  plugins: [react()],
  build: { outDir: 'dist', assetsDir: 'assets', sourcemap: false },
})
