import { test, expect, type Page } from '@playwright/test';

test.setTimeout(45000);
async function createResearch(page: Page, budget = '20', sweep = false) {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Settings', exact: true })).toBeVisible();
  await page.evaluate(({ budget, sweep }) => {
    const state = JSON.parse(localStorage.getItem('cereal-demo-v1')!);
    state.wallets.push({ id: 'existing-wallet', name: 'Apollo Research', mockDataVersion: 1,
      balance: 20, archived: false, createdAt: new Date().toISOString(),
      transactions: [{ id: 'prior-payment', title: 'Existing research purchase', merchant: 'Ledger Lens', amount: 2, durationSeconds: 3, timestamp: new Date().toISOString() }],
      constraints: { spend: Number(budget), days: 2, approval: 5, sweep, merchants: ['Ledger Lens', 'Venture Atlas', 'Open Ledger Index'] } });
    localStorage.setItem('cereal-demo-v1', JSON.stringify(state));
  }, { budget, sweep });
  await page.goto('/?wallet=existing-wallet');
  await expect(page.locator('.activity-illustration')).toBeVisible();
  await expect(page.getByText('Existing research purchase', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open demo chat' })).toHaveCount(0);
  return '/demo-chat';
}
async function startChat(chat: Page) {
  await chat.getByRole('textbox', { name: 'Research prompt' }).fill('Research XRPL. Use my Apollo Research wallet for payments.');
  await chat.getByRole('button', { name: 'Start research', exact: true }).click();
}
async function resetFromSettings(page: Page) {
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByText('Demo scenario & replay', { exact: true }).click();
  await page.getByLabel('Wallet activity to reset').selectOption('existing-wallet');
  await page.getByRole('button', { name: 'Reset research session', exact: true }).click();
  await page.getByRole('button', { name: 'Confirm reset', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('status')).toContainText('Research session reset.');
  await page.getByRole('button', { name: 'Close dialog' }).click();
}
async function waitForApproval(chat: Page, owner: Page) {
  await expect(chat.getByText('Cereal needs your permission', { exact: true })).toBeVisible({ timeout: 20000 });
  await expect(owner.getByRole('button', { name: 'Approve $7.50', exact: true })).toBeVisible();
}
async function readState(page: Page) {
  return page.evaluate(() => JSON.parse(localStorage.getItem('cereal-demo-v1')!));
}

test('wallet-first setup, two-window approval, reload recovery, no duplicate charges, and owner reset', async ({ page, context }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  const href = await createResearch(page);
  const chat = await context.newPage(); chat.on('pageerror', error => errors.push(error.message));
  await chat.goto(href!);
  await startChat(chat);
  await waitForApproval(chat, page);
  await expect(page.getByText('Allowed automatically', { exact: true })).toBeVisible();
  await expect(page.getByText('Blocked', { exact: true })).toBeVisible();
  const before = await readState(page);
  const researchWallet = before.wallets.find((wallet: { id: string }) => wallet.id === 'existing-wallet');
  expect(researchWallet.balance).toBe(18.8); expect(researchWallet.transactions).toHaveLength(2);
  await chat.reload(); await waitForApproval(chat, page);
  await expect(chat.getByRole('textbox', { name: 'Research prompt' })).toHaveValue('');
  // Two concurrent chat windows advance the same durable run without repeating payments.
  const duplicate = await context.newPage(); await duplicate.goto(`/demo-chat?run=${before.researchRuns[0].id}`);
  await page.getByRole('button', { name: 'Approve $7.50', exact: true }).click();
  await expect(chat.getByRole('heading', { name: 'Your XRPL research brief is ready.' })).toBeVisible({ timeout: 15000 });
  await expect(duplicate.getByRole('heading', { name: 'Your XRPL research brief is ready.' })).toBeVisible();
  await expect(page.locator('.budget-used')).toHaveText('$11.35 / $20.00');
  await expect(page.getByText('Approved by you', { exact: true })).toBeVisible();
  const after = await readState(chat);
  const wallet = after.wallets.find((item: { id: string }) => item.id === researchWallet.id);
  expect(wallet.balance).toBe(10.65); expect(wallet.transactions).toHaveLength(4);
  expect(after.demoPayments).toHaveLength(4); expect(wallet.constraints).toEqual(researchWallet.constraints);
  expect(after.demoPayments.find((payment: { sourceId: string }) => payment.sourceId === 'fraud').status).toBe('blocked');
  await resetFromSettings(page);
  await expect(page.locator('.budget-used')).toHaveText('$2.00 / $20.00');
  await expect(chat.getByRole('heading', { name: 'Curiosity, with a budget.' })).toBeVisible();
  await expect(chat.getByRole('button', { name: 'Start research', exact: true })).toBeEnabled();
  const reset = await readState(page);
  expect(reset.wallets.find((item: { id: string }) => item.id === wallet.id).transactions.map((item: { id: string }) => item.id)).toEqual(['prior-payment']);
  expect(reset.wallets.filter((item: { id: string }) => item.id !== wallet.id)).toEqual(before.wallets.filter((item: { id: string }) => item.id !== wallet.id));
  expect(errors).toEqual([]);
});

test('owner denial resumes research without charging the premium report', async ({ page, context }) => {
  const href = await createResearch(page); const chat = await context.newPage(); await chat.goto(href!);
  await startChat(chat);
  await waitForApproval(chat, page);
  await page.getByRole('button', { name: 'Deny payment', exact: true }).click();
  await expect(chat.getByRole('heading', { name: 'Your XRPL research brief is ready.' })).toBeVisible({ timeout: 15000 });
  await expect(chat.getByText('The premium founders and funding report was not purchased.', { exact: false })).toBeVisible();
  await expect(page.locator('.budget-used')).toHaveText('$3.85 / $20.00');
  const state = await readState(page);
  expect(state.wallets.find((item: { id: string }) => item.id === 'existing-wallet').balance).toBe(18.15);
});

test('Cereal policy edits take effect in the waiting chat and cannot be bypassed by approval', async ({ page, context }) => {
  const href = await createResearch(page); const chat = await context.newPage(); await chat.goto(href!);
  await startChat(chat); await waitForApproval(chat, page);
  await page.getByRole('button', { name: '$20', exact: true }).click();
  await page.getByRole('button', { name: 'Edit the fields instead' }).click();
  await page.getByLabel('Spend limit ($)', { exact: true }).fill('4');
  await page.getByRole('button', { name: 'Save constraints', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Approve $7.50', exact: true })).toHaveCount(0);
  await expect(chat.getByRole('heading', { name: 'Your XRPL research brief is ready.' })).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.budget-used')).toHaveText('$3.85 / $4.00');
  const state = await readState(page);
  expect(state.demoPayments.find((payment: { sourceId: string }) => payment.sourceId === 'funding').code).toBe('budget_exceeded');
});

test('missing wallet is actionable, and mobile chat has no overflow or unreachable composer', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/demo-chat');
  await page.getByRole('textbox', { name: 'Research prompt' }).fill('Research XRPL.');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByText('Which Cereal wallet should I use for payments?', { exact: false })).toBeVisible();
  expect((await readState(page)).researchRuns ?? []).toEqual([]);
  await expect(page.getByRole('textbox', { name: 'Research prompt' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const box = await page.locator('.chat-composer').boundingBox(); expect(box!.y + box!.height).toBeLessThanOrEqual(844);
  await page.getByRole('button', { name: 'Toggle chat navigation' }).click();
  await expect(page.getByRole('complementary', { name: 'Chat navigation' })).toBeVisible();
});

test('stopping research cancels pending approval; optional sweep returns funds on completion', async ({ page, context }) => {
  const href = await createResearch(page, '20', true); const chat = await context.newPage(); await chat.goto(href!);
  await startChat(chat); await waitForApproval(chat, page);
  await chat.getByRole('button', { name: 'Stop research', exact: true }).click();
  await expect(chat.getByRole('heading', { name: 'Your progress is saved.' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve $7.50', exact: true })).toHaveCount(0);
  expect((await readState(page)).demoPayments.find((payment: { sourceId: string }) => payment.sourceId === 'funding').status).toBe('cancelled');
  // Reset makes the same owner-created wallet ready for a clean presentation.
  await resetFromSettings(page);
  await expect(chat.getByRole('button', { name: 'Start research', exact: true })).toBeEnabled();
  await startChat(chat); await waitForApproval(chat, page);
  await page.getByRole('button', { name: 'Approve $7.50', exact: true }).click();
  await expect(page.getByText('$10.65 returned to the demo treasury.', { exact: false })).toBeVisible({ timeout: 15000 });
  const wallet = (await readState(page)).wallets.find((item: { id: string }) => item.id === 'existing-wallet');
  expect(wallet.balance).toBe(0); expect(wallet.demoReturnedBalance).toBe(10.65);
});

test('storage failure cannot debit funds or falsely complete an approval', async ({ page, context }) => {
  const href = await createResearch(page); const chat = await context.newPage(); await chat.goto(href!);
  await startChat(chat); await waitForApproval(chat, page);
  await page.evaluate(() => {
    const original = Storage.prototype.setItem;
    Object.assign(window, { restoreDemoStorage: () => { Storage.prototype.setItem = original; } });
    Storage.prototype.setItem = function(key, value) {
      if (key === 'cereal-demo-v1') throw new Error('Demo storage is full. Free space and retry.');
      return original.call(this, key, value);
    };
  });
  await page.getByRole('button', { name: 'Approve $7.50', exact: true }).click();
  await expect(page.locator('.research-error')).toContainText('Demo storage is full');
  const failed = await readState(page);
  expect(failed.demoPayments.find((payment: { sourceId: string }) => payment.sourceId === 'funding').status).toBe('pending');
  expect(failed.wallets.find((wallet: { id: string }) => wallet.id === 'existing-wallet').balance).toBe(18.8);
  await page.evaluate(() => (window as unknown as { restoreDemoStorage: () => void }).restoreDemoStorage());
  await page.getByRole('button', { name: 'Approve $7.50', exact: true }).click();
  await expect(chat.getByRole('heading', { name: 'Your XRPL research brief is ready.' })).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.budget-used')).toHaveText('$11.35 / $20.00');
});

test('demo tools live only in settings; legacy research wallets retain the standard layout and data', async ({ page }) => {
  await createResearch(page);
  await page.evaluate(() => {
    const state = JSON.parse(localStorage.getItem('cereal-demo-v1')!);
    state.wallets.find((item: { id: string }) => item.id === 'existing-wallet').demoPurpose = 'research';
    localStorage.setItem('cereal-demo-v1', JSON.stringify(state));
  });
  await page.reload();
  await expect(page.locator('.activity-illustration')).toBeVisible();
  await expect(page.getByText('Existing research purchase', { exact: true })).toBeVisible();
  await expect(page.getByText('Demo activity', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Research demo', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Open demo chat' })).toHaveCount(0);
  const state = await readState(page);
  expect(state.wallets.find((item: { id: string }) => item.id === 'existing-wallet').demoPurpose).toBeUndefined();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Developer tools' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open demo chat' })).toHaveAttribute('href', '/demo-chat');
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await page.getByRole('button', { name: 'New Wallet', exact: true }).click();
  await expect(page.getByLabel('Use for the research chat demo')).toHaveCount(0);
  await page.goto('/?setup=research');
  await expect(page.getByRole('dialog', { name: 'Workspace settings' })).toBeVisible();
});

test('duplicate names require an explicit choice before any request is created', async ({ page }) => {
  await createResearch(page);
  await page.evaluate(() => {
    const state = JSON.parse(localStorage.getItem('cereal-demo-v1')!);
    state.wallets.push({ ...state.wallets.find((item: { id: string }) => item.id === 'existing-wallet'), id: 'duplicate-wallet', balance: 50 });
    localStorage.setItem('cereal-demo-v1', JSON.stringify(state));
  });
  await page.goto('/demo-chat');
  await startChat(page);
  await expect(page.getByText('Which wallet should I use for payments?', { exact: false })).toBeVisible();
  expect((await readState(page)).researchRuns ?? []).toEqual([]);
  await page.getByRole('button', { name: /Apollo Research.*\$50.00/ }).click();
  await expect(page.getByRole('button', { name: 'Stop research' })).toBeVisible();
  const state = await readState(page);
  expect(state.researchRuns[0].walletId).toBe('duplicate-wallet');
  expect(state.wallets.find((item: { id: string }) => item.id === 'existing-wallet').balance).toBe(20);
});
