/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// The interface and the API share one origin. In development Vite proxies /api
// and /ws to the backend, so session cookies, the Command Center socket and the
// MJPEG <img> streams all behave exactly as they do when FastAPI serves the
// production build itself.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_BACKEND_URL || "http://127.0.0.1:8000";
  // 5173 is occupied on this machine by an unrelated project; overridable via VITE_PORT.
  const port = Number(env.VITE_PORT) || 5180;

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    server: {
      host: "127.0.0.1",
      port,
      strictPort: true,
      proxy: {
        "/api": { target: backend, changeOrigin: false },
        "/ws": { target: backend.replace(/^http/, "ws"), ws: true, changeOrigin: false },
      },
    },
    preview: {
      host: "127.0.0.1",
      port: 4173,
      proxy: {
        "/api": { target: backend, changeOrigin: false },
        "/ws": { target: backend.replace(/^http/, "ws"), ws: true, changeOrigin: false },
      },
    },
    build: {
      target: "es2022",
      sourcemap: true,
      chunkSizeWarningLimit: 700,
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: false,
      restoreMocks: true,
    },
  };
});
