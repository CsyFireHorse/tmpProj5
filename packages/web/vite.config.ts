import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const API_TARGET = process.env.ACV_API ?? "http://127.0.0.1:8787";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // The backend owns every local capability; the browser only talks HTTP.
      "/api": { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    // The built app is served same-origin by the Python package.
    outDir: "../server/src/agent_chat_viewer/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
