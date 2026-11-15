import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 백엔드 주소. docker에서는 API_TARGET=http://backend:8000
const proxy = { '/api': { target: process.env.API_TARGET ?? 'http://localhost:8000', changeOrigin: true } }

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: true, port: 5173, proxy },
  preview: { host: true, port: 5173, proxy },
})
