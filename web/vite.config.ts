import { defineConfig } from "vitest/config";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig(({ mode }) => ({
  plugins: [svelte()],
  build: { outDir: "../src/fatball/api/static", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://localhost:8080",
      "/media": "http://localhost:8080",
    },
  },
  resolve: mode === "test" ? { conditions: ["browser"] } : undefined,
  test: { environment: "jsdom", include: ["tests/**/*.test.ts"] },
}));
