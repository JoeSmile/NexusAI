import path from 'node:path'
import { EventEmitter } from 'node:events'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Quiets MaxListenersExceededWarning from http-proxy under Vite HMR.
EventEmitter.defaultMaxListeners = Math.max(EventEmitter.defaultMaxListeners, 20)

const rootDir = path.dirname(fileURLToPath(import.meta.url))

const backend = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(rootDir, './src'),
      // Force single React — @chatui/core CJS deep imports otherwise get a null dispatcher
      react: path.resolve(rootDir, './node_modules/react'),
      'react-dom': path.resolve(rootDir, './node_modules/react-dom'),
    },
    dedupe: ['react', 'react-dom'],
  },
  optimizeDeps: {
    include: ['@chatui/core', 'react', 'react-dom'],
  },
  server: {
    port: 5173,
    // Vite http-proxy stacks `close` listeners under HMR; raise default to quiet the warning.
    // Does not fix root cause if a real leak exists — keep an eye on long-lived tabs.
    proxy: {
      // admin/ab/audit/feedback/eval/personalization/rag/capabilities
      '/api': backend,
      '/chat': backend,
      '/feedback': backend,
      '/agent': backend,
      '/memory': backend,
      '/performance': backend,
      '/evaluation': backend,
      '/health': backend, // 登录验证用,无 /api 前缀
      '/playground': backend,
      // SPA 占用 `/`；环境徽章经此后端根 JSON（30.13）
      '/cg-meta': { target: backend, changeOrigin: true, rewrite: () => '/' },
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    restoreMocks: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
