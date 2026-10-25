import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, describeError, type ApiRecord, type FundRequest, type FundResult, type Refusal } from '../api';
import type { AppActions } from '../appActions';
import { explorerTx, formatAmount, sumDecimals } from '../format';
import { isLive } from '../mode';
import { Dialog } from './Dialog';

/** A04: Add funds. Mock: changes the demo balance only. Live: an owner-approved top-up on testnet. */
export function FundsDialog({ app }: { app: AppActions }) {
  const selected = app.selected!;
  if (isLive) return <LiveFundsDialog app={app} />;
  return <Dialog title="Add demo funds" onClose={app.close}><form onSubmit={event => {
    event.preventDefault(); const amount = Number(new FormData(event.currentTarget).get('amount'));
    if (!Number.isFinite(amount) || amount <= 0 || amount > 1000000) return;
    app.updateWallet(selected.id, { balance: Math.round((selected.balance + amount) * 100) / 100 }); app.close(); app.notify('Demo balance updated. No payment was made.');
  }}><p className="dialog-description">Available balance: {formatAmount(selected.balance)}. This changes the demo balance only.</p>{app.isHome && <label>Wallet to fund<select value={app.selectedId} onChange={event => app.setSelectedId(event.target.value)}>{app.activeWallets.map(wallet => <option key={wallet.id} value={wallet.id}>{wallet.name}</option>)}</select></label>}<label>Amount (USD)<input name="amount" type="number" min="0.01" max="1000000" step="0.01" placeholder="100.00" required autoFocus /></label><button className="primary-button form-submit">Add demo funds</button></form></Dialog>;
}

/** RLUSD as typed: digits, at most 6 decimal places (the backend's rule), above zero. */
const AMOUNT = /^\d{1,15}(\.\d{1,6})?$/;
const validAmount = (amount: string) => AMOUNT.test(amount) && /[1-9]/.test(amount);
/** "0.250" and "00.25" are the same top-up as "0.25" (the backend normalizes the same way). */
function normalizeAmount(amount: string): string {
  const [whole, frac = ''] = amount.split('.');
  const kept = frac.replace(/0+$/, '');
  return `${whole.replace(/^0+(?=\d)/, '')}${kept ? `.${kept}` : ''}`;
}
const atLeastZero = (value: string) => value.startsWith('-') ? '0' : value;
const smaller = (a: string, b: string) => sumDecimals([a, `-${b}`]).startsWith('-') ? a : b;

/** The attempt whose outcome has not arrived yet (in flight, or its reply was lost). It lives outside the dialog, so
 * closing and reopening Add funds and trying the same top-up again reuses its request_id: the service then returns the
 * original result instead of asking the Ledger, and paying, a second time. */
let openAttempt: { key: string; id: string } | null = null;

/** The live top-up: the owner's Ledger approves a main wallet → subwallet payment; cereal raises the wallet's trust line
 * to the new budget, then submits the approved payment. Nothing moves without the approval, and nothing here retries. */
function LiveFundsDialog({ app }: { app: AppActions }) {
  const fundable = app.workspace.wallets.filter(w => !w.archived && w.live?.status === 'active');
  const wallet = fundable.find(w => w.id === app.selectedId);
  const [amount, setAmount] = useState('');
  const [decision, setDecision] = useState<'approve' | 'reject'>('approve');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  // From Home the selection may be a wallet that cannot take funds (deploying, finished): offer the first one that can.
  useEffect(() => {
    if (app.isHome && !wallet && fundable[0]) app.setSelectedId(fundable[0].id);
  }, [app, wallet, fundable]);

  const value = amount.trim();
  const valid = validAmount(value);
  const caps = app.live.main?.caps;
  const budget = wallet?.live?.budget;
  // The room this wallet has: under the per-wallet cap, and under what is left of the cap across active wallets.
  const room = caps && budget !== undefined && app.live.main ? smaller(
    atLeastZero(sumDecimals([String(caps.MAX_SUBAGENT_BUDGET), `-${budget}`])),
    atLeastZero(sumDecimals([String(caps.MAX_OUTSTANDING_BUDGET), `-${app.live.main.outstanding_budget}`]))) : undefined;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !wallet || !valid) return;
    const key = `${wallet.id}|${normalizeAmount(value)}`;
    if (openAttempt?.key !== key) openAttempt = { key, id: crypto.randomUUID() };
    const attempt = openAttempt;
    const body: FundRequest = { amount: value, request_id: attempt.id, ...(import.meta.env.DEV ? { speculos_decision: decision } : {}) };
    const name = wallet.name;
    setBusy(true); setError(null);
    try {
      const out = await api.fund(wallet.id, body) as FundResult & { wallet?: ApiRecord };
      if (openAttempt === attempt) openAttempt = null;
      if (out.wallet) app.live.upsert(out.wallet);
      app.notify(`Added ${formatAmount(out.amount)} to ${name}, approved on your Ledger. Budget ${formatAmount(out.budget)}. Funding transaction: ${explorerTx(out.hashes.fund)}`);
      if (mounted.current) app.close(); // closed meanwhile: never close whatever dialog is open now
      void app.live.refresh();
    } catch (e) {
      // A refusal is final, so the next click is a new attempt; except request_pending, whose outcome is still coming.
      // Anything else (the reply never arrived) keeps the id too: retrying the same amount cannot pay twice.
      if (e instanceof ApiError && e.kind === 'refused' && e.refused !== 'request_pending' && openAttempt === attempt) openAttempt = null;
      if (mounted.current) setError(fundError(e));
      else app.notify(`${name}: ${fundError(e)}`, true);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return <Dialog title="Add funds" onClose={app.close}><form onSubmit={submit} aria-busy={busy}>
    <p className="dialog-description">Your Ledger approves this payment from the main wallet; nothing moves without it.</p>
    {app.isHome && <label>Wallet to fund<select value={wallet?.id ?? ''} disabled={busy || !fundable.length}
      onChange={event => { app.setSelectedId(event.target.value); setError(null); }}>
      {!fundable.length && <option value="">No active wallets</option>}
      {fundable.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
    </select></label>}
    {wallet?.live ? <dl className="funds-facts" aria-label={`${wallet.name} funds`}>
      <div><dt>Available</dt><dd data-fact="available">{formatAmount(wallet.live.available)}</dd></div>
      <div><dt>Budget</dt><dd data-fact="budget">{formatAmount(wallet.live.budget)}</dd></div>
      <div><dt>Room left</dt><dd data-fact="room" title={caps ? `Company caps: ${formatAmount(String(caps.MAX_SUBAGENT_BUDGET))} per wallet, ${formatAmount(String(caps.MAX_OUTSTANDING_BUDGET))} across active wallets` : undefined}>{formatAmount(room)}</dd></div>
    </dl> : <p className="funds-error" role="alert">This wallet is not active, so it cannot take funds.</p>}
    <label>Amount (RLUSD)<input name="amount" inputMode="decimal" autoComplete="off" placeholder="0.25" required autoFocus
      value={amount} disabled={busy} aria-invalid={!!value && !valid} aria-describedby={value && !valid ? 'funds-amount-hint' : undefined}
      onChange={event => { setAmount(event.target.value); setError(null); }} /></label>
    {value && !valid && <p id="funds-amount-hint" className="funds-error">Enter a positive amount with at most 6 decimal places.</p>}
    {import.meta.env.DEV && <label>Speculos emulator<select value={decision} disabled={busy}
      onChange={event => setDecision(event.target.value === 'reject' ? 'reject' : 'approve')}>
      <option value="approve">Approve</option><option value="reject">Reject</option>
    </select></label>}
    {busy && <p className="funds-progress" role="status">Waiting for your approval on the Ledger. After you approve, cereal raises the wallet’s limit and sends the payment; this can take a minute.</p>}
    {error && <p className="funds-error" role="alert">{error}</p>}
    <button className="primary-button form-submit" disabled={busy || !wallet || !valid}>Approve on Ledger</button>
  </form></Dialog>;
}

/** What went wrong, in the owner's words; every refusal states whether anything was sent. */
function fundError(error: unknown): string {
  if (!(error instanceof ApiError) || error.kind !== 'refused') {
    return `${describeError(error)} If you approved on the Ledger, check the wallet first: trying again with the same amount will not pay twice.`;
  }
  const body = error.body as Refusal;
  const text = (key: string) => body[key] === undefined || body[key] === null ? undefined : String(body[key]);
  switch (body.refused) {
    case 'owner_rejected': return 'Rejected on the Ledger. Nothing was sent.';
    case 'cap_exceeded': return body.cap === 'MAX_OUTSTANDING_BUDGET'
      ? `That is above the company cap of ${formatAmount(text('limit'))} across all active wallets; room left is ${formatAmount(text('room'))}. Nothing was sent.`
      : `That is above the company cap of ${formatAmount(text('limit'))} per wallet; room left is ${formatAmount(text('room'))}. Nothing was sent.`;
    case 'insufficient_main_balance': return `The main wallet holds ${formatAmount(text('rlusd'))}, less than ${formatAmount(text('requested'))}. Nothing was sent.`;
    case 'device_unavailable': return 'The Ledger is not connected. Connect it and try again. Nothing was sent.';
    case 'device_required': return 'Top-ups need the owner’s Ledger, and device funding is off on this service. Nothing was sent.';
    case 'device_timeout': return 'The Ledger did not answer in time. Nothing was sent.';
    case 'invalid_amount': return 'Enter a positive RLUSD amount with at most 6 decimal places.';
    case 'trustline_failed': return `The wallet’s limit could not be raised (${text('result') ?? 'not validated'}). The payment was not sent.`;
    case 'funding_failed': return `The approved payment did not validate (${text('result') ?? 'unknown'}). The wallet’s budget is unchanged.`;
    case 'request_pending': return 'The approved payment is still settling on the ledger. Try again in a minute to see its outcome; nothing new will be sent.';
    case 'topup_error': return 'Something failed before the payment was sent. Nothing left the main wallet.';
    default: return error.message;
  }
}
