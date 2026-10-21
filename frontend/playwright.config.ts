import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  outputDir: "../.local/ux-browser-tests",
  reporter: "line",
  use: { baseURL: "http://127.0.0.1:4174", channel: "chrome", trace: "off", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { viewport: { width: 360, height: 800 } } },
  ],
  webServer: { command: "pnpm dev --port 4174", url: "http://127.0.0.1:4174", reuseExistingServer: false },
});
