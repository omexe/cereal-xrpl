import { defineConfig } from '@playwright/test';

// Exercises sandbox entry points in the default live build. All API requests are intercepted;
// no backend, keys, device, or testnet transactions are needed.
const port = Number(process.env.CEREAL_SANDBOX_UI_PORT ?? 5188);
export default defineConfig({
  testDir: './tests', testMatch: /sandbox-.*\.spec\.ts/,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1440, height: 960 } },
  webServer: { command: `npm run dev -- --port ${port}`, url: `http://127.0.0.1:${port}`,
    env: { VITE_CEREAL_MODE: 'live' }, reuseExistingServer: false },
});
