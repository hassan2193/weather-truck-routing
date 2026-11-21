import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In development the Django API runs on :8000; the proxy keeps requests same-origin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true } },
  },
  build: { chunkSizeWarningLimit: 700 },
})
