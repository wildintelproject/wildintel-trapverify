import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    tailwindcss(),
    react(),
  ],
  server: {
    proxy: {
      '/docs': { target: 'http://localhost:8765', changeOrigin: true },
      '/api': {
        target: 'http://localhost:8765',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', (_err, _req, res) => {
            const r = res as import('http').ServerResponse
            r.writeHead(503, { 'Content-Type': 'application/json' })
            r.end(JSON.stringify({ detail: 'Backend no disponible en puerto 8765. ¿Está corriendo el servidor?' }))
          })
        },
      },
    },
  },
})
