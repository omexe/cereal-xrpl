import { test, expect, type Page } from '@playwright/test';
import type { ApiRecord, Run } from '../src/api';
import { resolveWalletFromPrompt } from '../src/researchDemo';
import { toWorkspace } from '../src/live';

const wallet = (id: string, name: string): ApiRecord => ({
  id, name, task: 'Research markets', sentence: 'Spend up to 5 RLUSD only at Vendor A.',
  budget: '5', balance: '4.75', currency: 'RLUSD', allowed_payees: ['rVendorA'],
  expires_at: '2099-01-01T00:00:00Z', subwallet: 'rWallet', status: 'active',
  approval_threshold: '1', sweep_when_done: false, payments: [],
});
async function backend(page: Page) {
  const state = { wallets: [wallet('live-market', 'market sizing wallet')], run: null as Run | null,
    targets: [] as string[], posts: [] as { task: string; request_id: string }[], offline: false, dropResponse: false, refusal: null as Record<string, unknown> | null, delay: 0, aiReply: null as string | null, aiOffline: false, chatCalls: [] as { message: string; selected_wallet?: string; history: { role: string; content: string }[] }[] };
  await page.route('**/api/**', async route => {
    if (state.offline) return route.fulfill({ status: 503, json: { detail: 'Service unavailable' } });
    const path = new URL(route.request().url()).pathname.replace('/api', '');
    if (path === '/research/chat') {
      const body = route.request().postDataJSON(); state.chatCalls.push(body);
      if (state.aiOffline) return route.abort();
      if (state.aiReply) return route.fulfill({ json: { action: 'reply', reply: state.aiReply, wallet_id: null, task: null } });
      // Model stub for UI tests; production has no phrase-matching fallback.
      const match = resolveWalletFromPrompt(toWorkspace(state.wallets, [], []), body.message);
      const selected = match.walletId ?? (!match.explicit ? body.selected_wallet : undefined);
      if (!selected) return route.fulfill({ json: { action: 'reply', reply: match.message, wallet_id: null, task: null } });
      return route.fulfill({ json: { action: 'research', reply: 'I’ll retrieve the requested report.', wallet_id: selected, task: body.message } });
    }
    if (path === '/main') return route.fulfill({ json: { address: 'rMain', rlusd: '10', xrp: '100', policy: {}, caps: {}, recent_sweeps: [] } });
    if (path === '/vendors') return route.fulfill({ json: [{ name: 'Vendor A', address: 'rVendorA', items: [{ item: 'agenda', price: '0.15' }] }] });
    if (path === '/folders') return route.fulfill({ json: [] });
    if (path.endsWith('/run')) {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON(); state.posts.push(body); state.targets.push(path);
        if (state.dropResponse) return route.abort();
        if (state.delay) await new Promise(resolve => setTimeout(resolve, state.delay));
        if (state.refusal) return route.fulfill({ json: { ok: false, ...state.refusal } });
        state.run = { id: 'run-live', deployment: 'live-market', status: 'running', task: body.task,
          request_id: body.request_id, plan: { lines: [{ item: 'agenda', vendor: 'Vendor A', price: '0.15' }] } };
      }
      return route.fulfill({ json: { ok: true, run: state.run } });
    }
    if (path === '/subagents') return route.fulfill({ json: state.wallets.map(w => ({ ...w, run: state.run })) });
    return route.fulfill({ json: state.wallets.find(w => path.endsWith(w.id)) });
  });
  return state;
}

test('chat resolves live wallet name including wallet suffix and displays backend activity', async ({ page }) => {
  const state = await backend(page);
  state.wallets[0].payments = [{ to: 'rVendorA', amount: '0.25', ok: true, hash: 'A'.repeat(64), validated: false, resource: '/agenda' }];
  await page.goto('/test-chat');
  await expect(page.getByRole('button', { name: 'market sizing wallet' })).toBeVisible();
  await expect(page.getByText('XRP research', { exact: true })).toHaveCount(0);
  await expect(page.getByText('RLUSD RLUSD', { exact: false })).toHaveCount(0);
  const prompt = 'Get the agenda. Use my market sizing wallet.';
  await page.getByLabel('Research prompt').fill(prompt);
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByText('Cereal is running your task')).toBeVisible();
  expect(state.posts).toHaveLength(1); expect(state.posts[0].task).toBe(prompt);
  await expect(page.getByText('Pending — not settled yet')).toBeVisible();
  await expect(page.getByText('Settled', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'View wallet and rules in Cereal' })).toHaveAttribute('href', '/?wallet=live-market');
  expect(await page.evaluate(() => localStorage.getItem('cereal-test-v1'))).toBeNull();
  await page.reload();
  await expect(page.getByText('Cereal is running your task')).toBeVisible();
  expect(state.posts).toHaveLength(1);
  state.wallets[0].payments[0].validated = true;
  state.run!.status = 'succeeded'; state.run!.summary = 'Bought agenda from Vendor A.';
  state.run!.resources = [{ resource: '/market-data', title: 'Market research brief', sample: true, summary: 'Illustrative research', findings: ['Sample finding'] }];
  await expect(page.getByText('Task succeeded')).toBeVisible({ timeout: 10000 });
  await expect(page.getByLabel('Retrieved data')).toContainText('Market research brief');
  await expect(page.getByLabel('Retrieved data')).toContainText('Sample research data');
  await expect(page.getByText('Settled', { exact: true })).toBeVisible({ timeout: 10000 });
});

test('unknown name receives an AI clarification and a follow-up can select the wallet', async ({ page }) => {
  const state = await backend(page);
  await page.goto('/test-chat');
  await page.getByLabel('Research prompt').fill('Get agenda. Use my market sizing watch wallet.');
  await expect(page.getByRole('button', { name: 'Start research', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByText(/couldn’t find a wallet named/)).toBeVisible();
  expect(state.posts).toHaveLength(0);
  await page.getByLabel('Research prompt').fill('Get agenda. Use my market sizing wallet.');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByText('Cereal is running your task')).toBeVisible();
  expect(state.chatCalls[1].history[0].content).toContain('market sizing watch');
});

test('refresh discovers new wallets and excludes archived or expired wallets', async ({ page }) => {
  const state = await backend(page);
  await page.goto('/test-chat');
  await expect(page.getByRole('button', { name: 'market sizing wallet' })).toBeVisible();
  state.wallets = [wallet('new', 'New research'), { ...wallet('old', 'Archived research'), archived: true }, { ...wallet('expired', 'Expired research'), expires_at: '2000-01-01' }];
  await page.getByRole('button', { name: 'Refresh wallets' }).click();
  await expect(page.getByRole('button', { name: 'New research', exact: false }).filter({ has: page.locator('small') })).toBeVisible();
  await expect(page.getByRole('button', { name: 'market sizing wallet' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Archived research' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Expired research' })).toHaveCount(0);
  expect(state.posts).toHaveLength(0);
});

test('backend outage never falls back to fixture wallets', async ({ page }) => {
  const state = await backend(page); state.offline = true;
  await page.goto('/test-chat');
  await expect(page.getByText('Wallet connection unavailable.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start research', exact: true })).toBeDisabled();
  await expect(page.getByText('XRP research', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('cereal-test-v1'))).toBeNull();
});

test('uncertain response reuses request ID after a reload', async ({ page }) => {
  const state = await backend(page); state.dropResponse = true;
  await page.goto('/test-chat');
  await page.getByLabel('Research prompt').fill('Get agenda. Use my market sizing wallet.');
  await expect(page.getByRole('button', { name: 'Start research', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByLabel('Assistant response')).toContainText('couldn’t confirm the result');
  await page.reload(); state.dropResponse = false;
  await expect(page.getByRole('button', { name: 'Retry request', exact: true })).toBeEnabled();
  expect(state.posts).toHaveLength(1);
  await page.getByRole('button', { name: 'Retry request', exact: true }).click();
  await expect(page.getByText('Cereal is running your task')).toBeVisible();
  expect(state.posts).toHaveLength(2);
  expect(state.posts[1].request_id).toBe(state.posts[0].request_id);
});

test('duplicate live names require explicit selection', async ({ page }) => {
  const state = await backend(page); state.wallets.push(wallet('another', 'market sizing wallet'));
  await page.goto('/test-chat');
  await page.getByLabel('Research prompt').fill('Get agenda. Use my market sizing wallet.');
  await expect(page.getByRole('button', { name: 'Start research', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByText(/More than one wallet matches/)).toBeVisible();
  expect(state.posts).toHaveLength(0);
  await expect(page.locator('.user-message')).toHaveCount(1);
});

for (const scenario of [
  { refused: 'nothing_to_buy', expected: 'none of Cereal’s connected vendors offers it', rejected: undefined },
  { refused: 'no_trusted_vendor', expected: 'aren’t allowed by your wallet’s rules', rejected: { 'market-data': [{ vendor: 'Vendor C', reason: 'not_on_your_list' }] } },
  { refused: 'over_budget', expected: 'exceeds this wallet’s available budget', rejected: undefined },
]) test(`sent message receives a conversational ${scenario.refused} reply`, async ({ page }) => {
  const state = await backend(page); state.refusal = scenario; state.delay = 600;
  // An earlier run must not replace the newly refused request during polling.
  state.run = { id: 'old', deployment: 'live-market', status: 'succeeded', task: 'Old task', request_id: 'old-key' };
  await page.goto('/test-chat');
  const prompt = 'Research market data from Vendor A. Use my market sizing wallet.';
  await page.getByLabel('Research prompt').fill(prompt);
  await expect(page.getByRole('button', { name: 'Start research', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.locator('.user-message')).toHaveText(prompt);
  await expect(page.getByLabel('Research prompt')).toHaveValue('');
  await expect(page.getByLabel('Assistant response')).toContainText('checking the available sources');
  await expect(page.getByLabel('Assistant response')).toContainText(scenario.expected);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Curiosity, with a budget.' })).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel('Assistant response')).toContainText(scenario.expected);
  expect(state.posts).toHaveLength(1);
  await page.getByLabel('Research prompt').fill('Get speakers. Use my market sizing wallet.');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.locator('.user-message')).toHaveCount(2);
});


test('completed tasks accept follow-ups with the same wallet and retain earlier results after reload', async ({ page }) => {
  const state = await backend(page);
  await page.goto('/test-chat');
  await page.getByLabel('Research prompt').fill('Get agenda. Use my market sizing wallet.');
  await expect(page.getByRole('button', { name: 'Start research', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByText('Cereal is running your task')).toBeVisible();
  // AI questions may be sent while running; the server enforces one payment run at a time.
  await expect(page.getByLabel('Research prompt')).toBeEditable();
  await page.getByLabel('Research prompt').fill('Now get the speakers.');
  await expect(page.getByRole('button', { name: 'Start research', exact: true })).toBeEnabled();
  state.run!.status = 'succeeded'; state.run!.summary = 'First result: agenda retrieved.';
  state.run!.resources = [{ resource: '/agenda', title: 'First report', findings: ['First finding'] }];
  await expect(page.getByText('First finding', { exact: true })).toBeVisible({ timeout: 10000 });
  await page.getByLabel('Research prompt').press('Enter');
  await expect.poll(() => state.posts.length).toBe(2);
  expect(state.targets).toEqual(['/subagents/live-market/run', '/subagents/live-market/run']);
  expect(state.posts[1].request_id).not.toBe(state.posts[0].request_id);
  await expect(page.locator('.user-message')).toHaveCount(2);
  await expect(page.getByText('First finding', { exact: true })).toBeVisible();
  state.run!.status = 'succeeded'; state.run!.summary = 'Second result: speakers retrieved.';
  await expect(page.getByText('Second result: speakers retrieved.')).toBeVisible({ timeout: 10000 });
  await page.reload();
  await expect(page.locator('.user-message')).toHaveCount(2);
  await expect(page.getByText('First finding', { exact: true })).toBeVisible();
  await expect(page.getByText('Second result: speakers retrieved.')).toBeVisible();
  expect(state.posts).toHaveLength(2);
});

test('reclaimed wallet allows messages, explains returned funds, and can switch wallets without losing results', async ({ page }) => {
  const state = await backend(page);
  state.wallets[0] = { ...state.wallets[0], status: 'reclaimed', balance: '0', returned: '4.75', sweep_when_done: true };
  state.run = { id: 'first', request_id: 'first-key', deployment: 'live-market', status: 'succeeded', task: 'First research', summary: 'First report remains here.' };
  await page.goto('/test-chat');
  await page.getByRole('button', { name: 'market sizing wallet', exact: true }).click();
  await expect(page.getByText('First report remains here.')).toBeVisible();
  await expect(page.getByLabel('Wallet availability')).toContainText('returned 4.75 RLUSD');
  await page.getByLabel('Research prompt').fill('Now get the speakers.');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.locator('.user-message')).toHaveCount(2);
  await expect(page.getByLabel('Assistant response').last()).toContainText('can’t pay for another request');
  expect(state.posts).toHaveLength(0);
  state.wallets.push(wallet('second-wallet', 'Continuing research'));
  await page.getByLabel('Research prompt').fill('Get speakers. Use my Continuing research wallet.');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect.poll(() => state.posts.length).toBe(1);
  expect(state.targets[0]).toBe('/subagents/second-wallet/run');
  await expect(page.getByText('First report remains here.')).toBeVisible();
  await expect(page.locator('.user-message')).toHaveCount(3);
});

test('unknown explicit wallet in a follow-up never spends from the previous wallet', async ({ page }) => {
  const state = await backend(page);
  state.run = { id: 'first', request_id: 'first-key', deployment: 'live-market', status: 'succeeded', task: 'First research' };
  await page.goto('/test-chat');
  await page.locator('.chat-sidebar-section').getByRole('button', { name: 'market sizing wallet' }).click();
  await expect(page.getByText('Task succeeded')).toBeVisible();
  await page.getByLabel('Research prompt').fill('Get speakers. Use my Missing wallet.');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByText(/couldn’t find a wallet named/)).toBeVisible();
  expect(state.posts).toHaveLength(0);
});


test('AI answers arbitrary questions without a wallet or payment and gets conversation history', async ({ page }) => {
  const state = await backend(page); state.wallets = [];
  state.aiReply = 'Cereal checks vendor permissions before every payment.';
  await page.goto('/test-chat');
  await page.getByLabel('Research prompt').fill('hey how does any of this work?');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByLabel('Assistant response')).toContainText(state.aiReply);
  state.aiReply = 'The same rules also apply to follow-ups.';
  await page.getByLabel('Research prompt').fill('and what about next time?');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByLabel('Assistant response').last()).toContainText(state.aiReply);
  expect(state.chatCalls[1].history).toEqual([
    { role: 'user', content: 'hey how does any of this work?' },
    { role: 'assistant', content: 'Cereal checks vendor permissions before every payment.' },
  ]);
  expect(state.posts).toHaveLength(0);
  await page.reload();
  await expect(page.locator('.user-message')).toHaveCount(2);
});

test('AI outage sends a normal reply and never starts a payment', async ({ page }) => {
  const state = await backend(page); state.aiOffline = true;
  await page.goto('/test-chat');
  await page.getByLabel('Research prompt').fill('please pull some company information');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByLabel('Assistant response')).toContainText('No payment was started');
  expect(state.posts).toHaveLength(0);
  await expect(page.getByRole('button', { name: 'Retry request' })).toHaveCount(0);
});


test('out of funds is a normal reply and another request can still be sent', async ({ page }) => {
  const state = await backend(page);
  state.refusal = { refused: 'over_budget', remaining: '0' };
  await page.goto('/test-chat');
  await page.getByLabel('Research prompt').fill('Get agenda. Use my market sizing wallet.');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByLabel('Assistant response')).toContainText('out of funds');
  await expect(page.getByRole('alert')).toHaveCount(0);
  state.aiReply = 'You can add funds from the wallet page in Cereal.';
  await page.getByLabel('Research prompt').fill('how do I add funds?');
  await page.getByRole('button', { name: 'Start research', exact: true }).click();
  await expect(page.getByLabel('Assistant response').last()).toContainText(state.aiReply);
  expect(state.posts).toHaveLength(1);
  await expect(page.locator('.user-message')).toHaveCount(2);
});
