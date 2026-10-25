import { defineConfig } from '@playwright/test';

// The original suite: browser-only mock data (VITE_CEREAL_MODE=mock). Live specs (tests/live-*.spec.ts) use
// playwright.live.config.ts.
// CEREAL_MOCK_UI_PORT keeps parallel checkouts from reusing each other's dev server.
const port = Number(process.env.CEREAL_MOCK_UI_PORT ?? 5179);

export default defineConfig({
  testDir: './tests',
  testIgnore: /live-.*\.spec\.ts/,
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1440, height: 960 } },
  webServer: { command: `npm run dev -- --port ${port}`, url: `http://127.0.0.1:${port}`, env: { VITE_CEREAL_MODE: 'mock' }, reuseExistingServer: false },
});
