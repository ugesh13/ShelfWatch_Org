import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: 'list',
  use: {
    ...devices['Desktop Chrome'],
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    baseURL: 'http://127.0.0.1:3041',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: `${process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python'} -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8041`,
      url: 'http://127.0.0.1:8041/api/health',
      env: { SHELFWATCH_DB: ':memory:' },
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 3041 --strictPort',
      url: 'http://127.0.0.1:3041',
      env: { SHELFWATCH_API_TARGET: 'http://127.0.0.1:8041' },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
