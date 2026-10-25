import { useCallback, useEffect, useRef, useState } from 'react';
import { LinkExternal01 } from '@untitledui/icons';
import { api, ApiError, describeError, REFUSAL_TEXT, type ApiRecord, type Payment, type RecordRefusal, type Run } from '../api';
import type { AppActions } from '../appActions';
import { explorerTx, formatAmount, sumDecimals } from '../format';
import { paymentState, resourceTitle, vendorName, type LiveInfo } from '../live';
import type { Wallet } from '../wallets';

/** A01/A02/A07 (live only): start the wallet's task, follow the run, then done & sweep, reclaim, retire.
 * Every state shown here comes from the cereal service: a run's status from GET /subagents/{id}/run, money and
 * transactions from the wallet record. Nothing is called settled without a validated ledger result. */
export function WalletActions({ app, wallet }: { app: AppActions; wallet: Wallet }) {
  if (!wallet.live) return null;
  return <LiveWalletActions key={wallet.id} app={app} id={wallet.id} live={wallet.live} />;
}

const LIVE_RUN = ['starting', 'running'];
const POLL_MS = 3000;
const isLiveRun = (run?: Run | null) => !!run && LIVE_RUN.includes(run.status);

interface Step { step: string; ok?: boolean; hash?: string | null; result?: string }
interface Cleanup { ok: boolean; returned?: string; steps: Step[] }
type Busy = 'start' | 'done' | 'reclaim' | 'retire' | null;

const STEP_TEXT: Record<string, string> = {
  sweep: 'Swept to the main wallet', trustset_zero: 'Trust line closed', account_delete: 'Account deleted',
};
const RUN_TITLE: Record<Run['status'], string> = {
  starting: 'Starting', running: 'Running', succeeded: 'Task finished', failed: 'Task failed',
  timed_out: 'Task timed out', interrupted: 'Task interrupted',
};
const TOO_YOUNG = 'Too new to retire. cereal retires it automatically once it’s 256 ledgers old (~15 min).';

/** The newer of the run this view polled and the run on the wallet record. */
function pickRun(polled: Run | null, recorded: Run | null | undefined): Run | null {
  if (!polled) return recorded ?? null;
  if (!recorded) return polled;
  if (polled.id !== recorded.id) return Date.parse(polled.started_at ?? '') >= Date.parse(recorded.started_at ?? '') ? polled : recorded;
  return isLiveRun(polled) && !isLiveRun(recorded) ? recorded : polled;
}

function elapsed(from?: string | null, to?: string | number | null): string {
  const start = Date.parse(from ?? '');
  const end = typeof to === 'number' ? to : Date.parse(to ?? '');
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '0:00';
  const s = Math.max(0, Math.round((end - start) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Plain-English text for the refusals this panel can meet; anything else uses the shared table. */
function explain(error: unknown): string {
  if (!(error instanceof ApiError) || error.kind !== 'refused') return describeError(error);
  const body = (error.body ?? {}) as Record<string, unknown>;
  switch (error.refused) {
    case 'nothing_to_buy': return 'Nothing to buy: this wallet’s sentence doesn’t name anything a vendor sells (for example the agenda or the speaker list). Nothing was started.';
    case 'no_trusted_vendor': return `No vendor this wallet allows sells ${(body.items as string[] | undefined)?.join(' and ') ?? 'what it asks for'}. Nothing was started.`;
    case 'over_budget': return `The quotes come to ${formatAmount(body.requested as string)}, more than the ${formatAmount(body.remaining as string)} this wallet holds. Nothing was started.`;
    case 'already_bought': return `This wallet already paid for ${(body.items as string[] | undefined)?.join(' and ') ?? 'everything it asks for'}; a new run never buys the same item twice. Nothing was started.`;
    case 'balance_unavailable': return 'The ledger could not be read, so cereal could not check what this wallet holds. Nothing was started; try again.';
    case 'already_running': return REFUSAL_TEXT.already_running;
    case 'not_active': return `This wallet is ${body.status ?? 'not active'}; only an active wallet can run or be reclaimed.`;
    case 'too_young': return TOO_YOUNG;
    default: return describeError(error);
  }
}

function refusalText(r: RecordRefusal): string {
  return REFUSAL_TEXT[r.refused] ?? r.refused.replace(/_/g, ' ');
}

/** Why a wallet never became active, from its Ledger approval or what was sent. */
function whyNotActive(rec: ApiRecord): string {
  const refused = (rec.create_refusal as { refused?: string } | undefined)?.refused;  // kept by POST /wallets (R03)
  if (refused) return REFUSAL_TEXT[refused] ?? `Refused: ${refused.replace(/_/g, ' ')}.`;
  const approval = rec.approval?.result;
  if (rec.status === 'rejected') return REFUSAL_TEXT[approval ?? 'owner_rejected'] ?? REFUSAL_TEXT.owner_rejected;
  if (approval && approval !== 'approved') return REFUSAL_TEXT[approval] ?? `The Ledger did not approve: ${approval.replace(/_/g, ' ')}. Nothing was sent.`;
  const hashes = rec.hashes ?? {};
  if (hashes.fund) return REFUSAL_TEXT.funding_failed;
  if (hashes.activate || (Array.isArray(hashes.lock) && hashes.lock.some(Boolean))) return REFUSAL_TEXT.subwallet_failed;
  const last = rec.refusals?.[rec.refusals.length - 1];
  return last ? refusalText(last) : 'Creating this wallet did not finish. No budget was sent.';
}

function TxLink({ hash, label }: { hash?: string | null; label: string }) {
  const href = explorerTx(hash);
  if (!href) return <span>{label}</span>;
  return <a className="action-link" href={href} target="_blank" rel="noreferrer">{label}<LinkExternal01 aria-hidden="true" /></a>;
}

function LiveWalletActions({ app, id, live }: { app: AppActions; id: string; live: LiveInfo }) {
  const rec = live.record;
  const status = live.status;
  const [polled, setPolled] = useState<Run | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmReclaim, setConfirmReclaim] = useState(false);
  const [cleanup, setCleanup] = useState<Cleanup | null>(null);
  const [retireNote, setRetireNote] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const run = pickRun(polled, rec.run);
  const running = isLiveRun(run);
  const { refresh } = app.live;

  // While a run is live: tick the clock, and read the run every few seconds (that read also reconciles a run whose
  // process vanished, e.g. after a service restart). When it ends, re-read the wallet for its payments and sweep.
  useEffect(() => {
    if (!running || !run) return;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    let stopped = false;
    const poll = window.setInterval(async () => {
      try {
        const out = await api.run(id);
        if (stopped || !out.run) return;
        setPolled(out.run);
        if (!isLiveRun(out.run)) refresh();
      } catch { /* the next tick tries again; the shell shows a lost connection */ }
    }, POLL_MS);
    return () => { stopped = true; clearInterval(tick); clearInterval(poll); };
  }, [running, run?.id, id, refresh]);

  const act = useCallback(async (kind: Exclude<Busy, null>, work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(kind); setError(null);
    try { await work(); }
    catch (e) { setError(explain(e)); }
    finally { inFlight.current = false; setBusy(null); }
  }, []);

  const start = () => act('start', async () => {
    setCleanup(null); setRetireNote(null);
    try {
      const out = await api.startRun(id);
      setPolled(out.run); setNow(Date.now());
    } catch (e) {
      const body = e instanceof ApiError ? e.body as { run?: Run } | undefined : undefined;
      if (e instanceof ApiError && e.refused === 'already_running' && body?.run) setPolled(body.run);
      throw e;
    } finally { refresh(); }
  });

  const done = () => act('done', async () => {
    const out = await api.done(id, 'Finished by the owner');
    if (out.swept) setCleanup(out.swept as Cleanup);
    await refresh();
  });

  const reclaim = () => act('reclaim', async () => {
    setConfirmReclaim(false);
    try { setCleanup(await api.reclaim(id) as Cleanup); }
    finally { await refresh(); }
  });

  const retire = () => act('retire', async () => {
    setRetireNote(null);
    try {
      const out = await api.retire(id);
      if (out.ok) { await refresh(); return; }
      setRetireNote(out.result === 'tecTOO_SOON' ? TOO_YOUNG
        : `The ledger refused the deletion (${out.result ?? 'no result'}). Nothing was deleted; the wallet stays tracked, so you can try again.`);
    } catch (e) {
      if (e instanceof ApiError && e.refused === 'too_young') {
        const seconds = Number((e.body as { ready_in_seconds?: number }).ready_in_seconds);
        setRetireNote(Number.isFinite(seconds) && seconds > 0 ? `${TOO_YOUNG} About ${Math.max(1, Math.ceil(seconds / 60))} min to go.` : TOO_YOUNG);
        return;
      }
      throw e;
    }
  });

  const payments = (rec.payments ?? []).filter(p => run && (p.at ?? '') >= (run.started_at ?? ''));
  const refusals = (rec.refusals ?? []).filter(r => run && (r.at ?? '') >= (run.started_at ?? ''));
  const vendors = app.live.vendors;
  const hashes = rec.hashes ?? {};

  if (status === 'deploying') return <div className="wallet-actions" data-wallet-status={status}>
    <p className="action-status" role="status">Creating this wallet: waiting for the owner’s Ledger and the ledger.</p>
  </div>;

  if (status === 'rejected' || status === 'failed') return <div className="wallet-actions" data-wallet-status={status}>
    <p className="action-status error">{status === 'rejected' ? 'Rejected' : 'Not created'} · {whyNotActive(rec)}</p>
  </div>;

  const runSection = run && <section className="run" aria-label="Task run" data-run-status={run.status}>
    <p className="action-status" role="status">
      {running ? `Running · ${elapsed(run.started_at, now)}` : `${RUN_TITLE[run.status] ?? run.status} · ${elapsed(run.started_at, run.finished_at)}`}
      {run.exit_code !== null && run.exit_code !== undefined && run.status === 'failed' ? ` · exit ${run.exit_code}` : ''}
    </p>
    {running && <PlanLine run={run} />}
    {run.summary && <p className="action-detail">{run.summary}</p>}
    {typeof (run as { note?: unknown }).note === 'string' && <p className="action-detail">{(run as { note?: string }).note}</p>}
    {run.error && run.status !== 'succeeded' && <p className="action-detail error">{run.error}</p>}
    {(payments.length > 0 || refusals.length > 0) && <ul className="action-list" aria-label="This run’s payments">
      {payments.map((p, i) => <PaymentItem key={p.hash ?? i} payment={p} vendor={vendorName(p.to, vendors)} />)}
      {refusals.map((r, i) => <li key={`refusal-${i}`} className="error">Refused {r.payee ? vendorName(r.payee, vendors) : 'a payment'}
        {r.amount ? ` · ${formatAmount(r.amount)}` : ''} · {refusalText(r)}</li>)}
    </ul>}
    {!running && !payments.length && !refusals.length && <p className="action-detail">No payments during this run.</p>}
  </section>;

  const errorLine = error && <p className="action-status error" role="alert">{error}</p>;
  const cleanupSteps = <CleanupSteps cleanup={cleanup} rec={rec} />;

  if (status === 'active') {
    const canRunAgain = !!run && !running;  // the service skips items already paid for, and refuses if none are left
    return <div className="wallet-actions" data-wallet-status={status}>
      {runSection}
      <div className="action-row">
        {!run && <button className="primary-button" disabled={!!busy} onClick={start}>{busy === 'start' ? 'Starting…' : 'Start task'}</button>}
        {canRunAgain && <button className="action-button" disabled={!!busy} onClick={start}>{busy === 'start' ? 'Starting…' : 'Start again'}</button>}
        {rec.sweep_when_done && !running && <button className="action-button" disabled={!!busy} onClick={done}>{busy === 'done' ? 'Sweeping…' : 'Done · sweep back'}</button>}
        {!confirmReclaim && <button className="action-button" disabled={!!busy} onClick={() => setConfirmReclaim(true)}>{busy === 'reclaim' ? 'Reclaiming…' : 'Reclaim now'}</button>}
      </div>
      {confirmReclaim && <div className="action-confirm" role="group" aria-label="Confirm reclaim">
        <p>{live.available !== null ? `Return ${formatAmount(live.available)} to the main wallet and close the trust line?` : 'Return what this wallet holds to the main wallet and close the trust line?'}
          {running ? ' Its task is still running; it will not be able to pay after this.' : ''}</p>
        <div className="action-row">
          <button className="primary-button" disabled={!!busy} onClick={reclaim}>Reclaim</button>
          <button className="action-button" disabled={!!busy} onClick={() => setConfirmReclaim(false)}>Cancel</button>
        </div>
      </div>}
      {cleanup && !cleanup.ok && cleanupSteps}
      {cleanup && !cleanup.ok && <p className="action-status error" role="alert">Reclaim did not finish. The wallet stays active; reclaim again to sweep what is left and close the trust line.</p>}
      {errorLine}
    </div>;
  }

  if (status === 'reclaimed' || status === 'recovered') {
    const returned = rec.returned ?? cleanup?.returned ?? '0';
    return <div className="wallet-actions" data-wallet-status={status}>
      {runSection}
      <p className="action-status" role="status">{status === 'recovered' ? 'Recovered with the owner’s Ledger' : 'Swept back'} · {formatAmount(returned)} returned to the main wallet</p>
      {cleanupSteps}
      <div className="action-row">
        <button className="action-button" disabled={!!busy || running} onClick={retire}>{busy === 'retire' ? 'Retiring…' : 'Retire account'}</button>
      </div>
      {retireNote && <p className="action-detail" role="status">{retireNote}</p>}
      {errorLine}
    </div>;
  }

  if (status === 'retired') return <div className="wallet-actions" data-wallet-status={status}>
    {runSection}
    <p className="action-status" role="status">Retired · account deleted · {formatAmount(rec.returned ?? '0')} returned{' '}
      <TxLink hash={typeof hashes.retire === 'string' ? hashes.retire : null} label="View deletion" /></p>
  </div>;

  return <div className="wallet-actions" data-wallet-status={status}><p className="action-status">Status: {status}</p></div>;
}

function PlanLine({ run }: { run: Run }) {
  const plan = run.plan as { lines?: { item?: string; vendor?: string; price?: string }[] } | null | undefined;
  const lines = plan?.lines ?? [];
  if (!lines.length) return null;
  return <p className="action-detail">Buying {lines.map(l => `the ${l.item} from ${l.vendor} at ${formatAmount(l.price)}`).join(', ')}</p>;
}

function PaymentItem({ payment, vendor }: { payment: Payment; vendor: string }) {
  const state = paymentState(payment);
  const label = state === 'settled' ? 'Settled' : state === 'failed' ? `Failed (${payment.result ?? 'no result'})` : 'Pending on the ledger';
  return <li className={state === 'failed' ? 'error' : undefined} data-payment-state={state}>
    {resourceTitle(payment.resource)} · {vendor} · {formatAmount(payment.amount)}{payment.approved_by === 'ledger' ? ' · approved on the Ledger' : ''} ·{' '}
    <TxLink hash={payment.hash} label={label} />
  </li>;
}

/** The reclaim's transactions: from the response when this view ran it, else from the record's hashes. */
function CleanupSteps({ cleanup, rec }: { cleanup: Cleanup | null; rec: ApiRecord }) {
  let steps: Step[] = cleanup?.steps ?? [];
  if (!steps.length) {
    const recorded = rec.hashes?.reclaim;
    const list = (Array.isArray(recorded) ? recorded : recorded ? [recorded] : []).filter(Boolean) as string[];
    const swept = sumDecimals([rec.returned]) !== '0';
    steps = list.map((hash, i) => ({ step: swept && i === 0 ? 'sweep' : 'trustset_zero', ok: true, hash }));
  }
  if (!steps.length) return null;
  return <ul className="action-list" aria-label="Reclaim transactions">
    {steps.map((s, i) => <li key={s.hash ?? `${s.step}-${i}`} className={s.ok === false ? 'error' : undefined}>
      <TxLink hash={s.hash} label={`${STEP_TEXT[s.step] ?? s.step}${s.ok === false ? ` · failed (${s.result ?? 'no result'})` : ''}`} />
    </li>)}
  </ul>;
}
