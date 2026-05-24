/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Local dev: backend runs at http://localhost:8000 via docker compose.
// Production: VITE_API_BASE_URL points at the staging/prod API host.
//
// Vitest config is included here behind a type assertion because the
// project's vite (rolldown-vite preview) and vitest's bundled vite emit
// incompatible Plugin<any> signatures. The runtime accepts the extra key.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  // @ts-expect-error — vitest config merged at runtime; types diverge across vite/rolldown
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
