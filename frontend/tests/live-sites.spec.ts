import { test, expect, type Page, type Route } from '@playwright/test';

// Sites UI (docs/SITES.md) against a mocked cereal service: every /api call is answered here with page.route, so
// nothing touches testnet and the Sites backend need not be running. Any CEREAL_API works:
//   CEREAL_API=http://127.0.0.1:8001 CEREAL_E2E_UI_PORT=5214 npx playwright test -c playwright.live.config.ts tests/live-sites.spec.ts
// SITES_SHOTS=<dir> also saves screenshots of the add-site card and the delivered content.

const RLUSD_HEX = '524C555344000000000000000000000000000000';
const ISSUER = 'rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV';
const VENDOR_D = 'rsV4kQoq7dzYZf3NYvK1Wt5TNSUY4HDqJ2';
const VENDOR_E = 'rEvnE8pqJ8VdQ6nTnBFXZ2kPWsSRm9H4aT';
const USDC_BASE_SEPOLIA = '0x036CbD53842c5426634e7929541eC2318f3dCF7e';
const D_URL = 'http://localhost:8004/research/report';
const E_URL = 'http://localhost:8005/research/report';
const F_URL = 'http://localhost:8006/research/report';
const USDC_URL = 'http://localhost:8004/usdc/report';
const FREE_URL = 'https://example.com';
const WALLED_URL = 'https://www.gatorade.com/';
const ARCHIVE_URL = 'https://web.archive.org/web/20261006135037/https://www.gatorade.com/';
const WALL_REASON = "www.gatorade.com blocks automated agents with Cloudflare's bot check (a captcha only a person in a browser can pass). cereal does not try to get around it.";
const USDC_REASON = 'This paywall only takes USDC on Base Sepolia (eip155:84532); cereal pays RLUSD on XRPL testnet (xrpl:1).';
const TOKEN = 'tok_test_123';
const USER = { id: 'u_test', name: 'Ana' };
const PAID_HASH = 'A1B2C3D4E5F60718293A4B5C6D7E8F90A1B2C3D4E5F60718293A4B5C6D7E8F90';
const LOST_HASH = 'FEDCBA98765432100123456789ABCDEFFEDCBA98765432100123456789ABCDEF';
const tx = (hash: string) => `https://testnet.xrpl.org/transactions/${hash}`;
const SHOTS = process.env.SITES_SHOTS;

type Json = Record<string, unknown>;
const now = () => new Date().toISOString();
const check = (name: string, ok: boolean | null, detail: string) => ({ name, ok, detail });
const payment = (payTo: string, url: string, description: string) => ({
  network: 'xrpl:1', asset: RLUSD_HEX, issuer: ISSUER, amount: '0.1', pay_to: payTo, resource: url, description, invoice_id: 'inv_1',
});
const okChecks = (payTo: string) => [
  check('asset', true, 'RLUSD on XRPL testnet, exact scheme'),
  check('price', true, '0.1 RLUSD (cap 1)'),
  check('payee_exists', true, `${payTo} exists on testnet`),
  check('payee_rlusd', true, 'RLUSD trust line open'),
  check('domain_proof', true, 'localhost’s xrp-ledger.toml lists the payee, and its Domain is localhost'),
];
const base = (url: string) => ({ url, origin: new URL(url).origin, host: new URL(url).hostname, accepts: [] as Json[], reason: null,
  credential: null, checks: [] as Json[], verdict: 'ok', verdict_reasons: [] as string[], payment: null, title: null, status: 200 });

const PROBES: Record<string, Json> = {
  [D_URL]: { ...base(D_URL), kind: 'payable', status: 402, payment: payment(VENDOR_D, D_URL, 'Vendor D: research report'),
    accepts: [{ network: 'xrpl:1', asset: RLUSD_HEX, amount: '0.1' }], credential: 'none',
    checks: [...okChecks(VENDOR_D), check('payee_history', null, 'Created 2 hours ago'), check('credential', null, 'No cereal credential: private only')],
    verdict: 'warn', verdict_reasons: ['The address is new: created 2 hours ago.'], trust_hint: 'private' },
  [E_URL]: { ...base(E_URL), kind: 'payable', status: 402, payment: payment(VENDOR_E, E_URL, 'Vendor E: research report'),
    accepts: [{ network: 'xrpl:1', asset: RLUSD_HEX, amount: '0.1' }], credential: 'none', checks: okChecks(VENDOR_E),
    verdict: 'ok', verdict_reasons: [], trust_hint: 'private' },
  [F_URL]: { ...base(F_URL), kind: 'payable', status: 402, payment: payment(VENDOR_E, F_URL, 'Vendor F: research report'),
    accepts: [{ network: 'xrpl:1', asset: RLUSD_HEX, amount: '0.1' }], credential: 'none',
    checks: [check('price', true, '0.1 RLUSD (cap 1)'), check('payee_exists', true, `${VENDOR_E} exists on testnet`),
      check('domain_proof', false, `localhost’s xrp-ledger.toml lists ${VENDOR_D}, not the payee ${VENDOR_E}`)],
    verdict: 'block', verdict_reasons: ['The site asks you to pay an address its own xrp-ledger.toml does not list.'], trust_hint: 'blocked' },
  [USDC_URL]: { ...base(USDC_URL), kind: 'unpayable', status: 402,
    accepts: [{ network: 'eip155:84532', asset: USDC_BASE_SEPOLIA, amount: '100000', scheme: 'exact', label: 'USDC on Base Sepolia (eip155:84532)' }],
    reason: USDC_REASON, verdict: 'block', verdict_reasons: [USDC_REASON], trust_hint: 'none' },
  [FREE_URL]: { ...base(FREE_URL), kind: 'free', status: 200, title: 'Example Domain', verdict: 'ok', trust_hint: 'free' },
  [WALLED_URL]: { ...base(WALLED_URL), kind: 'unreachable', status: 403, reason: WALL_REASON, verdict: 'block', verdict_reasons: [WALL_REASON],
    trust_hint: 'none', blocked_by: 'Cloudflare', archive: { url: ARCHIVE_URL, source: 'Internet Archive', timestamp: '2026-10-06T13:50:37Z' } },
  [ARCHIVE_URL]: { ...base(ARCHIVE_URL), kind: 'free', status: 200, title: 'Gatorade (archived)', verdict: 'ok', trust_hint: 'free' },
};

const DELIVERED = { title: 'Vendor D research report', findings: ['RLUSD settles on XRPL testnet in 3–5 s', '<b>not markup</b>'] };

/** A stateful stand-in for the cereal service: session, sites, site purchases and their runs. */
class Service {
  user: typeof USER | null = null;
  sites: Json[] = [];
  wallets: Json[] = [];
  runs: Record<string, { polls: number; site: string }> = {};
  buys: Json[] = [];
  sessionNames: string[] = [];
  unauthorized = 0;
  seq = 0;
  /** Content reads that answer "delivered, payment not validated yet" before the ledger settles it. */
  settlingReads = 0;

  site(url: string, extra: Json = {}): Json {
    const probe = PROBES[url];
    const site = { ...probe, id: `s_${++this.seq}`, owner: USER.id, name: (probe.title as string | null) ?? new URL(url).host,
      trust: probe.trust_hint, blocked_reason: null, added_at: now(), probed_at: now(), wallets: [], ...extra };
    this.sites.push(site);
    return site;
  }

  async handle(route: Route) {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api/, '');
    const method = request.method();
    const json = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    const authed = request.headers().authorization === `Bearer ${TOKEN}`;
    const body = (): Json => JSON.parse(request.postData() || '{}');

    if (path === '/main') return json({ address: 'rMainWa11etxxxxxxxxxxxxxxxxxxxxxxx', xrp: '90', rlusd: '5', outstanding_budget: '0',
      active_subagents: 0, recent_sweeps: [], caps: { MAX_SUBAGENT_BUDGET: 1, MAX_OUTSTANDING_BUDGET: 3, MAX_ACTIVE_SUBAGENTS: 5 },
      policy: { vendor_credentials: true, issuer: ISSUER, device_funding: true, ledger_recovery: true } });
    if (path === '/vendors' || path === '/folders') return json([]);
    if (path === '/subagents') return json(this.wallets);
    let m = path.match(/^\/subagents\/([^/]+)\/run$/);
    if (m) {
      const run = this.runs[m[1]];
      if (!run) return json({ ok: true, run: null });
      run.polls += 1;
      const status = run.polls >= 2 ? 'succeeded' : 'running';
      return json({ ok: true, run: { id: `r_${m[1]}`, deployment: m[1], status, started_at: new Date(Date.now() - 8000).toISOString(),
        finished_at: status === 'succeeded' ? now() : null, exit_code: status === 'succeeded' ? 0 : null } });
    }
    m = path.match(/^\/subagents\/([^/]+)$/);
    if (m) { const w = this.wallets.find(x => x.id === m![1]); return w ? json(w) : json({ detail: 'unknown deployment' }, 404); }

    if (path === '/session' && method === 'POST') {
      const name = String(body().name ?? '').trim();
      this.sessionNames.push(name);
      if (!name) return json({ ok: false, refused: 'invalid_name' });
      this.user = { ...USER, name };
      return json({ ok: true, user: this.user, token: TOKEN });
    }
    if (path === '/session') return authed ? json({ ok: true, user: USER }) : json({ detail: 'sign in' }, 401);
    if (path === '/sites/probe') {
      const url = String(body().url);
      return PROBES[url] ? json({ ok: true, ...PROBES[url] }) : json({ ok: false, refused: 'unsafe_url', reason: 'Local and private addresses are not opened.' });
    }
    if (!path.startsWith('/sites')) return json({ detail: 'Not Found' }, 404);
    if (!authed) { this.unauthorized += 1; return json({ detail: 'sign in' }, 401); }

    if (path === '/sites' && method === 'GET') return json(this.sites);
    if (path === '/sites' && method === 'POST') {
      const url = String(body().url);
      const probe = PROBES[url];
      if (probe.kind === 'unpayable' || probe.kind === 'unreachable') return json({ ok: false, refused: 'not_accessible', reason: probe.reason });
      if (probe.trust_hint === 'blocked') {
        const site = this.site(url, { trust: 'blocked', blocked_reason: (probe.verdict_reasons as string[])[0], blocked_by: 'probe', blocked_at: now(),
          blocked_evidence: { verdict_reasons: probe.verdict_reasons, checks: (probe.checks as { ok: boolean | null }[]).filter(c => c.ok === false) } });
        return json({ ok: false, refused: 'site_blocked', reason: site.blocked_reason, site });
      }
      return json({ ok: true, site: this.site(url) });
    }
    m = path.match(/^\/sites\/([^/]+)\/(remove|open|buy|content)$/);
    const site = m && this.sites.find(s => s.id === m![1]);
    if (!m || !site) return json({ detail: 'unknown site' }, 404);
    const [, id, action] = m;
    if (action === 'remove') { this.sites = this.sites.filter(s => s.id !== id); return json({ ok: true }); }
    if (action === 'open') return json({ ok: true, url: site.url, status: 200, content_type: 'text/html; charset=utf-8', title: 'Example Domain',
      text: 'Example Domain\n\nThis domain is for use in documentation examples.\n<script>alert("x")</script> <b>not bold</b>', truncated: true, bytes: 1256 });
    if (action === 'buy') {
      const request = body();
      this.buys.push(request);
      await new Promise(resolve => setTimeout(resolve, 1500));  // the owner's Ledger approving the budget
      if (request.speculos_decision === 'reject') return json({ ok: false, refused: 'owner_rejected' });
      const wallet = { id: `d_site${this.wallets.length + 1}`, task: `Buy ${site.url}`, name: `${site.name} purchase`, budget: '0.12', currency: 'RLUSD',
        allowed_payees: [(site.payment as Json).pay_to], expires_at: new Date(Date.now() + 3600_000).toISOString(), created_at: now(),
        status: 'active', balance: '0.12', owner: USER.id, site: id, sweep_when_done: true, payments: [] };
      this.wallets.unshift(wallet);
      (site.wallets as string[]).push(wallet.id as string);
      this.runs[wallet.id as string] = { polls: 0, site: id };
      return json({ ok: true, wallet, run: { id: `r_${wallet.id}`, deployment: wallet.id, status: 'running', started_at: now() } });
    }
    // content
    const wallet = (site.wallets as string[]).at(-1);
    if (!wallet) return json({ ok: false, refused: 'nothing_bought' });
    if (this.runs[wallet].polls < 2) return json({ ok: false, refused: 'not_delivered', pending: true, status: 'running', wallet, trust: site.trust });
    if (site.url === E_URL) {
      Object.assign(site, { trust: 'blocked', blocked_reason: 'paid_not_delivered', blocked_by: 'paid_not_delivered', blocked_at: now(),
        blocked_evidence: { hash: LOST_HASH, explorer: tx(LOST_HASH), payee: VENDOR_E, resource: E_URL, amount: '0.1', deployment: wallet } });
      return json({ ok: false, refused: 'not_delivered', pending: false, status: 'succeeded', wallet, trust: 'blocked', hash: LOST_HASH,
        paid: '0.1', explorer: tx(LOST_HASH), error: 'The vendor answered 500 after the payment validated.' });
    }
    const settling = this.settlingReads > 0 && this.settlingReads-- > 0;
    return json({ ok: true, wallet, hash: PAID_HASH, paid: settling ? null : '0.1', price: '0.1', settled: settling ? null : true,
      explorer: tx(PAID_HASH), resource: site.url, content: DELIVERED, truncated: false });
  }
}

async function setup(page: Page, { signedIn = true }: { signedIn?: boolean } = {}) {
  const service = new Service();
  if (signedIn) {
    service.user = USER;
    await page.addInitScript(([token, user]) => {
      if (!sessionStorage.getItem('sites-test-seeded')) {  // seed once: a sign-out must survive a reload
        localStorage.setItem('cereal-session', JSON.stringify({ user, token }));
        sessionStorage.setItem('sites-test-seeded', '1');
      }
    }, [TOKEN, USER] as const);
  }
  await page.route('**/api/**', route => service.handle(route));
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  return { service, errors };
}

const sitesSection = (page: Page) => page.getByRole('region', { name: 'My sites' });
const addDialog = (page: Page) => page.getByRole('dialog', { name: 'Add a site' });

async function checkSite(page: Page, url: string) {
  await sitesSection(page).getByRole('button', { name: 'Add site' }).click();
  const dialog = addDialog(page);
  await dialog.getByLabel('Site address').fill(url);
  await dialog.getByRole('button', { name: 'Check site' }).click();
  await expect(dialog.getByRole('region', { name: 'Site check' })).toBeVisible();
  return dialog;
}

test('sign in, see that sites are private, and sign out', async ({ page }) => {
  const { service, errors } = await setup(page, { signedIn: false });
  await page.goto('/');
  const section = sitesSection(page);
  await expect(section).toContainText('Your sites are private to you.');
  await section.getByRole('button', { name: 'Sign in to use sites' }).click();

  const signIn = page.getByRole('dialog', { name: 'Sign in to use sites' });
  await expect(signIn).toContainText('Your sites are private to you. Nobody else sees your list, only your wallets can pay');
  await expect(signIn).toContainText('your Ledger signs every one of those payments');
  await expect(signIn.getByRole('button', { name: 'Sign in' })).toBeDisabled();
  await signIn.getByLabel('Your name').fill('Ana');
  await signIn.getByRole('button', { name: 'Sign in' }).click();

  // Signed in, the same dialog continues as Add a site.
  await expect(addDialog(page)).toContainText('Adding to Ana’s sites · private to you.');
  expect(service.sessionNames).toEqual(['Ana']);
  await addDialog(page).getByRole('button', { name: 'Close dialog' }).click();
  await expect(section).toContainText('Signed in as Ana');
  await expect(section).toContainText('Private to you: nobody else sees this list, and only your wallets can pay these sites.');
  await expect(section.getByRole('button', { name: 'Add your first site' })).toBeVisible();
  expect(JSON.parse(await page.evaluate(() => localStorage.getItem('cereal-session') ?? 'null'))).toEqual({ user: USER, token: TOKEN });

  await section.getByRole('button', { name: 'Sign out' }).click();
  await expect(section.getByRole('button', { name: 'Sign in to use sites' })).toBeVisible();
  await expect(section).not.toContainText('Signed in as');
  expect(await page.evaluate(() => localStorage.getItem('cereal-session'))).toBeNull();
  expect(service.unauthorized).toBe(0);
  expect(errors).toEqual([]);
});

test('a URL in the composer checks a payable private site; adding it opens the site', async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto('/');
  await page.getByLabel('Describe a new wallet in plain English').fill(D_URL);
  await page.getByRole('button', { name: 'Create wallet from description' }).click();

  const dialog = addDialog(page);
  await expect(dialog.getByLabel('Site address')).toHaveValue(D_URL);
  // Opened from the composer with an address: the check runs by itself.
  const card = dialog.getByRole('region', { name: 'Site check' });
  await expect(card).toHaveAttribute('data-kind', 'payable');
  await expect(card.locator('.site-kind')).toHaveText('Paid: 0.10 RLUSD to rsV4kQ…DqJ2');
  await expect(card).toContainText('No cereal credential');
  await expect(card.locator('.site-check')).toHaveCount(7);
  await expect(card.locator('[data-check=domain_proof]')).toHaveAttribute('data-ok', 'true');
  await expect(card.locator('[data-check=domain_proof]')).toContainText('Domain proof: passed');
  await expect(card.locator('[data-check=payee_history]')).toHaveAttribute('data-ok', 'null');
  await expect(card.locator('[data-check=payee_history]')).toContainText('Payee history: could not tell');
  await expect(card.locator('.site-verdict')).toContainText('Verdict: Warnings');
  await expect(card.getByRole('list', { name: 'Verdict reasons' })).toContainText('The address is new: created 2 hours ago.');
  await expect(card.locator('.site-trust-note')).toContainText('Will be added as Private to you');
  await expect(card.locator('.site-trust-note')).toContainText('Only your wallets can pay it, and your Ledger signs every payment.');
  if (SHOTS) await dialog.screenshot({ path: `${SHOTS}/add-site-card.png` });

  await dialog.getByRole('button', { name: 'Add to my sites' }).click();
  await expect(dialog).toHaveCount(0);
  const detail = page.locator('.site-detail');
  await expect(detail.getByRole('heading', { level: 1 })).toHaveText('localhost:8004');
  await expect(detail.locator('.site-trust').first()).toHaveText('Private to you');
  await expect(detail.locator('[data-fact=price] dd')).toHaveText('0.10 RLUSD');
  await expect(detail.locator('[data-fact=payee] a')).toHaveAttribute('href', `https://testnet.xrpl.org/accounts/${VENDOR_D}`);
  await expect(detail.getByRole('link', { name: D_URL })).toHaveAttribute('href', D_URL);
  await expect(detail.getByRole('button', { name: 'Buy with a new wallet' })).toBeVisible();
  const row = sitesSection(page).getByRole('button', { name: 'Open localhost:8004 (Private to you)' });
  await expect(row).toHaveAttribute('aria-current', 'true');
  await expect(row).toHaveAttribute('data-trust', 'private');
  await expect(page.getByRole('status').filter({ hasText: 'added to your sites as private to you' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('Vendor F fails domain proof: blocked at the check, stored as blocked, nothing but Remove', async ({ page }) => {
  const { errors } = await setup(page);
  await page.goto('/');
  const dialog = await checkSite(page, 'localhost:8006/research/report');  // no scheme: local merchants get http
  await expect(dialog.getByLabel('Site address')).toHaveValue(F_URL);
  const card = dialog.getByRole('region', { name: 'Site check' });
  await expect(card.locator('[data-check=domain_proof]')).toHaveAttribute('data-ok', 'false');
  await expect(card.locator('[data-check=domain_proof]')).toContainText(`lists ${VENDOR_D}, not the payee ${VENDOR_E}`);
  await expect(card.locator('.site-verdict')).toContainText('Verdict: Blocked');
  await expect(card.locator('.site-trust-note .site-trust')).toHaveText('Blocked');

  await dialog.getByRole('button', { name: 'Add to my sites' }).click();
  const alert = dialog.getByRole('alert');
  await expect(alert).toContainText('This site is blocked: The site asks you to pay an address its own xrp-ledger.toml does not list.');
  await expect(alert).toContainText('It is in your sites as blocked');
  await expect(sitesSection(page).locator('.site-row[data-trust=blocked]')).toHaveCount(1);
  await alert.getByRole('button', { name: 'See the blocked site' }).click();

  const detail = page.locator('.site-detail');
  await expect(detail).toHaveAttribute('data-trust', 'blocked');
  const why = detail.getByRole('note', { name: 'Why it is blocked' });
  await expect(why).toContainText('The site asks you to pay an address its own xrp-ledger.toml does not list.');
  await expect(why.locator('[data-evidence=checks]')).toContainText(`not the payee ${VENDOR_E}`);
  await expect(why).toContainText('by an automatic check');
  await expect(detail.getByRole('button')).toHaveText(['Remove from my sites']);
  expect(errors).toEqual([]);
});

test('a USDC-only paywall is refused with what it wants', async ({ page }) => {
  const { service, errors } = await setup(page);
  await page.goto('/');
  const dialog = await checkSite(page, USDC_URL);
  const card = dialog.getByRole('region', { name: 'Site check' });
  const notice = card.getByRole('alert');
  await expect(notice.locator('.site-notice-heading')).toHaveText('cereal can’t pay localhost');
  await expect(notice).toContainText(USDC_REASON);
  await expect(card.locator('.site-verdict, .site-checks, .site-trust')).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Add to my sites' })).toHaveCount(0);  // no dead end: it can't be added
  expect(service.sites).toHaveLength(0);
  await expect(sitesSection(page).getByRole('button', { name: 'Add your first site' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('a site behind a bot wall says so plainly, and offers its public archived copy', async ({ page }) => {
  const { service, errors } = await setup(page);
  await page.goto('/');
  // Typed in the composer: the check runs right away, so the answer is the first thing shown.
  await page.getByRole('textbox', { name: 'Describe a new wallet in plain English' }).fill(WALLED_URL);
  await page.getByRole('textbox', { name: 'Describe a new wallet in plain English' }).press('Enter');
  const dialog = addDialog(page);
  const card = dialog.getByRole('region', { name: 'Site check' });
  const notice = card.getByRole('alert');
  await expect(notice.locator('.site-notice-heading')).toHaveText('www.gatorade.com blocks AI agents');
  await expect(notice).toContainText('Cloudflare’s bot protection');
  await expect(notice).toContainText('won’t try to get around it');
  await expect(notice).toContainText('Nothing was paid.');
  await expect(card.locator('.site-card-head strong')).toHaveText('www.gatorade.com');  // not the wall's "Just a moment..."
  await expect(dialog.getByRole('button', { name: 'Add to my sites' })).toHaveCount(0);
  await notice.getByRole('button', { name: 'Use the archived copy' }).click();
  await expect(dialog.getByLabel('Site address')).toHaveValue(ARCHIVE_URL);
  await expect(card.locator('.site-kind')).toHaveText('Free page');
  await dialog.getByRole('button', { name: 'Add to my sites' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'added to your sites as free' })).toBeVisible();
  expect(service.sites.map(s => s.url)).toEqual([ARCHIVE_URL]);
  expect(errors).toEqual([]);
});

test('a free site opens as plain text, and can be removed', async ({ page }) => {
  const { service, errors } = await setup(page);
  await page.goto('/');
  const dialog = await checkSite(page, 'example.com');
  await expect(dialog.getByLabel('Site address')).toHaveValue(FREE_URL);
  await expect(dialog.locator('.site-kind')).toHaveText('Free page');
  await expect(dialog.locator('.site-trust-note')).toContainText('Nothing to pay: cereal reads the page directly.');
  await dialog.getByRole('button', { name: 'Add to my sites' }).click();

  const detail = page.locator('.site-detail');
  await expect(detail.getByRole('heading', { level: 1 })).toHaveText('Example Domain');
  await expect(detail.locator('.site-trust').first()).toHaveText('Free');
  await expect(detail.getByRole('button', { name: /Buy/ })).toHaveCount(0);
  await detail.getByRole('button', { name: 'Open page' }).click();
  const text = detail.getByLabel('Page text');
  await expect(detail.getByRole('heading', { name: 'Example Domain', level: 2 })).toBeVisible();
  await expect(text).toContainText('This domain is for use in documentation examples.');
  await expect(text).toContainText('<script>alert("x")</script> <b>not bold</b>');  // shown as text, never as markup
  await expect(text.locator('b, script')).toHaveCount(0);
  await expect(detail.locator('.site-page .site-meta').first()).toHaveText(/^1,256 bytes · text\/html; charset=utf-8 · HTTP 200 · Truncated: showing the first 20,000 characters$/);

  await detail.getByRole('button', { name: 'Remove from my sites' }).click();
  await expect(detail.getByRole('heading', { level: 1 })).toHaveText('Example Domain was removed');
  expect(service.sites).toHaveLength(0);
  await expect(sitesSection(page).locator('.site-row')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('buy a private site: the Ledger approves, the run pays, the content and its proof are shown', async ({ page }) => {
  const { service, errors } = await setup(page);
  const site = service.site(D_URL);
  await page.goto('/');
  await sitesSection(page).getByRole('button', { name: /^Open localhost:8004/ }).click();
  const detail = page.locator('.site-detail');
  const purchase = detail.getByRole('region', { name: 'Purchase' });
  await expect(purchase).toContainText('Your Ledger approves the budget and signs the payment.');
  await expect(purchase.getByLabel('Speculos emulator: approve / reject')).toHaveValue('approve');
  await purchase.getByRole('button', { name: 'Buy with a new wallet' }).click();

  await expect(purchase.getByRole('status')).toContainText('Waiting for your Ledger to approve the budget…');
  await expect(purchase.getByRole('button', { name: 'Buy with a new wallet' })).toHaveCount(0);
  await expect(purchase.getByRole('status')).toContainText(/Running · \d+:\d\d/);
  await expect(purchase.getByRole('status')).toContainText('Your Ledger signs the payment. Nothing is shown as paid until the ledger validates it.');
  await expect(purchase.getByRole('status').getByRole('button', { name: 'Open the wallet' })).toBeVisible();
  expect(service.buys).toHaveLength(1);
  expect(service.buys[0]).toMatchObject({ speculos_decision: 'approve' });
  expect(String(service.buys[0].request_id)).toMatch(/^[0-9a-f-]{36}$/);

  await expect(purchase).toHaveAttribute('data-phase', 'delivered', { timeout: 20_000 });
  const proof = purchase.getByLabel('Payment proof');
  await expect(proof).toContainText('Paid 0.10 RLUSD · Signed by your Ledger');
  await expect(proof.getByRole('link', { name: 'Payment on the ledger' })).toHaveAttribute('href', tx(PAID_HASH));
  const content = purchase.getByLabel('Delivered content');
  await expect(content).toContainText('"title": "Vendor D research report"');
  await expect(content).toContainText('"<b>not markup</b>"');
  await expect(content.locator('b')).toHaveCount(0);
  await expect(purchase.getByRole('button', { name: 'Buy again with a new wallet' })).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/delivered-content.png` });

  // A second purchase is a new attempt with its own request id; rejected on the Ledger, it leaves the delivery shown.
  await purchase.getByLabel('Speculos emulator: approve / reject').selectOption('reject');
  await purchase.getByRole('button', { name: 'Buy again with a new wallet' }).click();
  await expect(purchase.getByRole('status')).toContainText('Waiting for your Ledger to approve the budget…');
  await expect(purchase.getByRole('alert')).toHaveText('Rejected on your Ledger. Nothing was sent.');
  await expect(purchase.getByLabel('Delivered content')).toContainText('Vendor D research report');
  expect(service.buys).toHaveLength(2);
  expect(service.buys[1].request_id).not.toBe(service.buys[0].request_id);
  expect(site.wallets).toEqual(['d_site1']);
  await proof.getByRole('button', { name: 'Open the wallet' }).click();
  await expect(page.locator('.wallet-detail.is-live')).toBeVisible();
  await expect(page.locator('.site-detail')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('paid but not delivered: the evidence is shown and the site is blocked', async ({ page }) => {
  const { service, errors } = await setup(page);
  service.site(E_URL);
  await page.goto('/');
  await sitesSection(page).getByRole('button', { name: /^Open localhost:8005/ }).click();
  const detail = page.locator('.site-detail');
  const purchase = detail.getByRole('region', { name: 'Purchase' });
  await purchase.getByRole('button', { name: 'Buy with a new wallet' }).click();
  await expect(purchase.getByRole('status')).toContainText(/Running · \d+:\d\d/);

  await expect(purchase).toHaveAttribute('data-phase', 'not_delivered', { timeout: 20_000 });
  const note = purchase.locator('.site-not-delivered');
  await expect(note).toContainText('The site was paid but did not deliver. 0.10 RLUSD was paid and nothing came back.');
  await expect(note).toContainText('cereal blocked this site: nobody can pay it again.');
  await expect(note).toContainText('The vendor answered 500 after the payment validated.');
  await expect(note.getByRole('link', { name: 'Payment on the ledger' })).toHaveAttribute('href', tx(LOST_HASH));
  await expect(purchase.getByRole('status')).toHaveCount(0);  // never left looking pending or paid-and-delivered

  // The site re-reads as blocked: its evidence links the payment, and only Remove is left.
  await expect(detail).toHaveAttribute('data-trust', 'blocked');
  const why = detail.getByRole('note', { name: 'Why it is blocked' });
  await expect(why).toContainText('The site took a payment and did not deliver what was paid for.');
  await expect(why.locator('[data-evidence=hash] a')).toHaveAttribute('href', tx(LOST_HASH));
  await expect(why.locator('[data-evidence=amount]')).toContainText('0.10 RLUSD');
  await expect(why).toContainText('by the delivery check');
  await expect(detail.getByRole('button', { name: /Buy/ })).toHaveCount(0);
  await expect(detail.getByRole('button', { name: 'Remove from my sites' })).toBeVisible();
  await expect(sitesSection(page).locator('.site-row[data-trust=blocked]')).toHaveCount(1, { timeout: 5_000 });
  expect(errors).toEqual([]);
});

test('reopening a site shows its last delivery, settling until the ledger validates the payment', async ({ page }) => {
  const { service, errors } = await setup(page);
  const site = service.site(D_URL);
  service.wallets.push({ id: 'd_old', task: 'Buy', budget: '0.12', currency: 'RLUSD', allowed_payees: [VENDOR_D], expires_at: now(), status: 'reclaimed', balance: '0' });
  (site.wallets as string[]).push('d_old');
  service.runs.d_old = { polls: 5, site: site.id as string };
  service.settlingReads = 2;  // delivered, but the ledger has not validated the payment yet
  await page.goto('/');
  await sitesSection(page).getByRole('button', { name: /^Open localhost:8004/ }).click();
  const purchase = page.locator('.site-detail').getByRole('region', { name: 'Purchase' });
  await expect(purchase).toHaveAttribute('data-phase', 'delivered');
  const proof = purchase.getByLabel('Payment proof');
  await expect(proof).toHaveAttribute('data-payment-state', 'pending');
  await expect(proof).toContainText('Payment of 0.10 RLUSD settling on the ledger…');
  await expect(proof).not.toContainText('Paid');
  await expect(proof).toHaveAttribute('data-payment-state', 'settled', { timeout: 10_000 });
  await expect(proof).toContainText('Paid 0.10 RLUSD · Signed by your Ledger');
  await expect(proof.getByRole('link', { name: 'Payment on the ledger' })).toHaveAttribute('href', tx(PAID_HASH));
  expect(errors).toEqual([]);
});

test('mobile: the site list and a site view fit the screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { service, errors } = await setup(page);
  service.site(F_URL, { trust: 'blocked', blocked_reason: 'The site asks you to pay an address its own xrp-ledger.toml does not list.' });
  service.site(D_URL);
  await page.goto('/');
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await sitesSection(page).getByRole('button', { name: /^Open localhost:8004/ }).click();
  const detail = page.locator('.site-detail');
  await expect(detail.getByRole('button', { name: 'Buy with a new wallet' })).toBeVisible();
  await expect(page.locator('.sidebar')).toBeHidden();
  const overflow = await page.evaluate(() => {
    const content = document.querySelector('.workspace-content')!;
    return { page: document.documentElement.scrollWidth - window.innerWidth, content: content.scrollWidth - content.clientWidth };
  });
  expect(overflow).toEqual({ page: 0, content: 0 });
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/mobile-site.png`, fullPage: true });
  await detail.getByRole('button', { name: 'Remove from my sites' }).scrollIntoViewIfNeeded();
  await expect(page.locator('.composer')).toBeVisible();
  expect(errors).toEqual([]);
});
