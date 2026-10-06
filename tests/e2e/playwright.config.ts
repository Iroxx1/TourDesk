import { defineConfig, devices } from "@playwright/test";

// The servers (API + worker) are started by scripts/run-e2e.sh against a dedicated database.
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts/,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "./test-results",
  use: {
    baseURL: process.env.TOURDESK_E2E_URL ?? "http://127.0.0.1:8090",
    locale: "de-DE",
    timezoneId: "Europe/Berlin",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "journey", testMatch: /tourdesk\.spec\.ts/, use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    // the layout checks log in as the user created by the journey, so they run after it; with
    // real scrollbars like a desktop browser (Playwright hides them in headless mode by default)
    {
      name: "layout",
      testMatch: /layout\.spec\.ts/,
      dependencies: ["journey"],
      use: { ...devices["Desktop Chrome"], launchOptions: { ignoreDefaultArgs: ["--hide-scrollbars"] } },
    },
  ],
});
