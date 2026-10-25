import { test, expect } from '@playwright/test';

// Read-only: the live app shows the main wallet and the wallet list from the cereal service; nothing is seeded.
test('live home and wallet list come from the cereal service', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const main = await (await request.get('/api/main')).json();
  const wallets = await (await request.get('/api/subagents')).json();
  await page.goto('/');
  await expect(page.locator('.home-summary h1')).toContainText('RLUSD');
  await expect(page.locator('.home-summary p')).toContainText('Main wallet on XRPL testnet');
  expect(Number(main.rlusd)).toBeGreaterThanOrEqual(0);
  const shown = wallets.filter((w: { archived?: boolean }) => !w.archived);
  const running = shown.filter((w: { status: string }) => ['active', 'deploying'].includes(w.status));
  await expect(page.locator('[data-wallet-group] .wallet-row')).toHaveCount(Math.min(4, running.length));
  if (shown.length > Math.min(4, running.length)) {
    await page.locator('.wallet-more').click();
    await expect(page.locator('[data-wallet-group] .wallet-row')).toHaveCount(shown.length);
  }
  await expect(page.locator('.transaction-card')).toHaveCount(0);
  if (wallets.length) {
    await page.locator('[data-wallet-group] .wallet-row').first().click();
    await expect(page.locator('.budget-used')).toContainText('RLUSD');
    await expect(page.locator('.constraints')).toContainText('RLUSD');
  }
  expect(errors).toEqual([]);
});
