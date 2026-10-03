/// <reference types="vitest/config" />
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// The bridge serves the build from src/nestris_terminal/web.
const outDir = fileURLToPath(new URL("../src/nestris_terminal/web", import.meta.url));
const bridge = process.env.TERMINAL_BRIDGE ?? "http://127.0.0.1:7991";

export default defineConfig({
  plugins: [svelte()],
  // @nestris-ltm/nes is linked from ../nestris-ltm: use one Svelte runtime.
  resolve: { dedupe: ["svelte"] },
  build: { outDir, emptyOutDir: true, sourcemap: false },
  server: {
    port: 5175,
    proxy: {
      "/api": bridge,
      "/local": bridge,
      "/ws": { target: bridge, ws: true },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
