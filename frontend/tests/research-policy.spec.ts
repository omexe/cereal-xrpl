import { test, expect } from '@playwright/test';
import { advanceResearch, cancelResearch, decidePayment, reconcilePayments, resetResearchWallet, startResearch, resolveWalletFromPrompt } from '../src/researchDemo';
import type { Workspace } from '../src/wallets';

const researchConstraints = { spend: 20, days: 2, merchants: ['Ledger Lens', 'Venture Atlas', 'Open Ledger Index'], approval: 5, sweep: false };
const now = Date.parse('2026-10-25T00:00:00Z');
function fixture(): Workspace {
  return { folders: [], wallets: [{ id: 'research', name: 'XRP research', mockDataVersion: 1, balance: 20, createdAt: new Date(now).toISOString(), archived: false, transactions: [], constraints: structuredClone(researchConstraints) }] };
}
function atFunding(state: Workspace) {
  const id = startResearch(state, 'research', 'Research XRPL', now);
  for (let step = 1; step <= 5; step++) advanceResearch(state, id, now + step * 2000);
  return { id, pending: state.demoPayments!.find(payment => payment.sourceId === 'funding')! };
}

test('public sources never request payment; automatic, fraud, and pending outcomes honor owner policy', () => {
  const state = fixture();
  const id = startResearch(state, 'research', 'Research XRPL', now);
  advanceResearch(state, id, now + 2000); advanceResearch(state, id, now + 4000);
  expect(state.demoPayments).toBeUndefined();
  for (const time of [6000, 8000, 10000]) advanceResearch(state, id, now + time);
  expect(state.demoPayments?.map(payment => [payment.sourceId, payment.status])).toEqual([['landscape', 'paid'], ['fraud', 'blocked'], ['funding', 'pending']]);
  expect(state.wallets[0].balance).toBe(18.8);
  expect(state.wallets[0].transactions).toHaveLength(1);
  expect(state.researchRuns?.[0].status).toBe('waiting');
});

test('approval charges once, duplicate ticks do not repeat payments, and final totals reconcile', () => {
  const state = fixture(); const { id, pending } = atFunding(state);
  decidePayment(state, pending.id, true, now + 12000);
  decidePayment(state, pending.id, true, now + 12000);
  for (const time of [12000, 14000, 16000, 18000]) {
    advanceResearch(state, id, now + time); advanceResearch(state, id, now + time);
  }
  expect(state.wallets[0].balance).toBe(10.65);
  expect(state.wallets[0].transactions).toHaveLength(3);
  expect(state.researchRuns?.[0].status).toBe('complete');
  expect(pending.approvedBy).toBe('owner');
  expect(state.wallets[0].constraints).toEqual(researchConstraints);
});

test('denial and cancellation never debit pending funds', () => {
  const state = fixture(); const { id, pending } = atFunding(state);
  decidePayment(state, pending.id, false, now + 12000);
  decidePayment(state, pending.id, true, now + 12001);
  expect(pending.status).toBe('denied'); expect(state.wallets[0].balance).toBe(18.8);
  const second = fixture(); const other = atFunding(second);
  cancelResearch(second, other.id, now + 12000);
  decidePayment(second, other.pending.id, true, now + 12001);
  advanceResearch(second, other.id, now + 16000);
  expect(second.wallets[0].balance).toBe(18.8); expect(other.pending.status).toBe('cancelled');
  expect(second.researchRuns?.[0].status).toBe('cancelled');
  advanceResearch(state, id, now + 12000);
  expect(state.researchRuns?.[0].status).toBe('running');
});

for (const [name, code, change] of [
  ['lowered budget', 'budget_exceeded', (state: Workspace) => { state.wallets[0].constraints.spend = 2; }],
  ['insufficient funds', 'insufficient_balance', (state: Workspace) => { state.wallets[0].balance = 1; }],
  ['archived wallet', 'wallet_archived', (state: Workspace) => { state.wallets[0].archived = true; }],
  ['removed merchant', 'merchant_not_allowed', (state: Workspace) => { state.wallets[0].constraints.merchants = ['Ledger Lens']; }],
  ['expired wallet', 'wallet_expired', (state: Workspace) => { state.wallets[0].createdAt = new Date(now - 3 * 86400000).toISOString(); }],
] as const) {
  test(`approval rechecks ${name} and cannot bypass the rule`, () => {
    const state = fixture(); const { pending } = atFunding(state); change(state);
    const balance = state.wallets[0].balance;
    decidePayment(state, pending.id, true, now + 12000);
    expect(pending.status).toBe('blocked'); expect(pending.code).toBe(code);
    expect(state.wallets[0].balance).toBe(balance); expect(state.wallets[0].transactions).toHaveLength(1);
  });
}

test('exact threshold and budget boundaries are allowed; a funded balance cannot override the cap', () => {
  const state = fixture(); state.wallets[0].constraints.approval = 1.2; state.wallets[0].constraints.spend = 1.2;
  atFunding(state);
  expect(state.demoPayments?.[0].status).toBe('paid');
  expect(state.demoPayments?.[2].code).toBe('budget_exceeded');
  expect(state.wallets[0].balance).toBe(18.8);
});

test('fraud blocks even if the owner includes the merchant in the allowlist', () => {
  const state = fixture(); state.wallets[0].constraints.merchants.push('Token Insider');
  atFunding(state);
  expect(state.demoPayments?.find(payment => payment.sourceId === 'fraud')?.code).toBe('vendor_revoked');
});

test('policy changes proactively resolve pending requests; duplicate active sessions are rejected', () => {
  const state = fixture(); const { pending } = atFunding(state);
  expect(() => startResearch(state, 'research', 'Another research', now)).toThrow('already has an active');
  state.wallets[0].constraints.spend = 2; reconcilePayments(state, now + 12000);
  expect(pending.status).toBe('blocked');
});

test('owner opt-in sweep returns remaining funds once, closes wallet, and reset preserves other wallets', () => {
  const state = fixture(); state.wallets[0].constraints.sweep = true;
  state.wallets.push({ ...structuredClone(state.wallets[0]), id: 'other' });
  const other = structuredClone(state.wallets[1]);
  const { id, pending } = atFunding(state); decidePayment(state, pending.id, true, now + 12000);
  for (const time of [12000, 14000, 16000, 18000]) advanceResearch(state, id, now + time);
  expect(state.wallets[0].balance).toBe(0); expect(state.wallets[0].demoReturnedBalance).toBe(10.65);
  expect(() => startResearch(state, 'research', 'Another research', now + 20000)).toThrow('active wallet');
  resetResearchWallet(state, 'research');
  expect(state.wallets[0].balance).toBe(20); expect(state.wallets[0].transactions).toEqual([]);
  expect(state.wallets[0].constraints.sweep).toBe(true); expect(state.wallets[0].demoClosedAt).toBeUndefined();
  expect(state.demoPayments).toEqual([]); expect(state.researchRuns).toEqual([]); expect(state.wallets[1]).toEqual(other);
});

for (const prompt of ['Use my XRP research wallet.', 'Research XRPL. If needed, use our XRP research cereal wallet.', 'Use my "XRP research" wallet for payments.', 'Use wallet named "XRP research".', 'Use my xrp RESEARCH wallet.']) {
  test(`wallet resolution: ${prompt}`, () => {
    expect(resolveWalletFromPrompt(fixture(), prompt).walletId).toBe('research');
  });
}

test('wallet resolution refuses a missing name, duplicate names, and substring matches', () => {
  const state = fixture();
  expect(resolveWalletFromPrompt(state, 'Research XRPL.').walletId).toBeUndefined();
  expect(resolveWalletFromPrompt(state, 'Use my XRP wallet.').walletId).toBeUndefined();
  state.wallets.push({ ...structuredClone(state.wallets[0]), id: 'duplicate' });
  expect(resolveWalletFromPrompt(state, 'Use my XRP research wallet.').walletId).toBeUndefined();
  expect(resolveWalletFromPrompt(state, 'Use my XRP research wallet.').candidates).toHaveLength(2);
});

test('reset reverses only research spending, preserving old transactions, top-ups, policy and duration', () => {
  const state = fixture();
  const previous = { id: 'previous', title: 'Previous purchase', merchant: 'Ledger Lens', amount: 2, durationSeconds: 1, timestamp: new Date(now - 1000).toISOString() };
  state.wallets[0].transactions = [previous];
  const createdAt = state.wallets[0].createdAt;
  atFunding(state);
  state.wallets[0].balance += 10; // a separate human top-up must survive reset
  resetResearchWallet(state, 'research');
  expect(state.wallets[0].transactions).toEqual([previous]);
  expect(state.wallets[0].balance).toBe(30);
  expect(state.wallets[0].createdAt).toBe(createdAt);
  expect(state.wallets[0].constraints).toEqual(researchConstraints);
  resetResearchWallet(state, 'research');
  expect(state.wallets[0].balance).toBe(30);
});
