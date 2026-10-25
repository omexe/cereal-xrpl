import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
const fixture = JSON.parse(readFileSync(new URL('../src/fixtures/deployment.json', import.meta.url), 'utf8'));
import { startResearch, advanceResearch } from '../src/researchDemo';
import type { Workspace } from '../src/wallets';

test('live Settings opens JSON test wallets and chat without touching live data', async ({ page, context }) => {
  test.setTimeout(45000);
  const apiCalls: string[] = [];
  const sandboxApiCalls: string[] = [];
  await context.route('**/api/**', route => {
    apiCalls.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    if (/\/(test-wallets|fixture-chat)/.test(route.request().frame().url())) sandboxApiCalls.push(route.request().url());
    return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"offline test"}' });
  });
  await page.goto('/');
  await page.evaluate(() => localStorage.setItem('cereal-demo-v1', 'existing demo data'));
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Open test chat' })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('cereal-test-v1'))).toBeNull();

  await page.getByText('Offline fixtures', { exact: true }).click();
  const [wallets] = await Promise.all([
    context.waitForEvent('page'), page.getByRole('link', { name: 'Open test wallets' }).click(),
  ]);
  await wallets.waitForURL('**/test-wallets');
  for (const name of ['XRP research', 'Review every payment', 'Small budget', 'Restricted sources'])
    await expect(wallets.getByRole('button', { name: `Open ${name}`, exact: true })).toBeVisible();
  await expect.poll(() => wallets.evaluate(() => JSON.parse(localStorage.getItem('cereal-test-v1')!).wallets.length)).toBe(4);
  const state = await wallets.evaluate(() => JSON.parse(localStorage.getItem('cereal-test-v1')!));
  expect(state.wallets.map((w: { balance: number }) => w.balance)).toEqual([20, 20, 3, 20]);
  expect(state.wallets.every((w: { transactions: unknown[]; live?: unknown }) => w.transactions.length === 0 && !w.live)).toBe(true);
  const createdAt = state.wallets[0].createdAt;
  await wallets.getByRole('button', { name: 'Open XRP research', exact: true }).click();

  const [chat] = await Promise.all([
    context.waitForEvent('page'), page.getByRole('link', { name: 'Open fixture chat' }).click(),
  ]);
  await chat.waitForURL('**/fixture-chat');
  await chat.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(wallets.getByRole('button', { name: 'Approve $7.50', exact: true })).toBeVisible({ timeout: 18000 });
  await expect(chat.getByRole('link', { name: 'Review payment in Cereal' })).toHaveAttribute('href', '/test-wallets?wallet=test-xrp-research');
  await wallets.getByRole('button', { name: 'Approve $7.50', exact: true }).click();
  await expect(chat.getByRole('heading', { name: 'Your XRPL research brief is ready.' })).toBeVisible({ timeout: 12000 });
  await expect(wallets.locator('.budget-used')).toHaveText('$9.35 / $20.00');
  await expect(wallets.getByText('Blocked', { exact: true })).toBeVisible();
  await wallets.reload();
  await wallets.getByRole('button', { name: 'Open XRP research', exact: true }).click();
  await expect(wallets.locator('.budget-used')).toHaveText('$9.35 / $20.00');
  expect(await wallets.evaluate(() => JSON.parse(localStorage.getItem('cereal-test-v1')!).wallets[0].createdAt)).toBe(createdAt);
  await wallets.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(wallets.getByRole('link', { name: 'Open test chat' })).toHaveAttribute('href', '/fixture-chat');
  expect(await page.evaluate(() => localStorage.getItem('cereal-demo-v1'))).toBe('existing demo data');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Open XRP research', exact: true })).toHaveCount(0);
  expect(apiCalls.every(call => call.startsWith('GET '))).toBe(true);
  expect(sandboxApiCalls).toEqual([]);
});

for (const scenario of [
  { name: 'XRP research', status: 'waiting', paid: 1.2, pending: 7.5 },
  { name: 'Review every payment', status: 'waiting', paid: 0, pending: 1.2 },
  { name: 'Small budget', status: 'complete', paid: 1.85, pending: undefined },
  { name: 'Restricted sources', status: 'complete', paid: 1.2, pending: undefined },
]) test(`JSON fixture exercises ${scenario.name}`, () => {
  const now = Date.now();
  const state: Workspace = structuredClone(fixture);
  state.wallets.forEach(wallet => wallet.createdAt = new Date(now).toISOString());
  const wallet = state.wallets.find(wallet => wallet.name === scenario.name)!;
  const runId = startResearch(state, wallet.id, `Research XRPL. Use my ${wallet.name} wallet.`, now);
  for (let i = 1; i <= 10; i++) {
    advanceResearch(state, runId, now + i * 10000);
    if (state.researchRuns![0].status === 'waiting') break;
  }
  expect(state.researchRuns![0].status).toBe(scenario.status);
  expect((wallet.transactions ?? []).reduce((sum, tx) => sum + tx.amount, 0)).toBeCloseTo(scenario.paid);
  expect(state.demoPayments?.find(payment => payment.status === 'pending')?.amount).toBe(scenario.pending);
  expect(state.demoPayments?.some(payment => payment.sourceId === 'fraud' && payment.status === 'paid')).toBe(false);
});
