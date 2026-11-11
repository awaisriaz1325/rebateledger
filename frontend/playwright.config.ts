import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end journeys against the real stack: Postgres/Redis/Mailpit (`make up`),
 * the API + worker on :8100 and a production build of the web app on :3100.
 * Ports differ from the dev servers so a running `make api`/`make web` is untouched.
 */
const WEB = "http://localhost:3100";
const API_ORIGIN = "http://127.0.0.1:8100";

export default defineConfig({
  testDir: "./e2e",
  // Journeys share one tenant and TOTP codes are single-use per 30 s step: run serially.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: WEB,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /global\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.state/owner.json" },
      dependencies: ["setup"],
      testMatch: /.*\.spec\.ts/,
    },
  ],
  webServer: [
    {
      command: "make -C .. e2e-api",
      url: `${API_ORIGIN}/healthz`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: "pnpm build && pnpm start -p 3100",
      url: `${WEB}/login`,
      env: { RL_API_ORIGIN: API_ORIGIN },
      reuseExistingServer: !process.env.CI,
      timeout: 300_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
