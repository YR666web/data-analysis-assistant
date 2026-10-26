import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发代理：/api、/ws 转发到 FastAPI（8000 端口）
const backend = process.env.DATA_ANALYSIS_API_URL || 'http://localhost:8000'
const websocketBackend = backend.replace(/^http/, 'ws')
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
      },
      '/ws': {
        target: websocketBackend,
        ws: true,
      },
    },
  },
})
