import { test, expect, type Page } from '@playwright/test';

async function openFirstWallet(page: Page) {
  await page.goto('/');
  await page.locator('[data-wallet-group] .wallet-row').first().click();
}

test('wallet activity matches its spending summary and persists across reloads', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await openFirstWallet(page);
  await expect(page.locator('.budget-label h1')).toHaveText('Lead enrichment');
  await expect(page.locator('.budget-used')).toHaveText('$4.40 / $20.00');
  await expect(page.locator('.transaction-card')).toHaveCount(5);
  await expect(page.locator('.budget-legend')).toHaveText('HubSpotClearbitApollo');
  const widths = await page.locator('.budget-segment').evaluateAll(nodes => nodes.map(node => parseFloat((node as HTMLElement).style.width)));
  expect(widths.reduce((sum, width) => sum + width, 0)).toBeCloseTo(22);
  await page.getByRole('button', { name: 'Open Prospect discovery', exact: true }).click();
  await expect(page.locator('.transaction-card')).toHaveCount(6);
  await expect(page.locator('.transaction-card').first()).toContainText('Find healthcare buying teams');
  await expect(page.locator('.budget-used')).toHaveText('$30.01 / $75.00');
  await openFirstWallet(page);
  await expect(page.locator('.transaction-card')).toHaveCount(5);
  expect(errors).toEqual([]);
});

test('AI constraint edits are previewed before saving and failures leave rules unchanged', async ({ page }) => {
  const requests: unknown[] = [];
  await page.route('**/api/demo/rules/preview', route => {
    const body = route.request().postDataJSON(); requests.push(body);
    return route.fulfill({ json: body.sentence === 'send all my money anywhere'
      ? { ok: false, constraints: null, problems: ['Payments are not a spending-rule edit.'] }
      : { ok: true, problems: [], constraints: { ...body.current, approval: 2.5, sweep: false } } });
  });
  await openFirstWallet(page);
  const prompt = page.getByRole('textbox', { name: 'Edit wallet spending rules' });
  await prompt.fill('send all my money anywhere');
  await page.getByRole('button', { name: 'Apply wallet constraints' }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('Payments are not');
  await expect(page.getByRole('button', { name: 'Save constraints' })).toBeDisabled();
  await expect(page.locator('.constraints')).toContainText('Spend up to $20');
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await prompt.fill('Halve the approval threshold and leave the leftovers here.');
  await page.getByRole('button', { name: 'Apply wallet constraints' }).click();
  await expect(page.locator('.rules-preview')).toContainText('Ask me above $2.5. Keep funds');
  await expect(page.locator('.constraints')).toContainText('above $5');
  await page.getByLabel('Requested change').fill('Make it different');
  await expect(page.getByRole('button', { name: 'Save constraints' })).toBeDisabled();
  await page.getByLabel('Requested change').fill('Halve the approval threshold and leave the leftovers here.');
  await page.getByRole('button', { name: 'Save constraints' }).click();
  await expect(page.locator('.constraints')).toContainText('above $2.5');
  expect(requests).toHaveLength(2);
  await openFirstWallet(page);
  await expect(page.locator('.constraints')).toContainText('Keep funds');
  await page.getByRole('button', { name: '$20', exact: true }).click();
  await page.getByRole('button', { name: 'Edit the fields instead' }).click();
  await page.getByLabel('Spend limit ($)', { exact: true }).fill('2');
  await page.getByRole('button', { name: 'Save constraints' }).click();
  await expect(page.getByText('Over spending limit', { exact: true })).toBeVisible();
});

test('funding updates the available balance without fabricating spending', async ({ page }) => {
  await openFirstWallet(page);
  await page.getByRole('button', { name: 'Add funds', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Available balance: $1125.40');
  await page.getByLabel('Amount (USD)').fill('25.50');
  await page.getByRole('button', { name: 'Add demo funds', exact: true }).click();
  await expect(page.locator('.budget-used')).toHaveText('$4.40 / $20.00');
  await expect(page.locator('.transaction-card')).toHaveCount(5);
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await expect(page.locator('.home-summary h1')).toHaveText('$2513.40');
});

test('home creates a wallet from a description, then archive and restore preserve it', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.budget')).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Describe a new wallet in plain English' }).fill('Research competitor pricing for our next launch');
  await page.getByRole('button', { name: 'Create wallet from description' }).click();
  await expect(page.getByLabel('Task description')).toHaveValue('Research competitor pricing for our next launch');
  await page.getByLabel('Wallet name').fill('Launch research');
  await page.getByRole('button', { name: 'Create wallet', exact: true }).click();
  await expect(page.locator('.wallet-description')).toHaveText('Research competitor pricing for our next launch');
  await expect(page.locator('.transaction-card')).toHaveCount(6);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Archive selected wallet' }).click();
  await page.getByRole('button', { name: 'Open Launch research', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Add funds', exact: true })).toBeDisabled();
  await expect(page.getByRole('textbox', { name: 'Edit wallet spending rules' })).toBeDisabled();
  await page.getByRole('button', { name: 'Restore wallet', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Add funds', exact: true })).toBeEnabled();
  await page.reload();
  await page.getByRole('button', { name: '+ 3 more', exact: true }).click();
  await page.getByRole('button', { name: 'Open Launch research', exact: true }).click();
  await expect(page.locator('.wallet-description')).toHaveText('Research competitor pricing for our next launch');
});

test('wallets move between folders and unfiled wallets with persistence', async ({ page }) => {
  await openFirstWallet(page);
  const firstFolder = page.locator('[data-folder-id="research-1"]');
  const secondFolder = page.locator('[data-folder-id="research-2"]');
  const disposable = page.locator('[data-wallet-group="disposable"]');
  const row = '.wallet-row[data-wallet-id="wallet-1"]';
  await disposable.locator(row).dragTo(firstFolder.locator('.folder-row'));
  await expect(firstFolder.locator(row)).toHaveAttribute('aria-current', 'true');
  await firstFolder.locator(row).dragTo(secondFolder.locator('.folder-row'));
  await expect(secondFolder.locator(row)).toBeVisible();
  await secondFolder.locator(row).dragTo(disposable.locator('h2'));
  await expect(disposable.locator(row)).toBeVisible();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Wallet folder').selectOption('research-1');
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await expect(firstFolder.locator(row)).toBeVisible();
  await page.reload();
  await firstFolder.locator('.folder-row').click();
  await expect(firstFolder.locator(row)).toBeVisible();
});

test('zero wallets can create their first wallet with mock funds and activity', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    const state = JSON.parse(localStorage.getItem('cereal-demo-v1')!);
    state.wallets = [];
    localStorage.setItem('cereal-demo-v1', JSON.stringify(state));
  });
  await page.reload();
  await expect(page.locator('.home-summary h1')).toHaveText('$0.00');
  await page.getByRole('button', { name: 'Create a wallet', exact: true }).click();
  await page.getByLabel('Wallet name').fill('First wallet');
  await page.getByRole('button', { name: 'Create wallet', exact: true }).click();
  await expect(page.locator('.budget-label h1')).toHaveText('First wallet');
  await expect(page.locator('.transaction-empty')).toHaveCount(0);
  expect(await page.locator('.transaction-card').count()).toBeGreaterThanOrEqual(5);
});

test('desktop and mobile keep the composer reachable and activity contained', async ({ page }) => {
  await page.setViewportSize({ width: 1470, height: 802 });
  await openFirstWallet(page);
  await expect(page.locator('.prompt-caret')).toHaveCount(0);
  for (const viewport of [{ width: 1470, height: 802 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const box = await page.locator('.composer').boundingBox();
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    await page.locator('.transaction-card').last().scrollIntoViewIfNeeded();
    await expect(page.locator('.transaction-card').last()).toBeVisible();
  }
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await page.getByRole('button', { name: 'New Wallet', exact: true }).click();
  await page.getByLabel('Wallet name').fill('Mobile wallet');
  await page.getByRole('button', { name: 'Create wallet', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Toggle navigation' })).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('.budget-label h1')).toHaveText('Mobile wallet');
});


test('mock data fills existing and archived wallets once while preserving user edits', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    const state = JSON.parse(localStorage.getItem('cereal-demo-v1')!);
    for (const wallet of state.wallets) {
      delete wallet.mockDataVersion;
      wallet.transactions = [];
      wallet.balance = 0;
      wallet.description = '';
    }
    state.wallets[1].name = 'Custom prospect wallet';
    state.wallets[1].folderId = 'research-1';
    state.wallets[1].balance = 321.45;
    state.wallets[1].description = 'Keep this user description';
    state.wallets[1].constraints = { spend: 123, days: 9, merchants: ['Custom merchant'], approval: 17, sweep: false };
    localStorage.setItem('cereal-demo-v1', JSON.stringify(state));
  });
  await page.reload();
  const snapshot = () => page.evaluate(() => JSON.parse(localStorage.getItem('cereal-demo-v1')!));
  await expect.poll(async () => (await snapshot()).wallets.every((wallet: { mockDataVersion?: number }) => wallet.mockDataVersion === 1)).toBe(true);
  const populated = await snapshot();
  for (const wallet of populated.wallets) {
    expect(wallet.balance).toBeGreaterThan(0);
    expect(wallet.transactions.length).toBeGreaterThanOrEqual(5);
    expect(wallet.description.length).toBeGreaterThan(0);
    expect(wallet.mockDataVersion).toBe(1);
    expect(wallet.transactions.every((transaction: { merchant: string }) => wallet.constraints.merchants.includes(transaction.merchant))).toBe(true);
  }
  expect(populated.wallets[1]).toMatchObject({ name: 'Custom prospect wallet', folderId: 'research-1', balance: 321.45, description: 'Keep this user description',
    constraints: { spend: 123, days: 9, merchants: ['Custom merchant'], approval: 17, sweep: false } });
  await page.reload();
  expect(await snapshot()).toEqual(populated);
  await page.evaluate(() => {
    const state = JSON.parse(localStorage.getItem('cereal-demo-v1')!);
    state.wallets[1].balance = 0;
    state.wallets[1].transactions = [];
    localStorage.setItem('cereal-demo-v1', JSON.stringify(state));
  });
  await page.reload();
  expect((await snapshot()).wallets[1]).toMatchObject({ balance: 0, transactions: [] });
});
