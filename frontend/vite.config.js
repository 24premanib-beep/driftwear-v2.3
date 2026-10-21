import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the Vite server proxies /api and /ws to the backend, so the
// browser talks to one origin and no CORS setup is needed locally.
const backend = process.env.VITE_DEV_BACKEND || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 900 },
  test: { environment: "node", include: ["src/**/*.test.js"] },
});
