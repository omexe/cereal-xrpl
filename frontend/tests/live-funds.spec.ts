import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

// A04 on XRPL testnet: Add funds is the owner's action on the Ledger (Speculos here). Spends testnet RLUSD from the
// shared treasury: run it under the machine-wide lock (see playwright.live.config.ts). The wallet it creates is
// reclaimed in afterAll, so every RLUSD it received goes back to the main wallet.
const SENTENCE = 'Funds test: spend up to 0.5 RLUSD today, only at Vendor A and Vendor C. Get the Swell agenda. Sweep back when done.';
const RPC = process.env.XRPL_TESTNET_RPC_URL ?? 'https://s.altnet.rippletest.net:51234/';
const LONG = { timeout: 10 * 60_000 };

let api: APIRequestContext;
let id = '';
let subwallet = '';
const evidence: Record<string, string> = {};

async function wallet() {
  const res = await api.get(`/api/subagents/${id}`);
  expect(res.ok()).toBeTruthy();
  return res.json();
}

async function rpc(method: string, params: Record<string, unknown>) {
  const res = await api.post(RPC, { data: { method, params: [params] } });
  return (await res.json()).result;
}

async function validated(hash: string) {
  const r = await rpc('tx', { transaction: hash });
  const tx = r.tx_json ?? r; // API v2 nests the transaction; v1 does not
  return { validated: r.validated === true, result: r.meta?.TransactionResult, type: tx.TransactionType, tx };
}

async function openWallet(page: Page) {
  await page.goto('/');
  await page.locator(`[data-wallet-id="${id}"]`).first().click();
  await expect(page.locator('.wallet-detail h1')).toHaveText('Funds test');
}

const dialog = (page: Page) => page.getByRole('dialog', { name: 'Add funds' });
const fact = (page: Page, name: string) => dialog(page).locator(`[data-fact="${name}"]`);

test.describe.serial('Add funds on testnet', () => {
  test.beforeAll(async ({ playwright }, testInfo) => {
    api = await playwright.request.newContext({ baseURL: testInfo.project.use.baseURL, timeout: 10 * 60_000 });
    const res = await api.post('/api/wallets', { data: { sentence: SENTENCE, speculos_decision: 'approve' }, ...LONG });
    const created = await res.json();
    expect(created.ok, JSON.stringify(created).slice(0, 500)).toBe(true);
    id = created.id; subwallet = created.subwallet;
    expect(created.budget).toBe('0.5');
    expect(created.balance).toBe('0.5');
    console.log(`wallet ${id} subwallet ${subwallet} fund ${created.hashes?.fund}`);
  });

  test.afterAll(async () => {
    if (!api || !id) return;
    const before = await wallet();
    if (before.status === 'active') {
      const out = await (await api.post(`/api/subagents/${id}/reclaim`, LONG)).json();
      console.log(`reclaim ${JSON.stringify({ ok: out.ok, returned: out.returned, steps: out.steps?.map((s: { step: string; hash?: string }) => [s.step, s.hash]) })}`);
      expect(out.ok).toBe(true);
      // Everything the wallet held came home: the original 0.5 plus every approved top-up.
      const topups = (before.topups ?? []).reduce((sum: number, t: { amount: string }) => sum + Number(t.amount), 0);
      expect(Number(out.returned)).toBeCloseTo(0.5 + topups, 6);
      expect(out.returned).toBe(before.balance);
      expect((await wallet()).status).toBe('reclaimed');
      const lines: { balance: string }[] = (await rpc('account_lines', { account: subwallet, ledger_index: 'validated' })).lines ?? [];
      expect(lines.every(l => Number(l.balance) === 0)).toBe(true);
    }
    console.log(`evidence ${JSON.stringify(evidence)}`);
    await api.dispose();
  });

  test('from the wallet: add 0.25 RLUSD, approved on the Ledger, lands on-ledger', async ({ page }) => {
    await openWallet(page);
    await page.locator('.budget-actions').getByRole('button', { name: 'Add funds' }).click();
    await expect(dialog(page)).toBeVisible();
    await expect(dialog(page)).toContainText('Your Ledger approves this payment from the main wallet; nothing moves without it.');
    await expect(dialog(page).getByLabel('Wallet to fund')).toHaveCount(0); // opened from the wallet itself
    await expect(fact(page, 'available')).toHaveText('0.50 RLUSD');
    await expect(fact(page, 'budget')).toHaveText('0.50 RLUSD');
    await expect(fact(page, 'room')).toHaveText('4.50 RLUSD');
    await dialog(page).getByLabel('Amount (RLUSD)').fill('0.25');
    await dialog(page).getByLabel('Speculos emulator').selectOption('approve');
    const approve = dialog(page).getByRole('button', { name: 'Approve on Ledger' });
    await approve.click();
    await expect(dialog(page).getByRole('status')).toContainText('Waiting for your approval on the Ledger');
    await expect(approve).toBeDisabled();
    await expect(dialog(page)).toHaveCount(0);
    await expect(page.locator('#status-message')).toContainText('Added 0.25 RLUSD to Funds test, approved on your Ledger. Budget 0.75 RLUSD.');
    await expect(page.locator('#status-message')).toContainText('https://testnet.xrpl.org/transactions/');
    await expect(page.locator('.budget-used')).toContainText('/ 0.75 RLUSD');
    await expect(page.locator('.constraints')).toContainText('Spend up to 0.75 RLUSD');
    await expect(page.locator('[data-figure="available"] dd')).toHaveText('0.75 RLUSD'); // read from the ledger

    const rec = await wallet();
    expect(rec.budget).toBe('0.75');
    expect(rec.balance).toBe('0.75');
    expect(rec.topups).toHaveLength(1);
    const [t] = rec.topups;
    expect(t.amount).toBe('0.25');
    expect(t.approval.screens.join(' ')).toContain('0.25');
    evidence.fund = `https://testnet.xrpl.org/transactions/${t.hash}`;
    evidence.trustline = `https://testnet.xrpl.org/transactions/${t.trustline_hash}`;
    const pay = await validated(t.hash);
    expect(pay).toMatchObject({ validated: true, result: 'tesSUCCESS', type: 'Payment' });
    expect(pay.tx.Destination).toBe(subwallet);
    expect(pay.tx.Amount?.value ?? pay.tx.DeliverMax?.value).toBe('0.25');
    expect(pay.tx.Signers?.length).toBe(1); // the owner's Ledger alone, as the main wallet's signer
    const line = await validated(t.trustline_hash);
    expect(line).toMatchObject({ validated: true, result: 'tesSUCCESS', type: 'TrustSet' });
    expect(line.tx.Account).toBe(subwallet);
    expect(line.tx.LimitAmount.value).toBe('0.75');
    expect(line.tx.Signers?.length).toBe(2); // subagent + cereal: the subwallet's master key is disabled
    const lines = (await rpc('account_lines', { account: subwallet, ledger_index: 'validated' })).lines;
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatchObject({ balance: '0.75', limit: '0.75' });

    // Reopened, the dialog reads the new numbers back from the service.
    await page.locator('.budget-actions').getByRole('button', { name: 'Add funds' }).click();
    await expect(fact(page, 'available')).toHaveText('0.75 RLUSD');
    await expect(fact(page, 'budget')).toHaveText('0.75 RLUSD');
    await expect(fact(page, 'room')).toHaveText('4.25 RLUSD');
  });

  test('from Home: the owner rejects on the Ledger and nothing moves', async ({ page }) => {
    await page.goto('/');
    await page.locator('.home-summary').getByRole('button', { name: 'Add funds' }).click();
    await expect(dialog(page)).toBeVisible();
    const select = dialog(page).getByLabel('Wallet to fund');
    const active = new Set(((await (await api.get('/api/subagents')).json()) as { id: string; status: string; archived?: boolean }[])
      .filter(w => w.status === 'active' && !w.archived).map(w => w.id));
    const offered = await select.locator('option').evaluateAll(options => options.map(o => (o as HTMLOptionElement).value));
    expect(offered).toContain(id);
    expect(offered.every(v => active.has(v))).toBe(true); // only active wallets can take funds
    await select.selectOption(id);
    await expect(fact(page, 'budget')).toHaveText('0.75 RLUSD');
    await dialog(page).getByLabel('Amount (RLUSD)').fill('0.1');
    await dialog(page).getByLabel('Speculos emulator').selectOption('reject');
    await dialog(page).getByRole('button', { name: 'Approve on Ledger' }).click();
    await expect(dialog(page).getByRole('alert')).toHaveText('Rejected on the Ledger. Nothing was sent.');
    await expect(dialog(page).getByRole('button', { name: 'Approve on Ledger' })).toBeEnabled();
    const rec = await wallet();
    expect(rec.balance).toBe('0.75');
    expect(rec.budget).toBe('0.75');
    expect(rec.topups).toHaveLength(1);
    expect(rec.refusals.at(-1)).toMatchObject({ refused: 'owner_rejected', rail: 'topup', amount: '0.1' });
    const events = await (await api.get('/api/events')).json();
    expect(events.find((e: { deployment: string; code: string }) => e.deployment === id && e.code === 'owner_rejected'))
      .toMatchObject({ by: 'owner', outcome: 'nothing sent' });

    // Over the cap: refused by cereal before the device is asked; nothing is sent.
    await dialog(page).getByLabel('Speculos emulator').selectOption('approve');
    await dialog(page).getByLabel('Amount (RLUSD)').fill('10');
    await dialog(page).getByRole('button', { name: 'Approve on Ledger' }).click();
    await expect(dialog(page).getByRole('alert')).toHaveText(
      'That is above the company cap of 5.00 RLUSD per wallet; room left is 4.25 RLUSD. Nothing was sent.');
    const after = await wallet();
    expect(after.balance).toBe('0.75');
    expect(after.topups).toHaveLength(1);
    expect(Object.keys(after.fund_requests ?? {})).toHaveLength(2); // the approval and the rejection; the cap refusal asked nothing

    // A malformed amount never reaches the service.
    await dialog(page).getByLabel('Amount (RLUSD)').fill('0.1234567');
    await expect(dialog(page).getByRole('button', { name: 'Approve on Ledger' })).toBeDisabled();
  });

  test('the same request_id twice over the API sends one payment', async () => {
    const body = { amount: '0.05', request_id: `e2e-${Date.now()}`, speculos_decision: 'approve' };
    // The twin arrives while the first waits on the device: it queues on the main-wallet lock, then gets the result.
    const send = async (delay: number) => {
      await new Promise(resolve => setTimeout(resolve, delay));
      return (await api.post(`/api/subagents/${id}/fund`, { data: body, ...LONG })).json();
    };
    const [a, b] = await Promise.all([send(0), send(1500)]);
    expect(a.ok && b.ok, JSON.stringify([a, b]).slice(0, 800)).toBe(true);
    expect(a.hashes).toEqual(b.hashes);
    expect([a.replayed, b.replayed].filter(Boolean)).toHaveLength(1);
    const c = await (await api.post(`/api/subagents/${id}/fund`, { data: body, ...LONG })).json();
    expect(c).toMatchObject({ ok: true, replayed: true, hashes: a.hashes, budget: '0.8' });
    const rec = await wallet();
    expect(rec.balance).toBe('0.8'); // 0.75 + 0.05 once
    expect(rec.budget).toBe('0.8');
    expect(rec.topups).toHaveLength(2);
    evidence.replayed_fund = `https://testnet.xrpl.org/transactions/${a.hashes.fund}`;
    expect(await validated(a.hashes.fund)).toMatchObject({ validated: true, result: 'tesSUCCESS' });
    const conflict = await (await api.post(`/api/subagents/${id}/fund`, { data: { ...body, amount: '0.06' } })).json();
    expect(conflict.refused).toBe('request_id_reused');
  });
});
