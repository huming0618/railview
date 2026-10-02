import { defineConfig } from 'vite';

// GitHub Pages: /railview/; Capacitor / offline: VITE_BASE=./
export default defineConfig({
  base: process.env.VITE_BASE || '/railview/',
  server: { host: true, port: 5175 },
  build: { outDir: 'dist', assetsDir: 'assets' },
});
