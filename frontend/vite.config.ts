import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// SPA 는 /app/ 경로에 마운트되어 기존 Jinja SSR 과 공존한다(단계 6 에서 / 로 승격).
// 빌드 산출물은 FastAPI 가 StaticFiles 로 서빙하는 ../src/myhouse/web/dist 로 보낸다.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/app/',
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  build: {
    outDir: path.resolve(import.meta.dirname, '../src/myhouse/web/dist'),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      // dev 모드: API/뮤테이션/정적자원은 FastAPI(8765)로 프록시.
      // '/run' 접두사는 /run-deals·/run-permits 까지 함께 커버한다.
      '/api': 'http://127.0.0.1:8765',
      '/curation': 'http://127.0.0.1:8765',
      '/complexes': 'http://127.0.0.1:8765',
      '/run': 'http://127.0.0.1:8765',
      '/static': 'http://127.0.0.1:8765',
    },
  },
})
