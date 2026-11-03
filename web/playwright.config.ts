import { defineConfig, devices } from "@playwright/test";

const CI = !!process.env.CI;

// One seeded service per state, each with its own data folder: the busy day (the default), a quiet
// day, and a quiet day with a camera problem. See scripts/e2e_server.py.
const server = (port: number, dir: string, flags = "") => ({
  command: `uv run python ../scripts/e2e_server.py --data-dir ../${dir} --port ${port} ${flags}`.trim(),
  url: `http://127.0.0.1:${port}/api/status`,
  reuseExistingServer: false,
  timeout: 120_000,
});

export default defineConfig({
  testDir: "tests/e2e",
  workers: 1,
  retries: CI ? 1 : 0,
  reporter: CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://127.0.0.1:8765",
    serviceWorkers: "block",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "webkit-ipad", use: { ...devices["iPad (gen 7)"] } },
    { name: "mobile-chrome", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    server(8765, ".e2e-data"),
    server(8766, ".e2e-data-empty", "--empty"),
    server(8767, ".e2e-data-problem", "--empty --camera-problem"),
  ],
});
