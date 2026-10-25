import type { Wallet, Workspace } from './wallets';
import { WALLET_PATH } from './mode';

export const RESEARCH_PROMPT = 'Do deep research on the XRPL product, browse multiple sites discovering docs, founder, raising information, etc. If needed, use our XRP research cereal wallet.';
// Fixed, fictional quotes and risk signals belong to Cereal's demo catalog, never to the chat request.
export const researchSources = [
  { id: 'docs', name: 'XRPL documentation', url: 'https://xrpl.org/docs', title: 'Explore the developer documentation', amount: 0, risk: 'public', detail: 'Documentation coverage: ledger architecture, payments, tokens, and developer tools.' },
  { id: 'background', name: 'XRPL overview', url: 'https://xrpl.org/about', title: 'Discover the ecosystem and its origins', amount: 0, risk: 'public', detail: 'Background coverage: the ledger’s origins, contributors, and the distinction between XRPL and companies building on it.' },
  { id: 'landscape', name: 'Ledger Lens', url: 'https://ledger-lens.example/xrpl/landscape', title: 'Unlock the XRPL product landscape', amount: 1.2, risk: 'trusted', detail: 'Illustrative dataset: infrastructure, payment applications, and tokenization projects.' },
  { id: 'fraud', name: 'Token Insider', url: 'https://token-insider.example/xrpl/private-rounds', title: 'Check a purported private funding database', amount: 0.8, risk: 'revoked', detail: 'Simulated fraud signal: merchant credential revoked after fraudulent billing reports.' },
  { id: 'funding', name: 'Venture Atlas', url: 'https://venture-atlas.example/reports/xrpl', title: 'Unlock the founders and funding report', amount: 7.5, risk: 'trusted', detail: 'Illustrative report: founder profiles, funding chronology, investor attribution, and source references.' },
  { id: 'index', name: 'Open Ledger Index', url: 'https://open-ledger-index.example/xrpl/ecosystem', title: 'Cross-check the ecosystem directory', amount: 0.65, risk: 'trusted', detail: 'Illustrative cross-check: project websites, documentation links, and company profiles.' },
] as const;

export type SourceId = typeof researchSources[number]['id'];
export type PaymentStatus = 'paid' | 'blocked' | 'pending' | 'denied' | 'cancelled';
export interface DemoPayment {
  id: string; runId: string; walletId: string; sourceId: SourceId;
  merchant: string; resource: string; title: string; amount: number;
  status: PaymentStatus; reason: string; code: string; createdAt: string; resolvedAt?: string;
  approvedBy?: 'owner';
}
export interface ResearchRun {
  id: string; walletId: string; prompt: string;
  status: 'running' | 'waiting' | 'complete' | 'cancelled';
  cursor: number; startedAt: string; nextAt: number; finishedAt?: string;
}
export const cents = (amount: number) => Math.round(amount * 100);
export const money = (amount: number) => `$${amount.toFixed(2)}`;
export const spending = (wallet: Wallet) => (wallet.transactions ?? []).reduce((sum, item) => sum + cents(item.amount), 0) / 100;
export const walletHref = (walletId?: string) => walletId ? `${WALLET_PATH}?wallet=${encodeURIComponent(walletId)}` : WALLET_PATH;

function refusal(wallet: Wallet | undefined, payment: DemoPayment, now: number): { code: string; reason: string } | null {
  const source = researchSources.find(item => item.id === payment.sourceId);
  if (!wallet) return { code: 'wallet_unavailable', reason: 'This research wallet is no longer available.' };
  if (wallet.archived) return { code: 'wallet_archived', reason: 'The owner archived this wallet in Cereal.' };
  if (wallet.demoClosedAt) return { code: 'wallet_closed', reason: 'Cereal returned the remaining funds and closed this demo wallet.' };
  if (!wallet.createdAt || !Number.isFinite(Date.parse(wallet.createdAt)) || now >= Date.parse(wallet.createdAt) + wallet.constraints.days * 86400000) return { code: 'wallet_expired', reason: 'The wallet’s spending window has expired.' };
  if (source?.risk === 'revoked') return { code: 'vendor_revoked', reason: source.detail };
  if (!source || source.risk !== 'trusted') return { code: 'unknown_vendor', reason: 'Cereal could not verify this demo merchant.' };
  if (!wallet.constraints.merchants.some(name => name.toLowerCase() === source.name.toLowerCase())) return { code: 'merchant_not_allowed', reason: 'This merchant is outside the wallet’s allowed merchants.' };
  if (cents(spending(wallet)) + cents(payment.amount) > cents(wallet.constraints.spend)) return { code: 'budget_exceeded', reason: 'This payment would exceed the wallet’s total spending limit.' };
  if (cents(payment.amount) > cents(wallet.balance)) return { code: 'insufficient_balance', reason: 'The wallet does not have enough available demo funds.' };
  return null;
}

function settle(wallet: Wallet, payment: DemoPayment, now: number, owner = false) {
  payment.status = 'paid'; payment.code = owner ? 'owner_approved' : 'policy_allowed';
  payment.reason = owner ? 'Approved by you in Cereal. Demo payment completed.' : 'Trusted demo merchant. Payment is within the wallet’s rules.';
  payment.resolvedAt = new Date(now).toISOString();
  if (owner) payment.approvedBy = 'owner';
  wallet.balance = (cents(wallet.balance) - cents(payment.amount)) / 100;
  wallet.transactions = [{ id: payment.id, title: payment.title, merchant: payment.merchant, amount: payment.amount, durationSeconds: 1, timestamp: payment.resolvedAt }, ...(wallet.transactions ?? [])];
}

/** Recheck hard policy gates after every wallet mutation; owner approval cannot bypass them. */
export function reconcilePayments(state: Workspace, now = Date.now()) {
  for (const payment of state.demoPayments ?? []) {
    if (payment.status !== 'pending') continue;
    const denied = refusal(state.wallets.find(wallet => wallet.id === payment.walletId), payment, now);
    if (denied) Object.assign(payment, denied, { status: 'blocked', resolvedAt: new Date(now).toISOString() });
  }
}

export function startResearch(state: Workspace, walletId: string, prompt: string, now = Date.now()): string {
  const wallet = state.wallets.find(item => item.id === walletId);
  if (!wallet || wallet.archived || wallet.demoClosedAt) throw new Error('Choose an active wallet in Cereal.');
  if (!wallet.createdAt || !Number.isFinite(Date.parse(wallet.createdAt)) || now >= Date.parse(wallet.createdAt) + wallet.constraints.days * 86400000) throw new Error('This wallet has expired. Choose another wallet in Cereal.');
  if (!prompt.trim() || prompt.length > 4000) throw new Error('Enter a research prompt of up to 4,000 characters.');
  if ((state.researchRuns ?? []).some(run => run.walletId === walletId && ['running', 'waiting'].includes(run.status))) throw new Error('This wallet already has an active research session. Open it from the chat history.');
  const id = crypto.randomUUID();
  (state.researchRuns ??= []).push({ id, walletId, prompt: prompt.trim(), status: 'running', cursor: 0, startedAt: new Date(now).toISOString(), nextAt: now + 1200 });
  return id;
}

/** One atomic step. All tabs can call this safely; a durable cursor and request ID prevent duplicate charges. */
export function advanceResearch(state: Workspace, runId: string, now = Date.now()) {
  const run = state.researchRuns?.find(item => item.id === runId);
  if (!run || run.status === 'complete' || run.status === 'cancelled') return;
  reconcilePayments(state, now);
  if (now < run.nextAt) return;
  const source = researchSources[run.cursor];
  if (!source) {
    run.status = 'complete'; run.finishedAt = new Date(now).toISOString();
    const wallet = state.wallets.find(item => item.id === run.walletId);
    if (wallet && !wallet.archived && wallet.constraints.sweep && !wallet.demoClosedAt) {
      wallet.demoReturnedBalance = (cents(wallet.demoReturnedBalance ?? 0) + cents(wallet.balance)) / 100;
      wallet.balance = 0; wallet.demoClosedAt = run.finishedAt;
    }
    return;
  }
  if (source.amount > 0) {
    const id = `${run.id}:${source.id}`;
    let payment = state.demoPayments?.find(item => item.id === id);
    if (!payment) {
      payment = { id, runId, walletId: run.walletId, sourceId: source.id, merchant: source.name, resource: source.url, title: source.title, amount: source.amount, status: 'pending', reason: '', code: '', createdAt: new Date(now).toISOString() };
      (state.demoPayments ??= []).push(payment);
      const wallet = state.wallets.find(item => item.id === run.walletId);
      const denied = refusal(wallet, payment, now);
      if (denied) Object.assign(payment, denied, { status: 'blocked', resolvedAt: new Date(now).toISOString() });
      else if (cents(payment.amount) > cents(wallet!.constraints.approval)) {
        payment.code = 'approval_required'; payment.reason = `Above your ${money(wallet!.constraints.approval)} automatic payment limit. Waiting for your decision in Cereal.`;
      } else settle(wallet!, payment, now);
    }
    if (payment.status === 'pending') { run.status = 'waiting'; return; }
  }
  run.cursor += 1; run.status = 'running'; run.nextAt = now + 1600;
}

export function decidePayment(state: Workspace, id: string, approve: boolean, now = Date.now()) {
  const payment = state.demoPayments?.find(item => item.id === id);
  if (!payment || payment.status !== 'pending') return;
  const wallet = state.wallets.find(item => item.id === payment.walletId);
  const denied = refusal(wallet, payment, now);
  if (denied) Object.assign(payment, denied, { status: 'blocked', resolvedAt: new Date(now).toISOString() });
  else if (!approve) Object.assign(payment, { status: 'denied', code: 'owner_denied', reason: 'You declined this payment in Cereal. No funds were spent.', resolvedAt: new Date(now).toISOString() });
  else settle(wallet!, payment, now, true);
}

export function cancelResearch(state: Workspace, id: string, now = Date.now()) {
  const run = state.researchRuns?.find(item => item.id === id);
  if (!run || ['complete', 'cancelled'].includes(run.status)) return;
  run.status = 'cancelled'; run.finishedAt = new Date(now).toISOString();
  for (const payment of state.demoPayments ?? []) {
    if (payment.runId === id && payment.status === 'pending') Object.assign(payment, { status: 'cancelled', code: 'research_cancelled', reason: 'Research stopped. Pending payment cancelled; no funds spent.', resolvedAt: run.finishedAt });
  }
}

/** Owner-only reset: reverse this tool's effects without replacing existing wallet history or policy. */
export function resetResearchWallet(state: Workspace, walletId: string) {
  const wallet = state.wallets.find(item => item.id === walletId);
  if (!wallet || wallet.archived) throw new Error('Select an active wallet.');
  const payments = (state.demoPayments ?? []).filter(payment => payment.walletId === walletId);
  const paid = payments.filter(payment => payment.status === 'paid');
  const ids = new Set(paid.map(payment => payment.id));
  wallet.balance = (cents(wallet.balance) + paid.reduce((total, payment) => total + cents(payment.amount), 0) + cents(wallet.demoReturnedBalance ?? 0)) / 100;
  wallet.transactions = (wallet.transactions ?? []).filter(transaction => !ids.has(transaction.id));
  delete wallet.demoClosedAt; delete wallet.demoReturnedBalance;
  state.demoPayments = (state.demoPayments ?? []).filter(payment => payment.walletId !== walletId);
  state.researchRuns = (state.researchRuns ?? []).filter(run => run.walletId !== walletId);
}

export interface WalletResolution { explicit: boolean; walletId?: string; message: string; candidates: Wallet[] }
const normalizeName = (name: string) => name.trim().replace(/^["“”']+|["“”']+$/g, '').replace(/\s+/g, ' ').toLocaleLowerCase();

/** Match explicit payment-wallet instructions by exact name, never the first wallet or a substring. */
export function resolveWalletFromPrompt(state: Workspace, prompt: string): WalletResolution {
  const names: string[] = [];
  const instructions = /\buse\s+(?:(?:my|our|the)\s+)?(?:cereal\s+)?wallet\s+(?:(?:named|called)\s+)?["“]([^"”]+)["”]|\buse\s+(?:(?:my|our|the)\s+)?["“]([^"”]+)["”](?:\s+(?:cereal\s+)?wallet)?|\buse\s+(?:(?:my|our|the)\s+)?([^.!?\n]+?)\s+(?:cereal\s+)?wallet\b/gi;
  for (const match of prompt.matchAll(instructions)) names.push(normalizeName(match[1] ?? match[2] ?? match[3]));
  const unique = [...new Set(names)];
  const matches = state.wallets.filter(wallet => unique.some(name => normalizeName(wallet.name) === name || normalizeName(wallet.name) === `${name} wallet`));
  if (unique.length === 1 && matches.length === 1) return { explicit: true, walletId: matches[0].id, message: '', candidates: matches };
  if (matches.length) return { explicit: true, message: 'Which wallet should I use for payments? More than one wallet matches your instruction.', candidates: matches.filter(wallet => !wallet.archived && !wallet.demoClosedAt) };
  return { explicit: unique.length > 0, message: unique.length ? `I couldn’t find a wallet named “${names[0]}”. Which existing wallet should I use?` : 'Which Cereal wallet should I use for payments? Name it in your prompt, for example: “Use my Apollo Research wallet.”', candidates: state.wallets.filter(wallet => !wallet.archived && !wallet.demoClosedAt) };
}
