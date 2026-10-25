import { defineConfig } from '@playwright/test';

// Live specs against a real cereal service on XRPL testnet. They spend testnet RLUSD: run them under the machine-wide
// lock so parallel runs take turns on the shared treasury and Speculos device:
//   ../.venv/bin/python ../scripts/with_testnet_lock.py -- npx playwright test -c playwright.live.config.ts tests/live-x.spec.ts
// By default this starts a private service (sweeper off, deterministic parser, its own record file) on
// CEREAL_E2E_PORT and the app on CEREAL_E2E_UI_PORT. Set CEREAL_API to test an already-running service instead.
const servicePort = Number(process.env.CEREAL_E2E_PORT ?? 8101);
const uiPort = Number(process.env.CEREAL_E2E_UI_PORT ?? 5181);
const external = process.env.CEREAL_API;
const api = external ?? `http://127.0.0.1:${servicePort}`;

export default defineConfig({
  testDir: './tests',
  testMatch: /live-.*\.spec\.ts/,
  workers: 1,
  timeout: 15 * 60_000,
  expect: { timeout: 3 * 60_000 },
  use: { baseURL: `http://127.0.0.1:${uiPort}`, viewport: { width: 1440, height: 960 }, trace: 'retain-on-failure' },
  webServer: [
    ...(external ? [] : [{
      command: `.venv/bin/uvicorn cereal.service:app --host 127.0.0.1 --port ${servicePort}`, cwd: '..', url: `${api}/health`,
      env: { CEREAL_SWEEPER: '0', CEREAL_LLM: process.env.CEREAL_LLM ?? 'off', CEREAL_SERVICE_URL: api,
        CEREAL_DEPLOYMENTS_FILE: process.env.CEREAL_DEPLOYMENTS_FILE ?? 'deployments.e2e.json' },
      reuseExistingServer: false, timeout: 120_000, stdout: 'pipe' as const, stderr: 'pipe' as const,
    }]),
    { command: `npm run dev -- --port ${uiPort}`, url: `http://127.0.0.1:${uiPort}`,
      env: { CEREAL_API: api, VITE_CEREAL_MODE: 'live' }, reuseExistingServer: false, timeout: 60_000 },
  ],
});
