import { test, expect } from '@playwright/test';

test('live AI edits apply the reviewed proposal without resending the sentence', async ({ page }) => {
  const wallet = { id: 'rules-ai', name: 'Research', task: 'Research', budget: '0.6', balance: '0.6',
    currency: 'RLUSD', allowed_payees: ['rVendorA'], expires_at: '2099-01-01T00:00:00Z',
    subwallet: 'rWallet', status: 'active', approval_threshold: '0.2', sweep_when_done: true, payments: [] };
  const applied: unknown[] = [];
  const previews: unknown[] = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    if (path === '/main') return route.fulfill({ json: { address: 'rMain', rlusd: '10', xrp: '100', policy: {}, caps: {}, recent_sweeps: [] } });
    if (path === '/vendors') return route.fulfill({ json: [{ name: 'Vendor A', address: 'rVendorA', credential: { status: 'valid' } }] });
    if (path === '/folders' || path === '/events' || path === '/sweeps') return route.fulfill({ json: [] });
    if (path.endsWith('/rules/preview')) {
      const body = route.request().postDataJSON(); previews.push(body);
      return route.fulfill({ json: { ok: true, changes: ['Approval threshold 0.2 → 0.1 RLUSD'], problems: [], notes: [],
        resolved_change: { approval_threshold: '0.1' } } });
    }
    if (path.endsWith('/rules')) {
      applied.push(route.request().postDataJSON()); wallet.approval_threshold = '0.1';
      return route.fulfill({ json: { ok: true, changes: ['Approval threshold 0.2 → 0.1 RLUSD'], rules: wallet, wallet } });
    }
    if (path === '/subagents') return route.fulfill({ json: [wallet] });
    return route.fulfill({ json: wallet });
  });
  await page.goto('/');
  await page.locator('[data-wallet-id="rules-ai"]').first().click();
  await page.locator('.constraints button').first().click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Requested change')).toBeVisible();
  await dialog.getByLabel('Requested change').fill('Halve what I can spend without asking.');
  await dialog.getByRole('button', { name: 'Preview changes' }).click();
  await expect(dialog.locator('.rules-preview')).toContainText('0.2 → 0.1');
  expect(applied).toHaveLength(0);
  await dialog.getByLabel('Requested change').fill('Actually make it a quarter.');
  await expect(dialog.getByRole('button', { name: 'Apply changes' })).toBeDisabled();
  await dialog.getByLabel('Requested change').fill('Halve what I can spend without asking.');
  await dialog.getByRole('button', { name: 'Apply changes' }).click();
  await expect(dialog.getByRole('heading', { name: 'Spending rules updated' })).toBeVisible();
  expect(previews).toEqual([{ sentence: 'Halve what I can spend without asking.' }]);
  expect(applied).toEqual([{ approval_threshold: '0.1' }]);
});
