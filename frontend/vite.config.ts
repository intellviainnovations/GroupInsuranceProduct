import { defineConfig } from "vitest/config";

// No @vitejs/plugin-react (not in the ADR-0001 baseline): Vite compiles TSX
// itself using the "jsx": "react-jsx" setting from tsconfig.json.
export default defineConfig({
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
