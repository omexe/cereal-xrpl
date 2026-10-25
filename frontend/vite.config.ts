import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

declare const process: { env: Record<string, string | undefined> };

// The live app reaches the cereal service through /api on its own origin: no CORS, no credentials in browser code.
// CEREAL_API picks the service (default the demo service on :8001). Port 5180 keeps clear of web/ on 5173.
const api = process.env.CEREAL_API ?? 'http://127.0.0.1:8001';
const proxy = { '/api': { target: api, changeOrigin: true, rewrite: (path: string) => path.replace(/^\/api/, '') } };

export default defineConfig({
  plugins: [react()],
  server: { port: 5180, strictPort: true, proxy },
  preview: { port: 5180, strictPort: true, proxy },
});
