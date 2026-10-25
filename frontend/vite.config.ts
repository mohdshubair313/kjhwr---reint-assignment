import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    babel({ presets: [reactCompilerPreset()] })
  ],
  server: {
    proxy: { '/api': process.env.REINT_DEV_API_TARGET ?? 'http://127.0.0.1:8000', '/health': process.env.REINT_DEV_API_TARGET ?? 'http://127.0.0.1:8000' },
  },
})
