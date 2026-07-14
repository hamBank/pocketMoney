import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// API routes live at the top level (no /api prefix — see API.md), so the dev
// server proxies each backend prefix to uvicorn on :8000.
const apiPrefixes = ['/health', '/auth', '/chores', '/claims', '/users', '/transactions']

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
})
