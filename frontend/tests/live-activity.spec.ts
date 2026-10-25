import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

// I04/V04: the live wallet view tells the truth about a wallet's money. Read-only against a running cereal service
// (no testnet spend, no lock):
//   CEREAL_API=http://127.0.0.1:8001 CEREAL_E2E_UI_PORT=5201 npx playwright test -c playwright.live.config.ts tests/live-activity.spec.ts
// The demo record d_e48a68 ("Market research", retired) holds a settled Vendor C payment, a Vendor A payment the
// owner's Ledger approved above the 0.2 threshold, a plan that skipped Vendor B, and its full lifecycle on testnet.

const EXPLORER = 'https://testnet.xrpl.org';
const DEMO = 'd_e48a68';

interface Pay {
  to: string; amount: string; ok?: boolean | null; hash?: string; approved_by?: string; resource?: string | null; rail?: string;
  validated?: boolean; result?: string; at?: string;
}
interface Refusal { payee?: string; amount?: string; refused: string; ok?: false; vendor?: { status?: string; revocation?: { hash?: string } } }
interface LedgerEvent { kind: string; result: string; hash: string | null; verified: boolean | null }
interface Rec {
  id: string; status: string; budget: string; subwallet?: string; balance: string | null; returned?: string; archived?: boolean;
  expires_at: string; approval_threshold?: string | null; payments?: Pay[]; refusals?: Refusal[]; events?: LedgerEvent[];
  hashes?: Record<string, string | string[] | null>;
}

/** Exact decimal sum (RLUSD strings), shown the way the app does: 2–6 decimals, never rounded up. */
function rlusd(values: (string | undefined)[]): string {
  const SCALE = 10n ** 15n;
  const total = values.reduce((sum, v) => {
    const [whole, frac = ''] = (v ?? '0').split('.');
    return sum + BigInt(whole || '0') * SCALE + BigInt((frac + '0'.repeat(15)).slice(0, 15));
  }, 0n);
  const frac = (total % SCALE).toString().padStart(15, '0').slice(0, 6).replace(/0+$/, '').padEnd(2, '0');
  return `${total / SCALE}.${frac} RLUSD`;
}

/** Settled = validated success with a hash (AP4M: redeemed on the XRPL EVM chain), one entry per hash. */
const settled = (rec: Rec) => [...new Map((rec.payments ?? [])
  .filter(p => p.ok === true && p.hash && (p.validated === true || p.rail === 'ap4m')).map(p => [p.hash, p])).values()];
const proofHashes = (rec: Rec) => [...new Set(Object.values(rec.hashes ?? {}).flatMap(v => Array.isArray(v) ? v : [v])
  .filter((h): h is string => typeof h === 'string' && h.length > 0))];

async function record(request: APIRequestContext, id: string): Promise<Rec | null> {
  const res = await request.get(`/api/subagents/${id}`);
  return res.ok() ? res.json() : null;
}

async function openWallet(page: Page, id: string) {
  await page.goto('/');
  await expect(page.locator('.home-summary h1')).toContainText('RLUSD');
  const row = page.locator(`.sidebar .wallet-row[data-wallet-id="${id}"]`).first();
  if (!await row.isVisible()) await page.locator('.wallet-more').click();
  await row.click();
  await expect(page.locator('.wallet-detail.is-live')).toBeVisible();
}

test('a retired wallet shows settled spending, Ledger approval, plan evidence and its on-ledger lifecycle', async ({ page, request }) => {
  const rec = await record(request, DEMO);
  test.skip(!rec, `${DEMO} is not on this service`);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await openWallet(page, DEMO);

  // Header: name, validated spending / budget, lifecycle status; Add funds only for active wallets.
  await expect(page.locator('.wallet-heading h1')).toHaveText('Market research');
  await expect(page.locator('.wallet-status')).toHaveText('Retired');
  await expect(page.locator('.budget-used')).toHaveText('0.40 RLUSD / 0.50 RLUSD');
  await expect(page.getByRole('button', { name: 'Add funds', exact: true })).toBeDisabled();

  // I01: distinct figures, and the subwallet's account on the explorer.
  await expect(page.locator('[data-figure=available] dd')).toHaveText('0.00 RLUSD');
  await expect(page.locator('[data-figure=spent] dd')).toHaveText('0.40 RLUSD');
  await expect(page.locator('[data-figure=pending] dd')).toHaveText('0.00 RLUSD');
  await expect(page.locator('[data-figure=returned] dd')).toHaveText('0.10 RLUSD');
  await expect(page.locator('[data-figure=address] a')).toHaveAttribute('href', `${EXPLORER}/accounts/${rec!.subwallet}`);

  // Budget bar: one segment per merchant, settled payments only, scaled to the budget.
  await expect(page.locator('.budget-legend')).toContainText('Vendor C · 0.15 RLUSD');
  await expect(page.locator('.budget-legend')).toContainText('Vendor A · 0.25 RLUSD');
  const widths = await page.locator('.budget-segment').evaluateAll(nodes => nodes.map(node => parseFloat((node as HTMLElement).style.width)));
  expect(widths).toHaveLength(2);
  expect(widths.reduce((sum, width) => sum + width, 0)).toBeCloseTo(80);

  // The rules the backend enforces, in one sentence; a finished wallet's rules cannot be edited.
  await expect(page.locator('.constraints')).toHaveText('Spend up to 0.50 RLUSD over 1 day, only at Vendor A and Vendor C. Ask me above 0.20 RLUSD. Sweep back when done.');
  for (const button of await page.locator('.constraints button').all()) await expect(button).toBeDisabled();
  const expired = Date.now() >= Date.parse(rec!.expires_at);
  await expect(page.locator('.wallet-rule-note')).toContainText(expired ? 'Expired' : 'Expires');
  await expect(page.locator('.wallet-rule-note')).toContainText('This wallet is retired');
  await expect(page.locator('.wallet-plan-note')).toHaveText(/Skipped while planning: Vendor B \(0\.05 RLUSD\), not one of the vendors you named\./);

  // Transactions: one card per payment, newest first, with state, rail, approval and explorer link. No durations.
  await expect(page.locator('.activity-summary')).toHaveText('2 settled');
  await expect(page.locator('.transaction-card')).toHaveCount(2);
  await expect(page.locator('.refusal-card')).toHaveCount(0);
  const speakers = page.locator('.transaction-card').nth(0);
  await expect(speakers).toHaveAttribute('data-hash', /^FA7594B7/);
  await expect(speakers.locator('h3')).toHaveText('Swell speakers');
  await expect(speakers.locator('.transaction-merchant')).toHaveText('Vendor A');
  await expect(speakers.locator('.transaction-amount')).toHaveText('0.25 RLUSD');
  await expect(speakers.locator('.transaction-state')).toHaveText('Settled');
  await expect(speakers.locator('.transaction-rail')).toHaveText('x402');
  await expect(speakers.locator('.transaction-approval')).toHaveText('Approved on your Ledger above 0.20 RLUSD');
  await expect(speakers.locator('a')).toHaveAttribute('href', `${EXPLORER}/transactions/FA7594B751FC79595E22365A113CF9E588CFDC9E56E528B012591A317D486A4B`);
  await expect(speakers.locator('time')).toHaveText(/ET$/);
  const agenda = page.locator('.transaction-card').nth(1);
  await expect(agenda).toHaveAttribute('data-hash', /^79B24795/);
  await expect(agenda.locator('h3')).toHaveText('Swell agenda');
  await expect(agenda.locator('.transaction-merchant')).toHaveText('Vendor C');
  await expect(agenda.locator('.transaction-amount')).toHaveText('0.15 RLUSD');
  await expect(agenda.locator('.transaction-state')).toHaveText('Settled');
  await expect(agenda.locator('.transaction-approval')).toHaveCount(0);
  await expect(agenda.locator('a')).toHaveAttribute('href', `${EXPLORER}/transactions/79B247957AB315E89DA12435B496DC74BE9C22A15B6D35DFC13242621FDA3ADB`);
  expect(await page.locator('.transaction-meta').allInnerTexts()).not.toContainEqual(expect.stringMatching(/\b\d+s\b/));

  // On-ledger proof: every lifecycle hash on the record, each linked to the explorer.
  const hashes = proofHashes(rec!);
  expect(hashes.length).toBeGreaterThanOrEqual(5);
  const proof = page.locator('.wallet-proof a');
  await expect(proof).toHaveCount(hashes.length);
  expect(await proof.evaluateAll(links => links.map(a => (a as HTMLAnchorElement).href)))
    .toEqual(expect.arrayContaining(hashes.map(h => `${EXPLORER}/transactions/${h}`)));
  for (const label of ['Activate', 'Lock · trust line', 'Lock · signer list', 'Lock · master key off', 'Fund', 'Reclaim 1/2', 'Retire']) {
    await expect(page.locator('.wallet-proof')).toContainText(label);
  }
  expect(errors).toEqual([]);
});

test('refused attempts get their own cards with revocation evidence and are never counted as spending', async ({ page, request }) => {
  const all: Rec[] = await (await request.get('/api/subagents')).json();
  const withRevocation = all.filter(r => (r.refusals ?? []).some(f => f.vendor?.revocation?.hash));
  test.skip(!withRevocation.length, 'no record with a refused, revoked vendor on this service');
  const rec = (await record(request, withRevocation.find(r => r.id === 'd_a6336c')?.id ?? withRevocation[0].id))!;
  const refusals = rec.refusals ?? [];
  await openWallet(page, rec.id);

  await expect(page.locator('.refusal-card')).toHaveCount(refusals.length);
  await expect(page.locator('.transaction-card')).toHaveCount((rec.payments ?? []).length);
  await expect(page.locator('.activity-summary')).toContainText(`${refusals.length} refused`);
  for (const card of await page.locator('.refusal-card').all()) {
    await expect(card.locator('.transaction-state')).toHaveText('Refused · nothing sent');
    await expect(card.locator('h3')).not.toBeEmpty();
  }
  const revoked = refusals.filter(f => f.vendor?.revocation?.hash);
  for (const f of revoked) {
    const href = `${EXPLORER}/transactions/${f.vendor!.revocation!.hash}`;
    const card = page.locator('.refusal-card', { has: page.locator(`a[href="${href}"]`) }).first();
    await expect(card).toBeVisible();
    await expect(card.locator('h3')).toHaveText('The vendor’s cereal credential was revoked');
  }

  // Spending is validated payments only: refused amounts never reach the figures or the bar.
  const spent = rlusd(settled(rec).map(p => p.amount));
  await expect(page.locator('[data-figure=spent] dd')).toHaveText(spent);
  await expect(page.locator('.budget-used')).toHaveText(`${spent} / ${rlusd([rec.budget])}`);
  const scale = Math.max(Number(spent.split(' ')[0]), Number(rec.budget));
  const widths = await page.locator('.budget-segment').evaluateAll(nodes => nodes.map(node => parseFloat((node as HTMLElement).style.width)));
  expect(widths.reduce((sum, width) => sum + width, 0)).toBeCloseTo(Number(spent.split(' ')[0]) / scale * 100);
});

test('pending, unvalidated, duplicate and failed payments are never shown or counted as settled', async ({ page, request }) => {
  // UI contract check on top of the real record: the service's reply is patched in the browser only (nothing is sent
  // to the ledger) to add a presented x402 payment, an ok-but-unvalidated one, a re-recorded settled hash, two failed
  // ones and a non-RLUSD refusal, and to make the wallet active, expired and without an approval threshold.
  const base = await record(request, DEMO);
  test.skip(!base, `${DEMO} is not on this service`);
  const [PENDING, UNVALIDATED, FAILED, NEVER] = ['A', 'C', 'B', 'D'].map(c => c.repeat(64));
  const fake = [PENDING, UNVALIDATED, FAILED, NEVER];
  const vendorC = base!.payments![0].to;
  const vendorA = base!.payments![1].to;
  const ago = (s: number) => new Date(Date.now() - s * 1000).toISOString();
  const patch = (rec: Rec): Rec => rec.id !== DEMO ? rec : {
    ...rec, status: 'active', archived: false, approval_threshold: null, balance: '0.1', returned: '0', expires_at: ago(60),
    payments: [...(rec.payments ?? []).filter(p => !p.hash || !fake.includes(p.hash)),
      { ...rec.payments![0] },  // the same settled hash recorded twice: one ledger transaction, counted once
      { to: vendorC, amount: '0.05', rail: 'x402', resource: 'http://localhost:8003/swell/extra', ok: null, result: 'presented', hash: PENDING, at: ago(40) },
      { to: vendorC, amount: '0.02', rail: 'x402', ok: true, result: 'tesSUCCESS', hash: UNVALIDATED, at: ago(35) },
      { to: vendorA, amount: '0.1', rail: 'direct', ok: false, result: 'tecPATH_PARTIAL', hash: FAILED, validated: true, at: ago(30) },
      { to: vendorA, amount: '0.03', rail: 'direct', ok: false, result: 'tesSUCCESS', hash: NEVER, validated: false, at: ago(25) }],
    refusals: [...(rec.refusals ?? []), { payee: vendorA, amount: '1000000', refused: 'not_rlusd', ok: false }],
  };
  await page.route('**/api/subagents', async route => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: (await res.json() as Rec[]).map(patch) });
  });
  await page.route(`**/api/subagents/${DEMO}`, async route => {
    const res = await route.fetch();
    await route.fulfill({ response: res, json: patch(await res.json()) });
  });
  await openWallet(page, DEMO);

  await expect(page.locator('.wallet-status')).toHaveText('Active');
  await expect(page.locator('.budget-used')).toHaveText('0.40 RLUSD / 0.50 RLUSD');
  await expect(page.locator('[data-figure=spent] dd')).toHaveText('0.40 RLUSD');
  await expect(page.locator('[data-figure=pending] dd')).toHaveText('0.07 RLUSD');
  await expect(page.locator('[data-figure=available] dd')).toHaveText('0.10 RLUSD');
  await expect(page.locator('.budget-segment')).toHaveCount(2);
  await expect(page.locator('.budget-legend')).toContainText('Vendor C · 0.15 RLUSD');
  await expect(page.locator('.activity-summary')).toHaveText('2 settled · 2 pending · 2 failed · 1 refused');
  await expect(page.locator('.transaction-card')).toHaveCount(6);
  for (const hash of [PENDING, UNVALIDATED]) {
    const card = page.locator(`.transaction-card[data-hash="${hash}"]`);
    await expect(card.locator('.transaction-state')).toHaveText('Pending — not settled yet');
    await expect(card).not.toContainText('Settled');
  }
  const failed = page.locator(`.transaction-card[data-hash="${FAILED}"]`);
  await expect(failed.locator('.transaction-state')).toHaveText('Failed tecPATH_PARTIAL');
  await expect(failed.locator('h3')).toHaveText('Direct payment');
  await expect(page.locator(`.transaction-card[data-hash="${NEVER}"] .transaction-state`)).toHaveText('Failed — never validated');
  const wrongCurrency = page.locator('.refusal-card[data-code=not_rlusd]');
  await expect(wrongCurrency.locator('h3')).toHaveText('Wrong currency; only RLUSD is accepted');
  await expect(wrongCurrency.locator('.transaction-amount')).toHaveCount(0);

  // Active but expired: rules stay editable (to extend the window); Add funds does not, since cereal refuses every
  // payment now. No threshold reads honestly.
  await expect(page.getByRole('button', { name: 'Add funds', exact: true })).toBeDisabled();
  await expect(page.locator('.constraints')).toContainText('cereal co-signs every payment.');
  await expect(page.locator('.constraints')).not.toContainText('Ask me');
  for (const button of await page.locator('.constraints button').all()) await expect(button).toBeEnabled();
  await expect(page.locator('.wallet-rule-note')).toContainText('Expired');
  await expect(page.locator('.wallet-rule-note')).toContainText('cereal refuses every payment after that');
});

test('attempts the ledger itself rejected are shown with their result codes and never counted', async ({ page, request }) => {
  const all: Rec[] = await (await request.get('/api/subagents')).json();
  const withEvents = all.filter(r => (r.events ?? []).length);
  test.skip(!withEvents.length, 'no record with ledger-level refusals on this service');
  const rec = (await record(request, withEvents.find(r => r.id === 'd_55e9c3')?.id ?? withEvents[0].id))!;
  const events = rec.events ?? [];
  await openWallet(page, rec.id);

  await expect(page.locator('.refusal-card[data-kind=ledger]')).toHaveCount(events.length);
  await expect(page.locator('.activity-summary')).toContainText(`${events.length} blocked by the ledger`);
  for (const e of events) {
    await expect(page.locator(`.refusal-card[data-kind=ledger][data-code=${e.result}]`).first())
      .toContainText(`Blocked by the ledger · ${e.result}`);
  }
  for (const e of events.filter(e => e.hash)) {
    const card = page.locator('.refusal-card[data-kind=ledger]', { has: page.locator(`a[href="${EXPLORER}/transactions/${e.hash}"]`) });
    await expect(card).toHaveCount(1);
    await expect(card).toContainText(e.verified ? 'Verified on the ledger' : 'Not verified');
  }
  const spent = rlusd(settled(rec).map(p => p.amount));
  await expect(page.locator('[data-figure=spent] dd')).toHaveText(spent);
});
