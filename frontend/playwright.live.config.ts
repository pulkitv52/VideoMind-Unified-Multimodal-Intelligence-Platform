import { defineConfig } from "@playwright/test";

// Explicitly invoked after operator provisioning; no API mocks or saved sessions.
export default defineConfig({
  testDir: "./live-tests",
  workers: 1,
  fullyParallel: false,
  timeout: 90000,
  outputDir: "../.local/role-live-browser-results",
  reporter: "line",
  use: { baseURL: "http://localhost:8080", channel: "chrome", trace: "off", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { viewport: { width: 360, height: 800 } } },
  ],
});
