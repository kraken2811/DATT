import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'

const runtimeOutDir = process.env.DATT_FRONTEND_OUT_DIR

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      'lucide-react': fileURLToPath(new URL('./src/icons/lucideCompat.jsx', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8501',
      '/telemetry': 'http://127.0.0.1:8501',
      '/cameras': 'http://127.0.0.1:8501',
      '/switch_camera': 'http://127.0.0.1:8501',
      '/stop_camera': 'http://127.0.0.1:8501',
      '/select_source': 'http://127.0.0.1:8501',
      '/public_cameras': 'http://127.0.0.1:8501',
      '/video_sources': 'http://127.0.0.1:8501',
      '/targets': 'http://127.0.0.1:8501',
      '/events': 'http://127.0.0.1:8501',
      '/event_snapshot': 'http://127.0.0.1:8501',
      '/video_feed': 'http://127.0.0.1:8501',
      '/frame_packet': 'http://127.0.0.1:8501',
      '/frame_stream': 'http://127.0.0.1:8501',
      '/static': 'http://127.0.0.1:8501',
    },
  },
  build: {
    outDir: runtimeOutDir || '../src/ui/static/react_dist',
    emptyOutDir: true,
  },
})
