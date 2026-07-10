import path from 'path'
import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] }),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    // Listen on every interface so other devices on the LAN can reach the dev
    // server (Vite prints a "Network:" URL to open from another PC/phone).
    host: true,
    port: 5173,
    strictPort: true,
    // Allow serving through a cloudflare quick tunnel (*.trycloudflare.com) so
    // Telegram's OIDC redirect can reach the dev server over public HTTPS.
    allowedHosts: ['.trycloudflare.com'],
    // Forward API calls to the FastAPI backend during local dev so the
    // frontend can use same-origin `/api/v1` paths (no CORS needed). The proxy
    // runs on this machine, so the backend target stays localhost.
    proxy: {
      '/api': {
        // Defaults to the backend on :8000; override with VITE_PROXY_TARGET
        // when the backend runs elsewhere (e.g. :8001 if 8000 is taken).
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
