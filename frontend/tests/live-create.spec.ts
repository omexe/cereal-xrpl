import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

// I05 / R07 / R03 on XRPL testnet: New wallet → review the card → create, through the real cereal service and the
// Speculos emulator. Spends testnet RLUSD (≤ 0.5): run under the machine-wide lock (see playwright.live.config.ts).
// Every wallet this spec creates is reclaimed in afterEach, pass or fail.
const CREATE = 'Create test: spend up to 0.5 RLUSD today, only at Vendor A and Vendor C. Get the Swell agenda. Ask me above 0.2. Sweep back when done.';
const REVOKED = 'Revoked test: spend up to 0.3 RLUSD today, only at Vendor B. Sweep back when done.';
const REJECT = 'Reject test: spend up to 0.3 RLUSD today, only at Vendor A. Sweep back when done.';
const CHANGED = 'Changed test: spend up to 0.3 RLUSD today, only at Vendor A. Sweep back when done.';
const OURS = [CREATE, REVOKED, REJECT, CHANGED];

interface Rec { id: string; status: string; sentence?: string; budget: string; hashes?: Record<string, unknown>; [k: string]: unknown }

const records = async (request: APIRequestContext): Promise<Rec[]> => (await request.get('/api/subagents')).json();
const newRecords = async (request: APIRequestContext, before: Set<string>, sentence: string) =>
  (await records(request)).filter(r => !before.has(r.id) && r.sentence === sentence);

const dialog = (page: Page) => page.locator('dialog[aria-labelledby="dialog-title"]');

/** Waits until the dialog closes (created) or shows an error, and says which. */
async function outcome(page: Page): Promise<string> {
  return Promise.race([
    dialog(page).waitFor({ state: 'detached', timeout: 240_000 }).then(() => 'closed'),
    page.locator('.wallet-error').waitFor({ timeout: 240_000 }).then(async () => `error: ${await page.locator('.wallet-error').innerText()}`),
  ]);
}

test.afterEach(async ({ request }) => {
  // Reclaim every wallet of ours that is still active: the budget goes back to the shared treasury.
  for (const r of await records(request)) {
    if (r.status !== 'active' || !OURS.includes(r.sentence ?? '')) continue;
    const res = await (await request.post(`/api/subagents/${r.id}/reclaim`, { data: {}, timeout: 240_000 })).json();
    console.log(`reclaimed ${r.id}: ok=${res.ok} returned=${res.returned}`);
    expect(res.ok, JSON.stringify(res)).toBe(true);
  }
});

test('create from the home composer: review the card, then the wallet is locked and funded on testnet', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const posted: Record<string, unknown>[] = [];
  page.on('request', r => { if (r.method() === 'POST' && new URL(r.url()).pathname === '/api/wallets') posted.push(r.postDataJSON()); });
  const before = new Set((await records(request)).map(r => r.id));

  await page.goto('/');
  await expect(page.locator('.home-summary h1')).toContainText('RLUSD');
  await page.getByRole('textbox', { name: 'Describe a new wallet in plain English' }).fill(CREATE);
  await page.getByRole('button', { name: 'Create wallet from description' }).click();
  await expect(page.getByLabel('Describe the wallet')).toHaveValue(CREATE);
  const preview = page.waitForResponse(r => new URL(r.url()).pathname === '/api/wallets/preview');
  await page.getByRole('button', { name: 'Review wallet' }).click();
  const card = await (await preview).json();

  const shown = page.getByRole('region', { name: 'Wallet card' });
  await expect(shown.locator('[data-field=budget]')).toHaveText('0.50 RLUSD');
  await expect(shown.locator('.card-vendor[data-credential=valid]')).toHaveCount(2);
  await expect(shown.locator('.card-vendor[data-credential=valid]').nth(0)).toContainText('Vendor A');
  await expect(shown.locator('.card-vendor[data-credential=valid]').nth(1)).toContainText('Vendor C');
  await expect(shown.locator('.card-vendor.not-allowed')).toHaveCount(0);
  await expect(shown).toContainText('0.20 RLUSD');
  await expect(shown).toContainText('Sweep leftovers back to the main wallet');
  await expect(shown).toContainText('Read by the backup parser');
  await page.getByLabel('Speculos emulator: approve / reject').selectOption('approve');

  // A double click must never create two wallets.
  await page.getByRole('button', { name: 'Create on testnet' }).dblclick();
  await expect(page.getByRole('button', { name: 'Create on testnet' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Edit' })).toBeDisabled();
  await expect(page.getByText('Waiting for approval on your Ledger…')).toBeVisible();
  await expect.soft(page.getByText('Locking and funding the wallet on testnet…')).toBeVisible({ timeout: 120_000 });
  expect(await outcome(page)).toBe('closed');
  await expect(page.locator('#status-message')).toContainText('Funding transaction: https://testnet.xrpl.org/transactions/');

  const made = await newRecords(request, before, CREATE);
  expect(made, 'exactly one wallet for one reviewed card').toHaveLength(1);
  const id = made[0].id;
  expect(posted).toHaveLength(1);
  expect(posted[0]).toMatchObject({ sentence: CREATE, card_digest: card.digest, speculos_decision: 'approve' });
  expect(String(posted[0].request_id)).toMatch(/^[0-9a-f-]{36}$/);

  await expect(page.locator(`[data-wallet-id="${id}"]`)).toHaveAttribute('data-status', 'active');
  await expect(page.locator(`[data-wallet-id="${id}"]`)).toHaveAttribute('aria-current', 'true');
  await expect(page.locator('.budget-label h1')).toHaveText('Create test');
  await expect(page.locator('.budget-used')).toContainText('/ 0.50 RLUSD');

  const rec = await (await request.get(`/api/subagents/${id}`)).json();
  expect(rec.status).toBe('active');
  expect(rec.budget).toBe('0.5');
  expect(rec.hashes.fund).toMatch(/^[0-9A-F]{64}$/);
  expect(rec.card_digest).toBe(card.digest);
  expect(rec.request_id).toBe(posted[0].request_id);
  console.log(`created ${id}: subwallet ${rec.subwallet} https://testnet.xrpl.org/transactions/${rec.hashes.fund}`);

  // R03: the same request again returns the same wallet, nothing new on the ledger.
  const replay = await (await request.post('/api/wallets', { data: posted[0] })).json();
  expect(replay).toMatchObject({ ok: true, id, replayed: true });
  expect(await newRecords(request, before, CREATE)).toHaveLength(1);
  expect(errors).toEqual([]);
});

test('a revoked vendor: the card marks it not allowed and nothing is created', async ({ page, request }) => {
  const before = new Set((await records(request)).map(r => r.id));
  await page.goto('/');
  await page.getByRole('textbox', { name: 'Describe a new wallet in plain English' }).fill(REVOKED);
  await page.getByRole('button', { name: 'Create wallet from description' }).click();
  await page.getByRole('button', { name: 'Review wallet' }).click();
  const shown = page.getByRole('region', { name: 'Wallet card' });
  const vendor = shown.locator('.card-vendor.not-allowed');
  await expect(vendor).toHaveCount(1);
  await expect(vendor).toHaveAttribute('data-credential', 'revoked');
  await expect(vendor).toContainText('Vendor B');
  await expect(vendor).toContainText('revoked · not allowed');
  await expect(shown.getByRole('list', { name: 'Problems' })).toContainText('not trusted (revoked)');
  await expect(page.getByRole('button', { name: 'Create on testnet' })).toBeDisabled();
  // The service refuses it too, whatever a client does.
  const direct = await (await request.post('/api/wallets', { data: { sentence: REVOKED } })).json();
  expect(direct.refused).toBe('card_problems');
  await page.getByRole('button', { name: 'Edit' }).click();
  await expect(page.getByLabel('Describe the wallet')).toHaveValue(REVOKED);
  expect(await newRecords(request, before, REVOKED)).toHaveLength(0);
});

test('owner rejection on the Ledger: the error shows, no active wallet, the record says rejected', async ({ page, request }) => {
  const before = new Set((await records(request)).map(r => r.id));
  await page.goto('/');
  await expect(page.locator('.home-summary h1')).toContainText('RLUSD');
  await page.getByRole('button', { name: 'New Wallet', exact: true }).click();
  await page.getByLabel('Describe the wallet').fill(REJECT);
  await page.getByRole('button', { name: 'Review wallet' }).click();
  await expect(page.getByRole('region', { name: 'Wallet card' }).locator('.card-vendor[data-credential=valid]')).toHaveCount(1);
  await page.getByLabel('Speculos emulator: approve / reject').selectOption('reject');
  await page.getByRole('button', { name: 'Create on testnet' }).click();
  await expect(page.getByText('Waiting for approval on your Ledger…')).toBeVisible();
  expect(await outcome(page)).toBe('error: Rejected on your Ledger. Nothing was sent.');
  await expect(dialog(page)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create on testnet' })).toBeEnabled();

  const made = await newRecords(request, before, REJECT);
  expect(made).toHaveLength(1);
  const rec = await (await request.get(`/api/subagents/${made[0].id}`)).json();
  expect(rec.status).toBe('rejected');
  expect(rec.approval.result).toBe('owner_rejected');
  expect(rec.hashes?.fund ?? null).toBeNull();
  expect(rec.subwallet ?? null).toBeNull();
  await page.getByRole('button', { name: 'Close dialog' }).click();
  await expect(page.locator(`[data-wallet-id="${made[0].id}"][data-status=active]`)).toHaveCount(0);
});

test('a card that changed after review is refused card_changed and must be confirmed again', async ({ page, request }) => {
  const before = new Set((await records(request)).map(r => r.id));
  // API: a mismatched digest sends nothing and returns the rebuilt card.
  const stale = '0'.repeat(64);
  const direct = await (await request.post('/api/wallets', { data: { sentence: CHANGED, card_digest: stale, request_id: crypto.randomUUID() } })).json();
  expect(direct).toMatchObject({ ok: false, refused: 'card_changed', sent_transactions: 0 });
  expect(direct.card.digest).toMatch(/^[0-9a-f]{64}$/);
  expect(direct.card.digest).not.toBe(stale);

  // UI: the reviewed card is made stale in transit, so the service's rebuilt card differs.
  await page.route('**/api/wallets/preview', async route => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: { ...(await res.json()), digest: stale } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'New Wallet', exact: true }).click();
  await page.getByLabel('Describe the wallet').fill(CHANGED);
  await page.getByRole('button', { name: 'Review wallet' }).click();
  await page.getByRole('button', { name: 'Create on testnet' }).click();
  await expect(page.getByText('The rules changed since you reviewed them. Review them again.')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Wallet card' }).locator('[data-field=budget]')).toHaveText('0.30 RLUSD');
  await expect(page.getByRole('button', { name: 'Create on testnet' })).toBeEnabled();
  await page.getByRole('button', { name: 'Close dialog' }).click();
  expect(await newRecords(request, before, CHANGED)).toHaveLength(0);
});
