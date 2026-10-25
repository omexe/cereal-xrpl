import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

// A01/A02/A07 on XRPL testnet: start a wallet's task from the UI, watch the subagent buy, see the sweep, then retire.
// Spends testnet RLUSD; run under the machine-wide lock (see playwright.live.config.ts):
//   CEREAL_E2E_PORT=8107 CEREAL_E2E_UI_PORT=5207 ../.venv/bin/python ../scripts/with_testnet_lock.py -- \
//     npx playwright test -c playwright.live.config.ts tests/live-run.spec.ts
// Setup and checks call the private service directly (wallet creation waits for the Ledger and three transactions).
const API = process.env.CEREAL_API ?? `http://127.0.0.1:${process.env.CEREAL_E2E_PORT ?? 8101}`;
const VENDOR_C = 'r3NdoyQhgKorLo54v2VGkMrMTyPHbTXszs';
const EXPLORER_TX = /^https:\/\/testnet\.xrpl\.org\/transactions\/[0-9A-F]{64}$/;
const TOO_YOUNG = 'Too new to retire. cereal retires it automatically once it’s 256 ledgers old (~15 min).';

test.describe.configure({ mode: 'serial' });
const created: string[] = [];

async function createWallet(request: APIRequestContext, sentence: string) {
  const res = await request.post(`${API}/wallets`, { data: { sentence }, timeout: 10 * 60_000 });
  const body = await res.json();
  expect(body.ok, JSON.stringify(body).slice(0, 600)).toBe(true);
  created.push(body.id);
  console.log(`created ${body.id} ${body.subwallet}: fund ${body.hashes?.fund}`);
  return body as { id: string; subwallet: string; status: string; hashes: Record<string, unknown> };
}

async function openWallet(page: Page, id: string) {
  await page.goto('/');
  await page.locator(`[data-wallet-group] .wallet-row[data-wallet-id="${id}"]`).click();  // newest active wallet: listed first
  return page.locator('.wallet-actions');
}

async function retireOrTooYoung(page: Page, actions: ReturnType<Page['locator']>) {
  await actions.getByRole('button', { name: 'Retire account' }).click();
  await expect(actions.getByText(TOO_YOUNG).or(page.locator('.wallet-actions[data-wallet-status="retired"]'))).toBeVisible({ timeout: 120_000 });
  const retired = await page.locator('.wallet-actions[data-wallet-status="retired"]').count();
  console.log(retired ? 'retired: account deleted' : 'retire: too young (stays tracked for the sweeper)');
}

test.afterAll(async ({ playwright }) => {
  const request = await playwright.request.newContext();
  for (const id of created) {  // never leave budget in a test wallet
    const rec = await (await request.get(`${API}/subagents/${id}`)).json();
    if (rec.status === 'active') {
      const out = await (await request.post(`${API}/subagents/${id}/reclaim`, { timeout: 5 * 60_000 })).json();
      console.log(`afterAll reclaimed ${id}: ${out.ok} ${out.returned}`);
    }
  }
  await request.dispose();
});

test('start the task: the subagent buys from Vendor C, sweeps home, and the account can be retired', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const w = await createWallet(request, 'Run test: spend up to 0.5 RLUSD today, only at Vendor A and Vendor C. '
    + 'Get the Swell agenda. Ask me above 0.4. Sweep back when done.');
  expect(w.status).toBe('active');
  expect((await (await request.get(`${API}/subagents/${w.id}/run`)).json()).run, 'creating a wallet never starts its task').toBeNull();

  const actions = await openWallet(page, w.id);
  await expect(actions).toHaveAttribute('data-wallet-status', 'active');
  await actions.getByRole('button', { name: 'Start task' }).click();
  await expect(actions.getByText(/^Running · \d+:\d\d/)).toBeVisible();
  await expect(actions.getByText(/Buying the agenda from Vendor C at 0\.15 RLUSD/)).toBeVisible();
  await expect(actions.getByRole('button', { name: 'Start task' })).toHaveCount(0);
  const second = await (await request.post(`${API}/subagents/${w.id}/run`)).json();
  expect(second.refused, 'a second start while running').toBe('already_running');

  await expect(actions.locator('.run')).toHaveAttribute('data-run-status', 'succeeded', { timeout: 10 * 60_000 });
  const paid = actions.locator('[data-payment-state="settled"]');
  await expect(paid).toHaveCount(1);
  await expect(paid).toContainText('Swell agenda · Vendor C · 0.15 RLUSD');
  await expect(paid.getByRole('link', { name: 'Settled' })).toHaveAttribute('href', EXPLORER_TX);

  await expect(actions).toHaveAttribute('data-wallet-status', 'reclaimed', { timeout: 3 * 60_000 });
  await expect(actions.getByText('Swept back · 0.35 RLUSD returned to the main wallet')).toBeVisible();
  await expect(actions.getByRole('link', { name: 'Swept to the main wallet' })).toHaveAttribute('href', EXPLORER_TX);
  await expect(actions.getByRole('link', { name: 'Trust line closed' })).toHaveAttribute('href', EXPLORER_TX);

  const rec = await (await request.get(`${API}/subagents/${w.id}`)).json();
  expect(rec.status).toBe('reclaimed');
  expect(rec.returned).toBe('0.35');
  expect(rec.run.status).toBe('succeeded');
  expect(rec.run.exit_code).toBe(0);
  const settled = rec.payments.filter((p: { ok?: boolean }) => p.ok === true);
  expect(settled).toHaveLength(1);
  expect(settled[0]).toMatchObject({ to: VENDOR_C, amount: '0.15', rail: 'x402', validated: true, result: 'tesSUCCESS' });
  console.log(`payment ${settled[0].explorer}`);
  for (const h of rec.hashes.reclaim) console.log(`reclaim https://testnet.xrpl.org/transactions/${h}`);
  console.log(`run summary: ${rec.run.summary}`);

  await retireOrTooYoung(page, actions);
  expect((await (await request.get(`${API}/subagents/${w.id}`)).json()).status).toMatch(/reclaimed|retired/);
  expect(errors).toEqual([]);
});

test('a sentence that names nothing to buy is refused; Done sweeps it home', async ({ page, request }) => {
  const w = await createWallet(request, 'Idle test: spend up to 0.1 RLUSD today, only at Vendor C. Sweep back when done.');
  const actions = await openWallet(page, w.id);
  await actions.getByRole('button', { name: 'Start task' }).click();
  await expect(actions.getByRole('alert')).toContainText('Nothing to buy');
  expect((await (await request.post(`${API}/subagents/${w.id}/run`)).json()).refused).toBe('nothing_to_buy');
  expect((await (await request.get(`${API}/subagents/${w.id}/run`)).json()).run).toBeNull();
  await expect(actions.getByRole('button', { name: 'Start task' })).toBeEnabled();

  await actions.getByRole('button', { name: 'Done · sweep back' }).click();
  await expect(actions).toHaveAttribute('data-wallet-status', 'reclaimed', { timeout: 3 * 60_000 });
  await expect(actions.getByText('Swept back · 0.10 RLUSD returned to the main wallet')).toBeVisible();
  await expect(actions.getByRole('link', { name: 'Swept to the main wallet' })).toHaveAttribute('href', EXPLORER_TX);
  const rec = await (await request.get(`${API}/subagents/${w.id}`)).json();
  expect(rec).toMatchObject({ status: 'reclaimed', returned: '0.1', summary: 'Finished by the owner' });
});

test('Reclaim now asks first, then returns the RLUSD and closes the trust line', async ({ page, request }) => {
  const w = await createWallet(request, 'Keep test: spend up to 0.1 RLUSD today, only at Vendor C. Keep funds when done.');
  const actions = await openWallet(page, w.id);
  await expect(actions.getByRole('button', { name: 'Done · sweep back' })).toHaveCount(0);
  await actions.getByRole('button', { name: 'Reclaim now' }).click();
  const confirm = actions.getByRole('group', { name: 'Confirm reclaim' });
  await expect(confirm).toContainText('Return 0.10 RLUSD to the main wallet and close the trust line?');
  await confirm.getByRole('button', { name: 'Cancel' }).click();
  await expect(confirm).toHaveCount(0);
  expect((await (await request.get(`${API}/subagents/${w.id}`)).json()).status, 'cancel sends nothing').toBe('active');

  await actions.getByRole('button', { name: 'Reclaim now' }).click();
  await actions.getByRole('group', { name: 'Confirm reclaim' }).getByRole('button', { name: 'Reclaim' }).click();
  await expect(actions).toHaveAttribute('data-wallet-status', 'reclaimed', { timeout: 3 * 60_000 });
  await expect(actions.getByText('Swept back · 0.10 RLUSD returned to the main wallet')).toBeVisible();
  await expect(actions.getByRole('link', { name: 'Swept to the main wallet' })).toHaveAttribute('href', EXPLORER_TX);
  await expect(actions.getByRole('link', { name: 'Trust line closed' })).toHaveAttribute('href', EXPLORER_TX);
  await retireOrTooYoung(page, actions);
});
