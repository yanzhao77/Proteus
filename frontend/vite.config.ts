import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_PRODUCT_API_ORIGIN || 'http://127.0.0.1:8000'
  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_DEV_PORT) || 5173,
      proxy: {
        '/factory-home': { target, changeOrigin: true },
        '/session': { target, changeOrigin: true },
        '/production-drafts': { target, changeOrigin: true },
        '/entry-drafts': { target, changeOrigin: true },
        '/entry-proposals': { target, changeOrigin: true },
        '/entry-master-plans': { target, changeOrigin: true },
      }
    },
    test: { environment: 'jsdom', globals: true, setupFiles: './src/test/setup.ts' },
  }
})
