import { existsSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, type APIRequestContext } from '@playwright/test';

// A05/A06 against a private cereal service on a fixture record file: folders, drag-and-drop, the Settings folder
// select, rename, archive and restore all persist through the API. Metadata sends no transaction, so nothing here
// spends testnet funds (only reads, such as the main wallet's balance, reach the ledger). Run:
//   CEREAL_DEPLOYMENTS_FILE=deployments.e2e-workspace.json CEREAL_E2E_PORT=8105 CEREAL_E2E_UI_PORT=5205 \
//     npx playwright test -c playwright.live.config.ts tests/live-workspace.spec.ts
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const RECORDS = process.env.CEREAL_DEPLOYMENTS_FILE;
const VENDOR_A = 'rGrhEwizViewpp8b91RTdUV2MpdWUdaEay';

function record(id: string, name: string, status: string, subwallet: string, minutesAgo: number) {
  const created = new Date(Date.now() - minutesAgo * 60_000);
  return {
    id, parent: 'main', task: `${name} task`, budget: '1', currency: 'RLUSD', allowed_payees: [VENDOR_A], vendor_class: 'data',
    refusals: [], expires_at: new Date(created.getTime() + 86_400_000).toISOString(), tag: `e2e-${id}`, subwallet,
    subagent: null, status, hashes: {}, summary: 'fixture', created_at: created.toISOString(), name,
    payments: [{ to: VENDOR_A, amount: '0.25', ok: true, result: 'tesSUCCESS', hash: `E2E${id.toUpperCase()}`, validated: true, at: created.toISOString() }],
    returned: '0.75', reclaimed_at: created.toISOString(),
  };
}

// beforeAll overwrites the record file, so this spec runs only on its own fixture file and its own private service:
// never the demo's deployments.json, never deployments.e2e.json (other live specs' funded wallets), never CEREAL_API.
const FIXTURE = 'deployments.e2e-workspace.json';
const owned = !process.env.CEREAL_API && !!RECORDS && path.basename(RECORDS) === FIXTURE;
test.skip(!owned, `needs CEREAL_DEPLOYMENTS_FILE=${FIXTURE} and the private service (no CEREAL_API); it rewrites that file`);

test.beforeAll(() => {
  if (!owned) return;
  const file = path.resolve(ROOT, RECORDS!);
  const records = [
    record('d_ws0001', 'Workspace Alpha', 'retired', 'rziZDEdVjmeEakXwj6ybpFa4UokVNJv32', 3),
    record('d_ws0002', 'Workspace Beta', 'reclaimed', 'rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR', 2),
    record('d_ws0003', 'Workspace Gamma', 'retired', 'rTYDyjZQJvUay4Je4i6RjHjrms7mroFLw', 1),
  ];
  writeFileSync(file, JSON.stringify(Object.fromEntries(records.map(r => [r.id, r])), null, 2));
  const folders = file.replace(/\.json$/, '.folders.json');
  if (existsSync(folders)) rmSync(folders);
});

const wallet = async (request: APIRequestContext, id: string) => (await request.get(`/api/subagents/${id}`)).json();

test('folders, moves, rename, archive and restore persist through the cereal service', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const row = '.wallet-row[data-wallet-id="d_ws0001"]';
  const disposable = page.locator('[data-wallet-group="disposable"]');
  const folder = page.locator('[data-folder-id="Market Research"]');
  const archived = page.locator('.sidebar-section', { has: page.getByRole('heading', { name: 'Archived Wallets' }) });
  const dialog = page.getByRole('dialog');
  const walletSettings = dialog.locator('.settings-wallet'); // the selected wallet's block inside live Settings

  await page.goto('/');
  await page.getByRole('button', { name: '+ 3 more', exact: true }).click();
  await page.getByRole('button', { name: 'Open Workspace Alpha', exact: true }).click();
  await expect(page.locator('.budget-label h1')).toHaveText('Workspace Alpha');

  // New folder → it appears, and the service lists it.
  await page.getByRole('button', { name: 'New folder' }).click();
  await page.getByLabel('Folder name').fill('  Market Research ');
  await page.getByRole('button', { name: 'Create folder' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(folder).toBeVisible();
  expect((await (await request.get('/api/folders')).json()).map((f: { name: string }) => f.name)).toEqual(['Market Research']);

  // A duplicate (ignoring case) is shown inline in the dialog; the service refuses it too.
  await page.getByRole('button', { name: 'New folder' }).click();
  await page.getByLabel('Folder name').fill('market RESEARCH');
  await page.getByRole('button', { name: 'Create folder' }).click();
  await expect(dialog.getByRole('alert')).toHaveText('A folder named “Market Research” already exists.');
  await page.getByRole('button', { name: 'Close dialog' }).click();
  expect((await (await request.post('/api/folders', { data: { name: 'MARKET research' } })).json()).refused).toBe('folder_exists');

  // Drag the wallet into the folder → the record's folder changes and survives a reload.
  await disposable.locator(row).dragTo(folder.locator('.folder-row'));
  await expect(folder.locator(row)).toBeVisible();
  await expect.poll(async () => (await wallet(request, 'd_ws0001')).folder).toBe('Market Research');
  await page.reload();
  await folder.locator('.folder-row').click();
  await expect(folder.locator(row)).toBeVisible();

  // Settings folder select → back to unfiled.
  await folder.locator(row).click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await walletSettings.getByLabel('Wallet folder').selectOption('');
  await expect(walletSettings.getByRole('status')).toHaveText('Moved to Disposable Wallets.');
  await expect.poll(async () => (await wallet(request, 'd_ws0001')).folder).toBeNull();

  // Rename → the sidebar and the detail update.
  await walletSettings.getByLabel('Wallet name').fill('Swell agenda');
  await walletSettings.getByRole('button', { name: 'Save name' }).click();
  await expect(walletSettings.getByRole('status')).toHaveText('Name saved.');
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await expect(page.locator('.budget-label h1')).toHaveText('Swell agenda');
  await expect(disposable.getByRole('button', { name: 'Open Swell agenda', exact: true })).toBeVisible();
  expect((await wallet(request, 'd_ws0001')).name).toBe('Swell agenda');

  // Archive → it moves to Archived Wallets; its status is unchanged.
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(walletSettings).toContainText('Archiving hides this wallet. It stays retired; nothing moves on the ledger');
  await walletSettings.getByRole('button', { name: 'Archive selected wallet' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(archived.locator(row)).toBeVisible();
  await expect(disposable.locator(row)).toHaveCount(0);
  const stored = await wallet(request, 'd_ws0001');
  expect([stored.archived, stored.status, stored.returned]).toEqual([true, 'retired', '0.75']);
  await page.reload();
  await expect(archived.locator(row)).toBeVisible();

  // Restore (WalletDetail's "Restore wallet") → it comes back, still retired.
  await archived.locator(row).click();
  await page.getByRole('button', { name: 'Restore wallet', exact: true }).click();
  await expect(disposable.locator(row)).toBeVisible();
  await expect(archived.locator(row)).toHaveCount(0);
  const restored = await wallet(request, 'd_ws0001');
  expect([restored.archived, restored.status]).toEqual([false, 'retired']);

  // Metadata can never change policy or revive a retired account.
  for (const data of [{ status: 'active' }, { archived: false, status: 'active' }, { budget: '5' }]) {
    expect((await request.post('/api/subagents/d_ws0001/meta', { data })).status()).toBe(422);
  }
  expect((await wallet(request, 'd_ws0001')).status).toBe('retired');

  // A reclaimed wallet archived and restored through the API stays reclaimed.
  for (const archivedFlag of [true, false]) {
    const out = await (await request.post('/api/subagents/d_ws0002/meta', { data: { archived: archivedFlag } })).json();
    expect([out.ok, out.wallet.archived, out.wallet.status]).toEqual([true, archivedFlag, 'reclaimed']);
  }
  expect(errors).toEqual([]);
});
