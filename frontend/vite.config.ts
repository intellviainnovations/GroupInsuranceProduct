import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

// No @vitejs/plugin-react (not in the ADR-0001 baseline): Vite compiles TSX
// itself using the "jsx": "react-jsx" setting from tsconfig.json.
// Dev only: /api is proxied to the backend so the browser stays same-origin
// (no CORS; the HttpOnly session cookie and CSRF header work on localhost).
const apiTarget = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [tailwindcss()],
  server: {
    host: "localhost",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Source maps stay off so the production bundle does not expose source.
    sourcemap: false,
    // Never inline assets as data: URIs; lets the bank proxy apply a strict CSP.
    assetsInlineLimit: 0,
    // Keep index.html free of inline scripts.
    modulePreload: { polyfill: false },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
