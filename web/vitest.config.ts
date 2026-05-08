import { defineConfig } from "vitest/config";
import path from "node:path";

/**
 * Minimal vitest config. Picks up tests from `lib/__tests__/*.test.ts`.
 * No DOM is needed for current tests; default `node` env is fine.
 */
export default defineConfig({
  test: {
    include: ["lib/**/*.test.ts", "lib/**/__tests__/**/*.test.ts"],
    environment: "node",
    globals: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
