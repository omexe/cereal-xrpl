import { test, expect, type Page } from '@playwright/test';

// Read-only (I06, I07): live Settings shows the service, policy, vendors, security events, sweeps and exports from
// the cereal service, and the right state when the service cannot be reached. Nothing here spends testnet funds.
const MOCK_MERCHANTS = /HubSpot|Clearbit|Apollo/;
const TESTNET_TX = /^https:\/\/testnet\.xrpl\.org\/transactions\/[0-9A-F]{64}$/;
const account = (address: string) => `https://testnet.xrpl.org/accounts/${address}`;
// The app's formatAmount: at least 2 and at most 6 decimals, never rounded.
const rlusd = (value: number | string) => { const [whole, frac = ''] = String(value).split('.'); return `${whole}.${frac.slice(0, 6).replace(/0+$/, '').padEnd(2, '0')} RLUSD`; };

interface ApiEvent { at: string; kind: string; wallet?: string; deployment?: string; what?: string; outcome?: string; proof?: string | null }
interface ApiVendor { name: string; address: string; paid?: { count: number }; refused?: { count: number };
  credential?: { status: string; revocation?: { reason?: string; explorer?: string } } }

async function openSettings(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Workspace settings' });
  await expect(dialog).toBeVisible();
  return dialog;
}

test('live settings come from the cereal service', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const main = await (await request.get('/api/main')).json();
  const vendors: ApiVendor[] = await (await request.get('/api/vendors')).json();
  const uiEventsReply = page.waitForResponse(r => r.url().endsWith('/api/events?limit=50') && r.ok());
  const dialog = await openSettings(page);
  const uiEvents: ApiEvent[] = await (await uiEventsReply).json();
  // Read GET /events right after the app did, so a newly recorded event cannot land in between.
  const apiEvents: ApiEvent[] = await (await request.get('/api/events?limit=50')).json();

  // 1. Connection: mode, reachable, the main wallet and its balances, matching GET /main.
  const connection = dialog.locator('[data-section="connection"]');
  await expect(connection.locator('[data-field="mode"]')).toHaveText('Live · XRPL testnet');
  await expect(connection.locator('[data-field="service"]')).toHaveText('Reachable');
  const address = connection.locator('[data-field="address"] a');
  await expect(address).toHaveText(main.address);
  await expect(address).toHaveAttribute('href', account(main.address));
  await expect(connection.locator('[data-field="rlusd"]')).toContainText('RLUSD');
  await expect(connection.locator('[data-field="xrp"]')).toContainText('XRP');
  await expect(connection.locator('[data-field="active"]')).toHaveText(`${main.active_subagents} of ${main.caps.MAX_ACTIVE_SUBAGENTS}`);
  await expect(connection.locator('[data-field="updated"]')).not.toHaveText('Not yet');

  // 2. Policy: credentials, issuer, the emulated device, AP4M, and the caps from GET /main.
  const policy = dialog.locator('[data-section="policy"]');
  await expect(policy.locator('[data-field="credentials"]')).toContainText(main.policy.vendor_credentials ? 'Required' : 'Not required');
  await expect(policy.locator('[data-field="issuer"] a')).toHaveAttribute('href', account(main.policy.issuer));
  await expect(policy.locator('[data-field="device-funding"]')).toHaveText(main.policy.device_funding ? 'On' : 'Off');
  if (main.policy.device) await expect(policy.locator('[data-field="device"] a')).toHaveAttribute('href', account(main.policy.device));
  await expect(policy.locator('[data-field="device"]')).toContainText('Speculos');
  await expect(policy.locator('[data-field="ap4m"]')).toContainText(main.policy.ap4m?.enabled ? 'Enabled' : 'Disabled');
  await expect(policy.locator('[data-field="ap4m"]')).toContainText('not native XRPL');
  await expect(policy.locator('[data-cap="MAX_SUBAGENT_BUDGET"]')).toHaveText(rlusd(main.caps.MAX_SUBAGENT_BUDGET));
  await expect(policy.locator('[data-cap="MAX_OUTSTANDING_BUDGET"]')).toHaveText(rlusd(main.caps.MAX_OUTSTANDING_BUDGET));
  await expect(policy.locator('[data-cap="MAX_ACTIVE_SUBAGENTS"]')).toHaveText(`${main.caps.MAX_ACTIVE_SUBAGENTS} wallets`);

  // 3. Vendors: one card per GET /vendors entry; B revoked with its public CredentialDelete, A and C valid.
  const section = dialog.locator('[data-section="vendors"]');
  const card = (name: string) => section.locator(`.settings-vendor[data-vendor="${name}"]`);
  await expect(section.locator('.settings-vendor')).toHaveCount(vendors.length);
  for (const vendor of vendors) {
    await expect(card(vendor.name)).toHaveAttribute('data-credential', vendor.credential?.status ?? 'none');
    await expect(card(vendor.name).locator('.settings-card-head a')).toHaveAttribute('href', account(vendor.address));
    await expect(card(vendor.name).locator('[data-field="paid"]')).toContainText(`${vendor.paid?.count ?? 0} payment`);
    await expect(card(vendor.name).locator('[data-field="refused"]')).toContainText(`${vendor.refused?.count ?? 0} payment`);
  }
  const vendorB = vendors.find(v => v.name === 'Vendor B');
  expect(vendorB?.credential?.status).toBe('revoked');
  await expect(card('Vendor B')).toContainText('Credential revoked');
  if (vendorB?.credential?.revocation?.reason) await expect(card('Vendor B')).toContainText(vendorB.credential.revocation.reason);
  await expect(card('Vendor B').getByRole('link', { name: 'Revocation transaction' })).toHaveAttribute('href', TESTNET_TX);
  for (const name of ['Vendor A', 'Vendor C']) {
    await expect(card(name)).toHaveAttribute('data-credential', 'valid');
    await expect(card(name)).toContainText('Valid credential');
  }
  // Refresh reads GET /vendors again and keeps the same cards.
  const vendorsReply = page.waitForResponse(r => r.url().endsWith('/api/vendors'));
  await section.getByRole('button', { name: 'Refresh vendors' }).click();
  expect((await vendorsReply).status()).toBe(200);
  await expect(section.locator('.settings-vendor')).toHaveCount(vendors.length);

  // 4. Security events: exactly what GET /events?limit=50 returned, in order, with proof links.
  expect(uiEvents.length).toBe(apiEvents.length);
  expect(uiEvents.map(e => [e.at, e.kind])).toEqual(apiEvents.map(e => [e.at, e.kind]));
  const events = dialog.locator('[data-section="events"] .settings-event');
  await expect(events).toHaveCount(uiEvents.length);
  for (const [i, event] of uiEvents.entries()) {
    const row = events.nth(i);
    await expect(row).toHaveAttribute('data-kind', event.kind);
    if (event.what) await expect(row.locator('[data-field="what"]')).toHaveText(event.what);
    await expect(row.locator('[data-field="wallet"]')).toHaveText(event.wallet ?? event.deployment ?? '—');
    await expect(row.locator('[data-field="outcome"]')).toHaveText(event.outcome ?? '—');
    if (event.proof) await expect(row.locator('[data-field="proof"] a')).toHaveAttribute('href', event.proof);
    else await expect(row.locator('[data-field="proof"]')).toHaveText('No ledger transaction');
  }
  if (!uiEvents.length) await expect(dialog.locator('[data-section="events"] .settings-empty')).toBeVisible();

  // 5. Recent sweeps from GET /main, each with its transaction.
  const sweeps = dialog.locator('[data-section="sweeps"] .settings-sweep');
  await expect(sweeps).toHaveCount(main.recent_sweeps.length);
  for (const [i, sweep] of main.recent_sweeps.entries()) {
    await expect(sweeps.nth(i).locator('[data-field="returned"]')).toHaveText(rlusd(sweep.returned));
    if (sweep.hash) await expect(sweeps.nth(i).locator('[data-field="proof"] a')).toHaveAttribute('href', `https://testnet.xrpl.org/transactions/${sweep.hash}`);
  }

  // 6. Exports: both links answer 200 and download; the count matches GET /export.json.
  const exported = await (await request.get('/api/export.json')).json();
  const exports = dialog.locator('[data-section="exports"]');
  const count = exports.locator('[data-field="export-count"]');
  await expect(count).toContainText(`${exported.rows.length} record`);
  await expect(count).toContainText(`${exported.totals.payments} settled payment`);
  await expect(count).toContainText(rlusd(exported.totals.rlusd));
  for (const [name, type, file] of [['Download CSV', 'text/csv', 'cereal-payments.csv'], ['Download JSON', 'application/json', 'cereal-payments.json']]) {
    const link = exports.getByRole('link', { name });
    await expect(link).toHaveAttribute('download', file);
    const reply = await request.get((await link.getAttribute('href'))!);
    expect(reply.status()).toBe(200);
    expect(reply.headers()['content-type']).toContain(type);
    const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
    expect(download.suggestedFilename()).toBe(file);
    expect(await download.failure()).toBeNull();
  }

  // Long content scrolls inside the dialog, under a fixed header.
  const scroller = dialog.locator('.settings-live');
  expect(await scroller.evaluate(el => el.scrollHeight > el.clientHeight && getComputedStyle(el).overflowY === 'auto')).toBe(true);
  await exports.scrollIntoViewIfNeeded();
  await expect(dialog.getByRole('heading', { name: 'Workspace settings' })).toBeInViewport();

  // The mock merchants never appear in live mode.
  expect(await dialog.innerText()).not.toMatch(MOCK_MERCHANTS);
  expect(await page.locator('body').innerText()).not.toMatch(MOCK_MERCHANTS);
  expect(errors).toEqual([]);
});

test('live settings show when the cereal service is not reachable', async ({ page }) => {
  await page.route('**/api/main', route => route.abort());
  await page.route(/\/api\/events\?/, route => route.abort());
  await page.route('**/api/export.json', route => route.abort());
  const dialog = await openSettings(page);
  const connection = dialog.locator('[data-section="connection"]');
  await expect(connection.locator('[data-field="service"]')).toHaveText('Not reachable');
  await expect(connection.getByRole('alert')).toContainText('The cereal service is not reachable.');
  await expect(connection.locator('[data-field="address"]')).toHaveText('—');
  await expect(dialog.locator('[data-section="policy"]')).toContainText('The policy loads with the main wallet.');
  await expect(dialog.locator('[data-section="events"]').getByRole('alert')).toContainText('Could not read security events');
  await expect(dialog.locator('[data-section="exports"]').getByRole('alert')).toContainText('Could not read the export');
  expect(await dialog.innerText()).not.toMatch(MOCK_MERCHANTS);
});

test('live settings show loading and empty states', async ({ page }) => {
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route(/\/api\/events\?/, async route => { await held; await route.fulfill({ json: [] }); });
  const dialog = await openSettings(page);
  const events = dialog.locator('[data-section="events"]');
  await expect(events.getByRole('status')).toHaveText('Loading security events…');
  await expect(events.getByRole('button', { name: 'Refresh security events' })).toBeDisabled();
  release();
  await expect(events.locator('.settings-empty')).toContainText('No security events yet');
  await expect(events.getByRole('button', { name: 'Refresh security events' })).toBeEnabled();
});

test('a failed vendor refresh is shown and keeps the last vendor list', async ({ page }) => {
  // Let the store's own vendor read land first, so its next one is 60 s away and cannot replace the panel's result.
  const storeRead = page.waitForResponse(r => r.url().endsWith('/api/vendors') && r.ok());
  await page.goto('/');
  await storeRead;
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Workspace settings' });
  const vendors = dialog.locator('[data-section="vendors"]');
  await expect(vendors.locator('.settings-vendor').first()).toBeVisible();
  const before = await vendors.locator('.settings-vendor').count();
  await page.route('**/api/vendors', route => route.abort());
  await vendors.getByRole('button', { name: 'Refresh vendors' }).click();
  await expect(vendors.getByRole('alert')).toContainText('Could not read vendors: The cereal service is not reachable.');
  await expect(vendors.locator('.settings-vendor')).toHaveCount(before);
  await page.unroute('**/api/vendors');
  await vendors.getByRole('button', { name: 'Refresh vendors' }).click();
  await expect(vendors.getByRole('alert')).toHaveCount(0);
  await expect(vendors.locator('.settings-vendor')).toHaveCount(before);
});
