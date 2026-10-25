import { defineConfig } from '@playwright/test';

// The original suite: browser-only mock data (VITE_CEREAL_MODE=mock). Live specs (tests/live-*.spec.ts) use
// playwright.live.config.ts.
export default defineConfig({
  testDir: './tests',
  testIgnore: /live-.*\.spec\.ts/,
  use: { baseURL: 'http://127.0.0.1:5179', viewport: { width: 1440, height: 960 } },
  webServer: { command: 'npm run dev -- --port 5179', url: 'http://127.0.0.1:5179', env: { VITE_CEREAL_MODE: 'mock' }, reuseExistingServer: !process.env.CI },
});
