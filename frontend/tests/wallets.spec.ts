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

test('transactions start collapsed left of the illustration and open to push it right', async ({ page }) => {
  await page.setViewportSize({ width: 1470, height: 802 });
  await openFirstWallet(page);
  const toggle = page.getByRole('button', { name: 'Transactions', exact: true });
  const art = page.locator('.activity-illustration');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(page.locator('.transaction-card').first()).toBeHidden();
  const header = (await page.locator('.transactions > header').boundingBox())!;
  const closed = (await art.boundingBox())!;
  expect(header.x + header.width).toBeLessThanOrEqual(closed.x);
  const content = (await page.locator('.wallet-activity').boundingBox())!;
  expect(Math.abs(closed.x + closed.width / 2 - (content.x + content.width / 2))).toBeLessThanOrEqual(2);
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator('.transaction-card').first()).toBeVisible();
  // The shift animates; wait for the illustration to settle before measuring.
  await expect.poll(async () => (await art.boundingBox())!.x).toBeGreaterThan(closed.x + 100);
  await expect(async () => {
    const before = (await art.boundingBox())!.x;
    await page.waitForTimeout(100);
    expect((await art.boundingBox())!.x).toBe(before);
  }).toPass();
  const list = (await page.locator('.transaction-list').boundingBox())!;
  expect(list.x + list.width).toBeLessThanOrEqual((await art.boundingBox())!.x);
  await page.getByRole('button', { name: 'Open Prospect discovery', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Transactions', exact: true })).toHaveAttribute('aria-expanded', 'false');
});

test('the wallet graphic navigates: spheres open active wallets, the core goes home, and home navigates back', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await openFirstWallet(page);
  const map = page.locator('.activity-illustration');
  const sphere = (name: string) => map.getByRole('button', { name: new RegExp(`^${name}, wallet`) });
  await expect(map.locator('.wallet-cluster')).toHaveCount(await page.locator('.sidebar .wallet-row:not(.archived)').count());
  await expect(sphere('Lead enrichment')).toHaveAttribute('aria-pressed', 'true');
  await sphere('Prospect discovery').click();
  await expect(sphere('Prospect discovery')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.budget-label h1')).toHaveText('Prospect discovery');
  await expect(page.locator('.wallet-row[aria-current=true]')).toHaveText('Prospect discovery');
  // Keyboard reaches the same controls; focusing a sphere never scrolls the cropped frame.
  await sphere('CRM updates').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.budget-label h1')).toHaveText('CRM updates');
  expect(await map.evaluate(node => node.scrollLeft + node.scrollTop)).toBe(0);
  const core = map.getByRole('button', { name: /^Home\. Total wallet/ });
  await core.click();
  await expect(core).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.home-summary h1')).toBeVisible();
  // Home has the same map, with the core selected: its spheres open wallets too.
  const home = page.locator('.home-illustration');
  await expect(home.getByRole('button', { name: /^Home\. Total wallet/ })).toHaveAttribute('aria-pressed', 'true');
  await home.getByRole('button', { name: /^Market sizing, wallet/ }).click();
  await expect(page.locator('.budget-label h1')).toHaveText('Market sizing');
  expect(errors).toEqual([]);
});

test('navigation fades the page out and in, keeps the sphere map steady, and skips the fade under reduced motion', async ({ page }) => {
  // Count view transitions and record which layers fade.
  await page.addInitScript(() => {
    const start = document.startViewTransition?.bind(document);
    (window as unknown as { transitions: number }).transitions = 0;
    if (start) document.startViewTransition = (update => { (window as unknown as { transitions: number }).transitions++; return start(update); }) as typeof document.startViewTransition;
  });
  await page.goto('/');
  const transitions = () => page.evaluate(() => (window as unknown as { transitions: number }).transitions);
  const layer = (name: string) => page.locator(name).evaluate(node => getComputedStyle(node).viewTransitionName);
  await page.locator('[data-wallet-group] .wallet-row').first().click();
  await expect(page.locator('.budget-label h1')).toHaveText('Lead enrichment');
  expect(await transitions()).toBe(1);
  expect(await layer('.workspace-content')).toBe('page');
  expect(await layer('.activity-illustration')).toBe('sphere-map');
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await expect(page.locator('.home-summary h1')).toBeVisible();
  expect(await transitions()).toBe(2);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.locator('[data-wallet-group] .wallet-row').first().click();
  await expect(page.locator('.budget-label h1')).toHaveText('Lead enrichment');
  expect(await transitions()).toBe(2);
});

test('typing on Home forms the new wallet: blue workspace, amount and rules as typed, cancel or create', async ({ page }) => {
  await page.goto('/');
  const box = page.getByRole('textbox', { name: 'Describe a new wallet in plain English' });
  const shell = page.locator('.app-shell');
  const create = page.getByRole('button', { name: 'Create wallet', exact: true });
  await expect(page.getByRole('button', { name: 'New Wallet', exact: true })).toHaveCount(0);
  await box.pressSequentially('Create a wallet called Breakfast');
  await expect(shell).toHaveClass(/is-forming/);
  await expect(page.locator('.forming-amount')).toHaveText('$0.00');
  await expect(page.locator('.forming-caption')).toHaveText('Breakfast · New demo wallet, funded with demo money');
  await expect(create).toBeDisabled();
  await box.pressSequentially(' Customer Discovery with a budget of $20');
  await expect(page.locator('.forming-amount')).toHaveText('$20.00');
  // Only what is typed: no default duration, vendors or sweep.
  await expect(page.locator('.forming-rules')).toHaveText('Spend up to $20.');
  await expect(page.locator('.forming-missing')).toHaveText('Still needed: a time limit and vendors');
  await box.pressSequentially(' over 2 days');
  await expect(page.locator('.forming-rules')).toHaveText('Spend up to $20 over 2 days.');
  await expect(create).toBeDisabled();
  await box.pressSequentially(', only at Notion and Apollo. Ask me above $5. Keep funds when done.');
  await expect(page.locator('.forming-rules')).toHaveText('Spend up to $20 over 2 days, only at Notion and Apollo. Ask me above $5. Keep funds when done.');
  await expect(page.locator('.forming-missing')).toHaveCount(0);
  await expect(create).toBeEnabled();
  // Vendors may be typed in any case after "only at"; known ones keep their spelling, and "at most" is not a vendor.
  await box.fill('create a wallet called breakfast that has a limit of $30 over the span of 5 days, only at apollo and hubspot.');
  await expect(page.locator('.forming-rules')).toHaveText('Spend up to $30 over 5 days, only at Apollo and HubSpot.');
  await expect(create).toBeEnabled();
  await box.fill('called Lunch, spend at most $30 over 3 days');
  await expect(page.locator('.forming-rules')).toHaveText('Spend up to $30 over 3 days.');
  await expect(page.locator('.forming-missing')).toHaveText('Still needed: vendors');
  // Escape and Cancel both return to Home with nothing created.
  await box.press('Escape');
  await expect(shell).not.toHaveClass(/is-forming/);
  await expect(box).toHaveValue('');
  await box.fill('called Scratch with $9');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.locator('.home-summary h1')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Open Scratch', exact: true })).toHaveCount(0);
  // Create makes exactly the wallet on screen and opens it.
  await box.fill('Create a wallet called Breakfast Customer Discovery with a budget of $20 over 2 days, only at Notion and Apollo. Ask me above $5.');
  await create.click();
  await expect(page.locator('.budget-label h1')).toHaveText('Breakfast Customer Discovery');
  await expect(page.locator('.constraints')).toHaveText('Spend up to $20 over 2 days, only at Notion and Apollo. Ask me above $5. Sweep back when done.');
  await expect(shell).not.toHaveClass(/is-forming/);
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
  await page.getByRole('textbox', { name: 'Describe a new wallet in plain English' }).fill('Create a wallet called Launch research with a budget of $40 over 3 days, only at HubSpot and Apollo. Sweep back when done.');
  await page.getByRole('button', { name: 'Create wallet from description' }).click();
  await expect(page.locator('.budget h1')).toHaveText('Launch research');
  await expect(page.locator('.constraints')).toHaveText('Spend up to $40 over 3 days, only at HubSpot and Apollo. Sweep back when done.');
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
  await expect(page.locator('.budget h1')).toHaveText('Launch research');
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
  await page.getByRole('button', { name: 'Transactions', exact: true }).click();
  for (const viewport of [{ width: 1470, height: 802 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const box = await page.locator('.composer').boundingBox();
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height);
    await page.locator('.transaction-card').last().scrollIntoViewIfNeeded();
    await expect(page.locator('.transaction-card').last()).toBeVisible();
  }
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await expect(page.getByRole('button', { name: 'New Wallet', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Home', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Toggle navigation' })).toHaveAttribute('aria-expanded', 'false');
  await page.getByRole('textbox', { name: 'Describe a new wallet in plain English' }).fill('A wallet called Mobile wallet with $15 for 1 day, only at Apollo');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Create wallet', exact: true }).click();
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
