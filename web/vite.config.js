import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 중에는 EC2의 FastAPI로 프록시. 프론트에서 CORS 신경 안 써도 된다.
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, rewrite: p => p.replace(/^\/api/, '') } }
  }
})
