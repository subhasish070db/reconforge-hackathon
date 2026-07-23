import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  // GCS object URLs include the bucket name in the path. Set
  // VITE_PUBLIC_BASE_PATH=/<bucket>/ for that deployment so Vite emits asset
  // URLs below the bucket instead of root-relative /assets URLs.
  base: process.env.VITE_PUBLIC_BASE_PATH || '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Backend runs on :8000 (docker-compose or `uvicorn app.main:app`).
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
