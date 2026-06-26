import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/docs': { target: 'http://localhost:8765', changeOrigin: true },
      '/api': {
        target: 'http://localhost:8765',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', (_err, _req, res) => {
            res.writeHead(503, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify({ detail: 'Backend no disponible en puerto 8765. ¿Está corriendo el servidor?' }))
          })
        },
      },
    },
  },
})
