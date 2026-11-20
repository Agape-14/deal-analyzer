const { defineConfig, devices } = require('@playwright/test');
const diagnostic = process.env.BROWSER_DIAGNOSTIC === '1';

module.exports = defineConfig({
  testDir: './browser-tests',
  globalSetup: './browser-tests/setup.cjs',
  timeout: diagnostic ? 90000 : 45000,
  expect: { timeout: diagnostic ? 20000 : 10000 },
  outputDir: diagnostic ? 'diagnostics/test-results' : 'test-results',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: diagnostic ? 'diagnostics/playwright-report' : 'playwright-report' }], ['junit', { outputFile: diagnostic ? 'diagnostics/browser-results.xml' : 'test-results/browser-results.xml' }]],
  use: {
    baseURL: 'http://127.0.0.1:3000',
    storageState: '.browser-auth/admin.json',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    serviceWorkers: 'block',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } }],
  webServer: [
    { command: 'python ../scripts/browser_test_server.py', url: 'http://127.0.0.1:8000/api/healthz',
      env: { BROWSER_TEST_MODE: 'synthetic' }, reuseExistingServer: false, timeout: 90000 },
    { command: `npm run ${diagnostic ? 'dev' : 'start'} -- --hostname 127.0.0.1 --port 3000`, url: 'http://127.0.0.1:3000/login',
      env: { FASTAPI_URL: 'http://127.0.0.1:8000' }, reuseExistingServer: false, timeout: 90000 },
  ],
});
