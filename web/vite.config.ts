import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
// Side-effect import: `vitest/config` augments Vite's `UserConfig` with the
// `test` key. A triple-slash `<reference types>` does not reliably resolve
// a subpath export like this one, so the import is the load-bearing part —
// `defineConfig` still comes from "vite" itself, unchanged.
import "vitest/config";

// Before anything reads a date. Several screens render a wall clock —
// reply timestamps, "as of 14:02" — and `Intl` resolves the zone from the
// process. Without this, those assertions pass in London and fail in
// Sydney, which is the worst kind of test.
process.env.TZ = "UTC";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // Dev is two processes: Vite here, uvicorn on 8000. Proxying rather
    // than enabling CORS keeps the app same-origin in development and
    // identical to the deployment where the built SPA is served by
    // uvicorn itself — so no request path is exercised only in one mode.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
  },
});
