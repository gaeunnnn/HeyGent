import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // true 는 IPv4 + IPv6 모두 listen. '0.0.0.0' 은 IPv4 만 listen 해서
    // Windows 에서 localhost (::1) 로 들어올 때 connection refused 가 발생한다.
    host: true,
    port: 5173,
    allowedHosts: ['k14e105.p.ssafy.io'],
  },
})
