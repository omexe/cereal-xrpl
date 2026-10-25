import { test, expect, type APIRequestContext } from '@playwright/test';
import { execFile } from 'node:child_process';
import path from 'node:path';
import { promisify } from 'node:util';

// A03 on XRPL testnet: edit a live wallet's spending rules from the UI, then prove cereal enforces them. Spends testnet
// RLUSD (budget 0.6, returned in afterAll): run under the machine-wide lock, see playwright.live.config.ts.
const SENTENCE = 'Rules test: spend up to 0.6 RLUSD today, only at Vendor A and Vendor C. Get the Swell agenda. Ask me above 0.2. Sweep back when done.';
const API = process.env.CEREAL_API ?? `http://127.0.0.1:${process.env.CEREAL_E2E_PORT ?? 8101}`;
const ROOT = path.resolve(process.cwd(), '..');
const RPC = 'https://s.altnet.rippletest.net:51234/';
const LONG = 10 * 60_000;
const run = promisify(execFile);

test.describe.configure({ mode: 'serial' });

let http: APIRequestContext;
let dep = '';
let vendorA = '';
let vendorC = '';
let treasury = '';
const evidence: Record<string, unknown> = {};

const record = async () => (await http.get(`${API}/subagents/${dep}`, { timeout: LONG })).json();

test.beforeAll(async ({ playwright }) => {
  http = await playwright.request.newContext({ timeout: LONG });
  treasury = (await (await http.get(`${API}/health`)).json()).main;
  const vendors: { name: string; address: string }[] = await (await http.get(`${API}/vendors`)).json();
  vendorA = vendors.find(v => v.name === 'Vendor A')!.address;
  vendorC = vendors.find(v => v.name === 'Vendor C')!.address;
  const created = await (await http.post(`${API}/wallets`, { data: { sentence: SENTENCE, speculos_decision: 'approve' } })).json();
  expect(created.ok, JSON.stringify(created).slice(0, 800)).toBe(true);
  dep = created.id;
  expect(created.allowed_payees).toEqual([vendorA, vendorC]);
  expect(created.approval_threshold).toBe('0.2');
  evidence.deployment = dep; evidence.subwallet = created.subwallet; evidence.fund = created.hashes?.fund;
});

test.afterAll(async () => {
  if (dep) {
    const out = await (await http.post(`${API}/subagents/${dep}/reclaim`)).json();
    evidence.reclaim = { ok: out.ok, returned: out.returned, steps: (out.steps ?? []).map((s: { step: string; hash?: string }) => [s.step, s.hash]) };
  }
  console.log(`EVIDENCE ${JSON.stringify(evidence)}`);
  await http?.dispose();
});

async function openWallet(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.locator(`[data-wallet-id="${dep}"]`).first().click();
  await expect(page.locator('.budget-used')).toContainText('RLUSD');
}

test('a blue rule button edits the threshold and the merchant list', async ({ page }) => {
  await openWallet(page);
  const rules = page.locator('.constraints');
  await expect(rules).toContainText('only at Vendor A and Vendor C');
  await expect(rules).toContainText('above 0.20 RLUSD');
  await rules.getByRole('button').first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Edit the fields instead' }).click();
  await expect(dialog.getByRole('checkbox', { name: /Vendor B/ })).toBeDisabled();  // revoked: never addable
  await expect(dialog).toContainText('Revoked');
  await dialog.getByLabel('Ask for approval above (RLUSD)').fill('0.1');
  await dialog.getByRole('checkbox', { name: /Vendor C/ }).uncheck();
  await expect(dialog.getByRole('button', { name: 'Apply changes' })).toBeDisabled();  // preview first
  await dialog.getByRole('button', { name: 'Preview changes' }).click();
  const preview = dialog.locator('.rules-preview');
  await expect(preview).toContainText('Approval threshold 0.2 → 0.1 RLUSD');
  await expect(preview).toContainText('Merchants Vendor A and Vendor C → Vendor A');
  await dialog.getByRole('button', { name: 'Apply changes' }).click();
  await expect(dialog.getByRole('heading', { name: 'Spending rules updated' })).toBeVisible();
  await dialog.getByRole('button', { name: 'Done' }).click();
  await expect(rules).toContainText('above 0.10 RLUSD');
  await expect(rules).toContainText('only at Vendor A.');
  await expect(rules).not.toContainText('Vendor C');
  const rec = await record();
  expect(rec.approval_threshold).toBe('0.1');
  expect(rec.allowed_payees).toEqual([vendorA]);
  expect(rec.rules_history).toHaveLength(1);
});

test('lowering the spend limit returns the excess on-ledger', async ({ page }) => {
  await openWallet(page);
  await page.locator('.constraints').getByRole('button').first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Edit the fields instead' }).click();
  await dialog.getByLabel('Spend limit (RLUSD)').fill('0.4');
  await dialog.getByRole('button', { name: 'Preview changes' }).click();
  await expect(dialog.locator('.rules-preview')).toContainText('Spend limit 0.6 → 0.4 RLUSD; 0.2 RLUSD returns to the main wallet now');
  await dialog.getByRole('button', { name: 'Apply changes' }).click();
  const link = dialog.getByRole('link', { name: 'View the return transaction' });
  await expect(link).toBeVisible();
  const href = await link.getAttribute('href');
  const hash = href!.split('/').pop()!;
  evidence.return = href;
  await dialog.getByRole('button', { name: 'Done' }).click();
  await expect(page.locator('.budget-used')).toContainText('/ 0.40 RLUSD');
  const rec = await record();
  expect(rec.budget).toBe('0.4');
  expect(rec.balance).toBe('0.4');
  expect(rec.hashes.returns).toEqual([hash]);
  // The ledger, not cereal's word: a validated RLUSD payment of 0.2 from the subwallet to the main wallet.
  const tx = (await (await http.post(RPC, { data: { method: 'tx', params: [{ transaction: hash }] } })).json()).result;
  expect(tx.validated).toBe(true);
  expect(tx.meta.TransactionResult).toBe('tesSUCCESS');
  expect((tx.tx_json ?? tx).Account).toBe(rec.subwallet);
  expect((tx.tx_json ?? tx).Destination).toBe(treasury);
  expect(tx.meta.delivered_amount.value).toBe('0.2');
});

test('raising the spend limit is refused: only Add funds adds money', async ({ page }) => {
  await openWallet(page);
  await page.locator('.constraints').getByRole('button').first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Edit the fields instead' }).click();
  await dialog.getByLabel('Spend limit (RLUSD)').fill('2');
  await dialog.getByRole('button', { name: 'Preview changes' }).click();
  await expect(dialog.locator('.rules-problems')).toContainText('Only Add funds can raise a wallet\'s budget');
  await expect(dialog.getByRole('button', { name: 'Apply changes' })).toBeDisabled();
  const direct = await (await http.post(`${API}/subagents/${dep}/rules`, { data: { spend: '2' } })).json();
  expect(direct.refused).toBe('use_add_funds');
  expect(direct.sent_transactions).toBe(0);
  await dialog.getByRole('button', { name: 'Close dialog' }).click();
  const rec = await record();
  expect(rec.budget).toBe('0.4');
  expect(rec.balance).toBe('0.4');
});

test('a sentence in the wallet composer is previewed and applied', async ({ page }) => {
  await openWallet(page);
  await expect(page.locator('.constraints')).toContainText('Sweep back');
  await page.getByRole('textbox', { name: 'Edit wallet spending rules' }).fill('Keep funds when done.');
  await page.getByRole('button', { name: 'Apply wallet constraints' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Requested change')).toHaveValue('Keep funds when done.');
  await expect(dialog.locator('.rules-preview')).toContainText('When done: sweep back to the main wallet → keep funds in the wallet');
  await dialog.getByRole('button', { name: 'Apply changes' }).click();
  await dialog.getByRole('button', { name: 'Done' }).click();
  await expect(page.locator('.constraints')).toContainText('Keep funds when done');
  const rec = await record();
  expect(rec.sweep_when_done).toBe(false);
  expect(rec.rules_history).toHaveLength(3);
});

test('cereal refuses the removed vendor for that reason', async () => {
  const before = await record();
  const { stdout } = await run(path.join(ROOT, '.venv/bin/python'),
    ['-m', 'cereal.subagent', dep, 'Rules test', '--payments', '1', '--buy', 'http://localhost:8003/swell/agenda@0.2'],
    { cwd: ROOT, env: { ...process.env, CEREAL_SERVICE_URL: API, CEREAL_LLM: 'off' }, timeout: LONG, maxBuffer: 16 * 1024 * 1024 });
  const events = stdout.trim().split('\n').filter(line => line.startsWith('{')).map(line => JSON.parse(line));
  const refused = events.find(e => e.event === 'refused');
  expect(refused?.data?.refused, stdout.slice(-1500)).toBe('payee_not_allowed');
  expect(refused.data.payee).toBe(vendorC);
  const rec = await record();
  const refusal = rec.refusals.find((r: { refused: string; payee: string }) => r.refused === 'payee_not_allowed' && r.payee === vendorC);
  expect(refusal).toBeTruthy();
  expect(refusal.allowed).toEqual([vendorA]);
  expect(rec.payments).toHaveLength(before.payments.length);  // nothing was signed or sent
  expect(rec.balance).toBe('0.4');
  expect(rec.status).toBe('active');  // "keep funds when done": done did not sweep
  evidence.refusal = { refused: refusal.refused, payee: refusal.payee, amount: refusal.amount, at: refusal.at };
});
