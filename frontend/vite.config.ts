import path from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

const backend = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(rootDir, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // admin/ab/audit/feedback/eval/personalization/rag/capabilities
      '/api': backend,
      '/chat': backend,
      '/streaming': backend,
      '/enhanced-chat': backend,
      '/agent': backend,
      '/memory': backend,
      '/performance': backend,
      '/health': backend, // 登录验证用,无 /api 前缀
      '/playground': backend,
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    restoreMocks: true,
  },
})
