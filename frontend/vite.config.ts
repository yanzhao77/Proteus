import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_PRODUCT_API_ORIGIN || 'http://127.0.0.1:8000'
  return {
    plugins: [react()],
    server: { proxy: { '/factory-home': { target, changeOrigin: true } } },
    test: { environment: 'jsdom', globals: true, setupFiles: './src/test/setup.ts' },
  }
})
