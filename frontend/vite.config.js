import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'node:fs'

// API routes live at the top level (no /api prefix — see API.md), so the dev
// server proxies each backend prefix to uvicorn on :8000.
const apiPrefixes = ['/health', '/auth', '/chores', '/claims', '/users', '/transactions']

// Written by scripts/write-version.js just before `vite build`; absent under
// `vite` (dev) and vitest, where the stale-client check is off.
function frontendSha() {
  try {
    return JSON.parse(readFileSync(new URL('./public/version.json', import.meta.url))).frontend_sha
  } catch {
    return null
  }
}

export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  define: {
    __FRONTEND_SHA__: JSON.stringify(command === 'build' ? frontendSha() : null),
  },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    proxy: Object.fromEntries(apiPrefixes.map((p) => [p, 'http://localhost:8000'])),
  },
  test: {
    environment: 'jsdom',
  },
}))
