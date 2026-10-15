import { defineConfig, type ProxyOptions } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

const gateway = 'http://127.0.0.1:8001'

/** Shared by `vite` and `vite preview`. Preview without this returns 502/404 for /api. */
const proxy: Record<string, ProxyOptions> = {
  '/api': { target: gateway, changeOrigin: true },
  '/ws': { target: 'ws://127.0.0.1:8001', ws: true },
  '/health': { target: gateway, changeOrigin: true },
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5180,
    strictPort: true,
    host: '0.0.0.0',
    proxy,
  },
  preview: {
    port: 5180,
    strictPort: true,
    host: '0.0.0.0',
    proxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['vue', 'vue-router', 'pinia'],
          echarts: ['echarts/core', 'vue-echarts'],
        },
      },
    },
  },
})
