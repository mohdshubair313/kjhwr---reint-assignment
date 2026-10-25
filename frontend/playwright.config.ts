import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  reporter: [['list'], ['json', { outputFile: '../artifacts/phase-4-browser-tests.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:18262',
    channel: 'chrome',
    timezoneId: 'Asia/Kolkata',
    viewport: { width: 1440, height: 1100 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    { command: 'uv run --directory ../backend python -m uvicorn main:app --host 127.0.0.1 --port 18261', url: 'http://127.0.0.1:18261/health', reuseExistingServer: !process.env.CI },
    { command: 'npm run dev -- --host 127.0.0.1 --port 18262 --strictPort', url: 'http://127.0.0.1:18262', env: { REINT_DEV_API_TARGET: 'http://127.0.0.1:18261' }, reuseExistingServer: !process.env.CI },
  ],
})
