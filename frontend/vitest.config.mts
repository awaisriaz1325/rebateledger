import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, ".") } },
  test: {
    environment: "jsdom",
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", "e2e/**/*.spec.ts", "e2e/*.setup.ts", ".next/**"],
    setupFiles: ["./vitest.setup.ts"],
  },
});
