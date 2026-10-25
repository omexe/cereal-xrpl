import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { LinkExternal01 } from '@untitledui/icons';
import { api, ApiError, describeError, REFUSAL_TEXT, type ApiRecord, type Refusal, type Run, type Site, type SiteContent, type SiteOpen } from '../api';
import type { AppActions } from '../appActions';
import { explorerAccount, explorerTx, formatAmount, shortAddress } from '../format';
import { sitesChanged, onSitesChanged } from './sites/events';
import { ProbeFindings, TrustNote } from './sites/SiteChecks';
import { blockedInfo, blockedText, formatWhen, newRequestId, refusalMessage, trustOf } from './sites/siteText';
import { sitesLoadError } from './SitesSection';

/** Sites (live only): one site's checks and trust, Open (free) or Buy (payable), and what was delivered. */
export function SiteDetail({ app, siteId }: { app: AppActions; siteId: string }) {
  return <SiteView key={`${siteId}:${app.session?.token ?? ''}`} app={app} siteId={siteId} />;
}

type Load = { state: 'loading' } | { state: 'ready'; site: Site } | { state: 'missing' } | { state: 'removed'; name: string }
  | { state: 'error'; message: string; signedOut: boolean };

function ExternalLink({ href, children, title }: { href?: string; children: ReactNode; title?: string }) {
  if (!href) return <>{children}</>;
  return <a className="action-link" href={href} target="_blank" rel="noreferrer noopener" title={title}>{children}<LinkExternal01 aria-hidden="true" /></a>;
}

function SiteView({ app, siteId }: { app: AppActions; siteId: string }) {
  const [load, setLoad] = useState<Load>({ state: 'loading' });
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const seq = useRef(0);
  const signedIn = !!app.session;

  // The latest read wins; the sidebar and this view both re-read on every sitesChanged().
  const reload = useCallback(async () => {
    const n = ++seq.current;
    try {
      const sites = await api.sites();
      if (n !== seq.current) return;
      const site = sites.find(s => s.id === siteId);
      setLoad(previous => previous.state === 'removed' ? previous : site ? { state: 'ready', site } : { state: 'missing' });
    } catch (e) {
      if (n !== seq.current) return;
      setLoad(previous => previous.state === 'ready' ? previous : { state: 'error', ...sitesLoadError(e) });
    }
  }, [siteId]);

  useEffect(() => {
    if (!signedIn) return;
    void reload();
    const stop = onSitesChanged(() => { void reload(); });
    return () => { seq.current++; stop(); };
  }, [signedIn, reload]);

  async function remove(site: Site) {
    if (removing) return;
    setRemoving(true); setRemoveError(null);
    try {
      await api.removeSite(site.id);
      seq.current++;
      setLoad({ state: 'removed', name: site.name });
      sitesChanged();
      app.notify(`${site.name} removed from your sites.`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) { setLoad({ state: 'missing' }); sitesChanged(); }
      else setRemoveError(describeError(e));
    } finally { setRemoving(false); }
  }

  if (!signedIn) return <article className="site-detail" aria-label="Site">
    <h1 className="site-title">Sign in to see your sites</h1>
    <p className="site-lede">Sites are private to each person: only the user who added a site can see it or pay it.</p>
    <div className="site-actions"><button className="primary-button" onClick={() => app.openAddSite()}>Sign in</button></div>
  </article>;
  if (load.state === 'loading') return <article className="site-detail" aria-label="Site" aria-busy="true"><p className="site-lede" role="status">Loading this site…</p></article>;
  if (load.state === 'error') return <article className="site-detail" aria-label="Site">
    <p className="site-error" role="alert">{load.message}</p>
    <div className="site-actions">{load.signedOut
      ? <button className="primary-button" onClick={() => { app.setSession(null); app.openAddSite(); }}>Sign in again</button>
      : <button className="action-button" onClick={() => { setLoad({ state: 'loading' }); void reload(); }}>Try again</button>}</div>
  </article>;
  if (load.state === 'missing' || load.state === 'removed') return <article className="site-detail" aria-label="Site">
    <h1 className="site-title">{load.state === 'removed' ? `${load.name} was removed` : 'This site is not in your list'}</h1>
    <p className="site-lede">{load.state === 'removed' ? 'It is no longer in your sites. Wallets already bought for it keep their own history.'
      : 'It may have been removed, or it belongs to another user. Sites are private to the person who added them.'}</p>
    <div className="site-actions"><button className="primary-button" onClick={() => app.openAddSite()}>Add a site</button></div>
  </article>;

  const { site } = load;
  const trust = trustOf(site);
  const blocked = trust === 'blocked';
  const payable = site.kind === 'payable' && (trust === 'public' || trust === 'private');
  const payment = site.payment;
  const info = blockedInfo(site);
  const added = formatWhen(site.added_at);
  const blockedAt = formatWhen(info.at);

  return <article className="site-detail" aria-labelledby="site-title" data-site-id={site.id} data-trust={trust}>
    <header className="site-header">
      <h1 id="site-title" className="site-title">{site.name}</h1>
      <a className="site-url action-link" href={site.url} target="_blank" rel="noreferrer noopener">{site.url}<LinkExternal01 aria-hidden="true" /></a>
    </header>
    <TrustNote trust={trust} />

    <dl className="site-facts">
      {payment && <div data-fact="price"><dt>Price</dt><dd>{formatAmount(payment.amount)}</dd></div>}
      {payment && <div data-fact="payee"><dt>Payee</dt><dd>
        <ExternalLink href={explorerAccount(payment.pay_to)} title={payment.pay_to}>{shortAddress(payment.pay_to)}</ExternalLink></dd></div>}
      {added && <div data-fact="added"><dt>Added</dt><dd>{added}</dd></div>}
      {!!site.wallets?.length && <div data-fact="wallets"><dt>Wallets</dt><dd>{site.wallets.length}</dd></div>}
    </dl>

    {blocked && <section className="site-blocked" aria-label="Why it is blocked" role="note">
      <h2>Why it is blocked</h2>
      <p>{blockedText(site.blocked_reason ?? (info.by === 'paid_not_delivered' ? 'paid_not_delivered' : null))}</p>
      <BlockedEvidence evidence={info.evidence} />
      {blockedAt && <p className="site-meta">Blocked {blockedAt}{info.by ? ` · by ${info.by === 'probe' ? 'an automatic check' : 'the delivery check'}` : ''}</p>}
    </section>}

    <section className="site-section" aria-label="Checks">
      <h2>Checks</h2>
      <ProbeFindings probe={site} />
      {formatWhen(site.probed_at) && <p className="site-meta">Checked {formatWhen(site.probed_at)}</p>}
    </section>

    {!blocked && site.kind === 'free' && <FreePage siteId={site.id} />}
    {site.kind === 'payable' && <Purchase app={app} site={site} canBuy={payable && !blocked} />}

    <div className="site-actions site-remove">
      <button className="action-button" disabled={removing} onClick={() => remove(site)}>{removing ? 'Removing…' : 'Remove from my sites'}</button>
    </div>
    {removeError && <p className="site-error" role="alert">{removeError}</p>}
  </article>;
}

function evidenceValue(key: string, value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return '—';
  if (key === 'hash' && typeof value === 'string') return <ExternalLink href={explorerTx(value)} title={value}>{shortAddress(value)}</ExternalLink>;
  if (key === 'payee' && typeof value === 'string') return <ExternalLink href={explorerAccount(value)} title={value}>{shortAddress(value)}</ExternalLink>;
  if (key === 'amount' && (typeof value === 'string' || typeof value === 'number')) return formatAmount(value);
  if (Array.isArray(value)) return value.map(v => typeof v === 'object' && v ? (v as { detail?: string }).detail ?? JSON.stringify(v) : String(v)).join(' · ');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

const EVIDENCE_LABEL: Record<string, string> = {
  hash: 'Payment', payee: 'Paid to', amount: 'Amount', resource: 'Resource', deployment: 'Wallet', verdict_reasons: 'Reasons', checks: 'Failed checks',
};

function BlockedEvidence({ evidence }: { evidence: Record<string, unknown> | null }) {
  if (!evidence) return null;
  const keys = Object.keys(evidence).filter(k => k !== 'explorer' && evidence[k] !== null && evidence[k] !== undefined);
  if (!keys.length) return null;
  return <dl className="site-evidence" aria-label="Evidence">
    {keys.map(k => <div key={k} data-evidence={k}><dt>{EVIDENCE_LABEL[k] ?? k.replace(/_/g, ' ')}</dt><dd>{evidenceValue(k, evidence[k])}</dd></div>)}
  </dl>;
}

/** Free sites: read the page through cereal. The text is data: rendered as text, never as HTML. */
function FreePage({ siteId }: { siteId: string }) {
  const [page, setPage] = useState<SiteOpen>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function open() {
    if (busy) return;
    setBusy(true); setError(null);
    try { setPage(await api.openSite(siteId)); }
    catch (e) { setError(refusalMessage(e)); }
    finally { setBusy(false); }
  }

  return <section className="site-section" aria-label="Page">
    <div className="site-actions">
      <button className="primary-button" disabled={busy} onClick={open}>{busy ? 'Opening…' : page ? 'Open again' : 'Open page'}</button>
      <span className="site-meta">Free · read through cereal · no wallet, no payment</span>
    </div>
    {busy && <p className="site-progress" role="status">Reading the page…</p>}
    {error && <p className="site-error" role="alert">{error}</p>}
    {page && <div className="site-page" data-status={page.status}>
      <h2 className="site-page-title">{page.title || 'Untitled page'}</h2>
      <p className="site-meta">{page.bytes.toLocaleString()} bytes{page.content_type ? ` · ${page.content_type}` : ''} · HTTP {page.status}
        {page.truncated ? ' · Truncated: showing the first 20,000 characters' : ''}</p>
      <pre className="site-text" tabIndex={0} aria-label="Page text">{page.text || '(The page has no readable text.)'}</pre>
      <p className="site-meta">Scripts and styles are removed. The text is shown as data: nothing on the page runs here.</p>
    </div>}
  </section>;
}

/** GET /sites/{id}/content on success (unit 3): `settled` is the ledger's word, `paid` is set only once it is true. */
type Delivered = SiteContent & { price?: string | null; settled?: boolean | null; explorer?: string; truncated?: boolean; resource?: string };
interface NotDelivered { wallet?: unknown; status?: string; pending?: boolean; trust?: string; hash?: string; paid?: string; explorer?: string; error?: unknown }
interface Failure { message: string; evidence: string[]; wallet?: string }

type Phase =
  | { phase: 'idle' }
  | { phase: 'approving' }
  | { phase: 'running'; wallet: string; run: Run | null; since: number }
  | { phase: 'delivered'; result: Delivered }
  | { phase: 'not_delivered'; body: NotDelivered }
  | { phase: 'nothing'; run: Run | null }
  | { phase: 'lost'; wallet: string; message: string };

/** What one read of /content says: the outcome is shown, the purchase is still in flight, or the read failed. */
type Read = 'done' | 'pending' | 'error';

const POLL_MS = 3000;
/** Consecutive failed reads while following a purchase before the view stops and says so. */
const MAX_FAILED_READS = 5;
/** How long a delivered payment that the ledger has not validated yet is re-checked (every POLL_MS). */
const MAX_SETTLE_READS = 40;
const LIVE_RUN = ['starting', 'running'];
/** Final answers for this request id: pressing Buy again starts a new attempt. Anything else replays the same one,
 * except a replayed outcome (`replayed: true`), which is final too unless the purchase is still being set up. */
const FINAL = new Set(['owner_rejected', 'device_error', 'device_timeout', 'subwallet_failed', 'funding_failed', 'rejected', 'failed',
  'request_id_reused', 'invalid_request_id', 'site_blocked', 'not_payable', 'price_above_cap']);
const REPLAY_KEEPS_ID = new Set(['in_progress', 'deploy_interrupted', 'already_running']);
const RUN_TITLE: Record<string, string> = {
  starting: 'Starting', running: 'Running', succeeded: 'Finished', failed: 'Failed', timed_out: 'Timed out', interrupted: 'Interrupted',
};
const BUY_TEXT: Record<string, string> = {
  owner_rejected: 'Rejected on your Ledger. Nothing was sent.',
  device_timeout: 'Your Ledger did not answer in time. Nothing was sent; press Buy to ask again.',
  in_progress: 'This purchase is still being set up on testnet. Wait a moment and press Buy again: it will not buy twice.',
  deploy_interrupted: 'Setting up this purchase stopped partway on testnet and was not retried. Check the wallet before buying again.',
  invalid_request_id: 'cereal refused the purchase id. Press Buy again to start a new attempt.',
  site_blocked: 'This site is blocked. Nothing was paid.',
};

function elapsed(from: number, now: number): string {
  const s = Math.max(0, Math.round((now - from) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

const walletId = (wallet: unknown): string | undefined =>
  typeof wallet === 'string' ? wallet : wallet && typeof wallet === 'object' && typeof (wallet as { id?: unknown }).id === 'string' ? (wallet as { id: string }).id : undefined;

const CAP_TEXT: Record<string, string> = {
  MAX_SUBAGENT_BUDGET: 'budget per wallet', MAX_OUTSTANDING_BUDGET: 'total budget out in wallets', MAX_ACTIVE_SUBAGENTS: 'active wallets',
  SITE_PRICE_CAP: 'price per site purchase',
};

/** The evidence behind a buy refusal, in plain words: the cap and what was asked, the balance, a hint. */
function evidenceLines(body: Refusal): string[] {
  const out: string[] = [];
  const str = (key: string) => (body[key] === undefined || body[key] === null ? undefined : String(body[key]));
  const cap = str('cap');
  const count = cap === 'MAX_ACTIVE_SUBAGENTS';
  if (cap) out.push(`Cap: ${CAP_TEXT[cap] ?? cap.replace(/_/g, ' ').toLowerCase()}`);
  if (str('limit')) out.push(`Limit: ${count ? `${str('limit')} active wallets` : formatAmount(str('limit'))}`);
  if (str('active')) out.push(`Active now: ${str('active')}`);
  if (str('outstanding')) out.push(`Already out in wallets: ${formatAmount(str('outstanding'))}`);
  if (str('rlusd')) out.push(`Main wallet holds: ${formatAmount(str('rlusd'))}`);
  if (str('price')) out.push(`Price: ${formatAmount(str('price'))}`);
  if (str('requested')) out.push(`Requested: ${formatAmount(str('requested'))}`);
  if (str('reason')) out.push(String(body.reason));
  if (str('hint')) out.push(String(body.hint));
  return out;
}

/** Payable sites: buy with a new wallet, follow its run, then show what the site delivered and the payment proof. */
function Purchase({ app, site, canBuy }: { app: AppActions; site: Site; canBuy: boolean }) {
  const [phase, setPhase] = useState<Phase>({ phase: 'idle' });
  const [failure, setFailure] = useState<Failure>();
  const [speculos, setSpeculos] = useState<'approve' | 'reject'>('approve');
  const [requestId, setRequestId] = useState(newRequestId);
  const [now, setNow] = useState(() => Date.now());
  const buying = useRef(false);
  /** Bumped by every Buy press: a read started for an earlier attempt never overwrites a newer one. */
  const attempt = useRef(0);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const isPrivate = trustOf(site) === 'private';
  const { upsert, refresh, records } = app.live;

  /** Read GET /sites/{id}/content and show its outcome. `wallet` is the purchase being followed, if any; `quiet`
   * keeps a failed read off the screen (the resume when the site opens). */
  const readContent = useCallback(async ({ wallet, run, quiet }: { wallet?: string; run?: Run | null; quiet?: boolean } = {}): Promise<Read> => {
    const mine = attempt.current;
    const current = () => mounted.current && attempt.current === mine;
    try {
      const out = await api.siteContent(site.id) as Delivered;
      if (current()) setPhase({ phase: 'delivered', result: out });
      return 'done';
    } catch (e) {
      if (!current()) return 'done';
      const body = e instanceof ApiError && e.refused ? e.body as Refusal & NotDelivered : undefined;
      if (body?.refused === 'not_delivered') {
        if (body.pending) {  // still in flight: follow it
          const following = walletId(body.wallet) ?? wallet;
          if (following) setPhase(previous => previous.phase === 'running' && previous.wallet === following ? previous
            : { phase: 'running', wallet: following, run: null, since: Date.now() });
          return 'pending';
        }
        setPhase({ phase: 'not_delivered', body });
        sitesChanged();  // the delivery check may have blocked this site: the view and the sidebar re-read it
        return 'done';
      }
      if (body?.refused === 'nothing_bought') { setPhase(wallet ? { phase: 'nothing', run: run ?? null } : { phase: 'idle' }); return 'done'; }
      if (!wallet && !quiet) setFailure({ message: describeError(e), evidence: [] });
      return 'error';
    }
  }, [site.id]);

  // A purchase started earlier (or in another tab) shows its outcome, or resumes following it.
  const hasWallets = !!site.wallets?.length;
  const resumed = useRef(false);  // once per view, also under StrictMode's double effects
  useEffect(() => {
    if (!hasWallets || resumed.current) return;
    resumed.current = true;
    void readContent({ quiet: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // While a purchase runs: tick the clock and read the run every few seconds (one read at a time); once it ends,
  // ask what was delivered. Reads that keep failing stop the loop with a visible note instead of spinning forever.
  const following = phase.phase === 'running' ? phase.wallet : null;
  useEffect(() => {
    if (!following) return;
    let stopped = false;
    let failed = 0;
    let timer = 0;
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    const lost = (message: string) => setPhase(previous => previous.phase === 'running' && previous.wallet === following
      ? { phase: 'lost', wallet: following, message } : previous);
    const step = async () => {
      let read: Read = 'pending';
      let error: unknown;
      try {
        const out = await api.run(following);
        if (stopped) return;
        if (out.run) setPhase(previous => previous.phase === 'running' && previous.wallet === following ? { ...previous, run: out.run } : previous);
        if (!out.run || !LIVE_RUN.includes(out.run.status)) {
          read = await readContent({ wallet: following, run: out.run });
          if (read === 'done') void refresh();
        }
      } catch (e) { read = 'error'; error = e; }
      if (stopped) return;
      failed = read === 'error' ? failed + 1 : 0;
      if (error instanceof ApiError && (error.status === 404 || error.status === 401)) { lost(describeError(error)); return; }
      if (failed >= MAX_FAILED_READS) { lost(error ? describeError(error) : 'cereal could not say what this purchase delivered.'); return; }
      if (read !== 'done') timer = window.setTimeout(step, POLL_MS);
    };
    timer = window.setTimeout(step, POLL_MS);
    return () => { stopped = true; clearInterval(tick); clearTimeout(timer); };
  }, [following, readContent, refresh]);

  // A delivery whose payment the ledger has not validated yet: re-read until it says settled or failed.
  const settling = phase.phase === 'delivered' && phase.result.settled === null ? phase.result : null;
  const settleReads = useRef(0);
  useEffect(() => {
    if (!settling || settleReads.current >= MAX_SETTLE_READS) return;
    const timer = window.setTimeout(() => { settleReads.current += 1; void readContent({ quiet: true }); }, POLL_MS);
    return () => clearTimeout(timer);
  }, [settling, readContent]);

  async function buy() {
    if (buying.current || !canBuy) return;
    buying.current = true;
    attempt.current += 1;
    settleReads.current = 0;
    const before = phase;
    setFailure(undefined); setPhase({ phase: 'approving' });
    try {
      const out = await api.buySite(site.id, { request_id: requestId, ...(import.meta.env.DEV ? { speculos_decision: speculos } : {}) });
      upsert(out.wallet); void refresh(); sitesChanged();
      setRequestId(newRequestId());
      if (!mounted.current) { app.notify(`Buying ${site.name}: its wallet is running on testnet.`); return; }
      setNow(Date.now());
      setPhase({ phase: 'running', wallet: out.wallet.id, run: out.run ?? null, since: Date.now() });
    } catch (e) {
      const body = e instanceof ApiError && e.refused ? e.body as Refusal & { wallet?: ApiRecord | string; run?: Run; replayed?: boolean } : undefined;
      const code = body?.refused;
      const wallet = walletId(body?.wallet);
      if (body?.wallet && typeof body.wallet === 'object') upsert(body.wallet);
      if (code === 'already_running' && wallet) {  // this site's purchase is still in flight: follow it
        if (mounted.current) { setNow(Date.now()); setPhase({ phase: 'running', wallet, run: body?.run ?? null, since: Date.now() }); }
        return;
      }
      if (code && (FINAL.has(code) || (body?.replayed === true && !REPLAY_KEEPS_ID.has(code)))) setRequestId(newRequestId());
      if (code === 'site_blocked') sitesChanged();
      const message = !code ? `${describeError(e)} Pressing Buy again sends the same request: if cereal already bought it, you get that purchase, not a second one.`
        : BUY_TEXT[code] ?? REFUSAL_TEXT[code] ?? describeError(e);
      const failed = { message, evidence: body ? evidenceLines(body) : [], wallet };
      // A refused new attempt leaves what an earlier purchase delivered on screen.
      if (mounted.current) { setFailure(failed); setPhase(before.phase === 'approving' || before.phase === 'running' ? { phase: 'idle' } : before); }
      else app.notify(`${site.name}: ${message}`, true);
    } finally { buying.current = false; }
  }

  const openWallet = (id: string) => app.showWallet(id);
  /** Who signed a delivered payment: the wallet record's payment says, else a private site's rule (the owner's Ledger
   * signs every payment to a private site). */
  const signedBy = (result: Delivered) => {
    const pay = records.find(r => r.id === result.wallet)?.payments?.find(p => p.hash && p.hash === result.hash);
    return pay?.approved_by ?? (isPrivate ? 'ledger' : undefined);
  };
  const settled = phase.phase === 'delivered' || phase.phase === 'not_delivered' || phase.phase === 'nothing' || phase.phase === 'lost';
  const canStart = canBuy && (phase.phase === 'idle' || settled);
  const price = site.payment ? formatAmount(site.payment.amount) : null;
  if (!canBuy && phase.phase === 'idle' && !failure) return null;

  return <section className="site-section site-purchase" aria-label="Purchase" data-phase={phase.phase}>
    <h2>{phase.phase === 'delivered' ? 'Delivered' : 'Buy'}</h2>
    {canBuy && phase.phase === 'idle' && <p className="site-lede">
      cereal opens a new wallet for this purchase: budget {price ?? 'the price'}, payable only to this site’s payee, buy-only,
      swept back when done. {isPrivate ? 'Your Ledger approves the budget and signs the payment.' : 'Your Ledger approves the budget; cereal co-signs the payment within the wallet’s rules.'}</p>}

    {phase.phase === 'approving' && <div className="site-progress" role="status" aria-live="polite">
      <p>Waiting for your Ledger to approve the budget…</p>
      <span>30–90 s is normal. Keep this open; pressing Buy again never buys twice.</span></div>}

    {phase.phase === 'running' && <div className="site-progress" role="status" aria-live="polite" data-run-status={phase.run?.status ?? 'starting'}>
      <p>{phase.run && !LIVE_RUN.includes(phase.run.status) ? `${RUN_TITLE[phase.run.status] ?? phase.run.status} · checking what was delivered…`
        : `Running · ${elapsed(Date.parse(phase.run?.started_at ?? '') || phase.since, now)}`}</p>
      <span>The wallet pays {price ?? 'the price'} and fetches the page.{isPrivate ? ' Your Ledger signs the payment.' : ''} Nothing is shown as paid until the ledger validates it.</span>
      <button className="sites-signout" onClick={() => openWallet(phase.wallet)}>Open the wallet</button>
    </div>}

    {failure && <div className="site-error" role="alert"><p>{failure.message}</p>
      {failure.evidence.length > 0 && <ul>{failure.evidence.map(line => <li key={line}>{line}</li>)}</ul>}
      {failure.wallet && <button className="sites-signout" onClick={() => openWallet(failure.wallet!)}>Open the wallet</button>}</div>}

    {phase.phase === 'delivered' && <DeliveredContent result={phase.result} signedBy={signedBy(phase.result)} onOpenWallet={openWallet} />}
    {phase.phase === 'not_delivered' && <NotDeliveredNote body={phase.body} siteBlocked={trustOf(site) === 'blocked'} onOpenWallet={openWallet} />}
    {phase.phase === 'nothing' && <div className="site-error" role="alert">
      <p>Nothing was bought: the purchase {phase.run ? (RUN_TITLE[phase.run.status] ?? phase.run.status).toLowerCase() : 'ended'} without a payment.</p>
      {typeof phase.run?.error === 'string' && <ul><li>{phase.run.error}</li></ul>}
    </div>}
    {phase.phase === 'lost' && <div className="site-error" role="alert">
      <p>cereal stopped following this purchase: {phase.message}</p>
      <ul><li>The wallet keeps its own record of any payment. Open it to see what happened.</li></ul>
      <button className="sites-signout" onClick={() => openWallet(phase.wallet)}>Open the wallet</button>
    </div>}

    {canStart && import.meta.env.DEV && <label className="site-dev">Speculos emulator: approve / reject
      <select value={speculos} onChange={event => setSpeculos(event.target.value === 'reject' ? 'reject' : 'approve')}>
        <option value="approve">Emulator approves</option>
        <option value="reject">Emulator rejects</option>
      </select>
      <span className="demo-note">Development only: picks the button the Speculos emulator presses. A real Ledger always waits for its owner.</span>
    </label>}
    {canStart && <div className="site-actions">
      <button className="primary-button" onClick={buy}>{settled ? 'Buy again with a new wallet' : 'Buy with a new wallet'}</button>
      {price && <span className="site-meta">{price} · RLUSD on XRPL testnet</span>}
    </div>}
  </section>;
}

function contentText(content: unknown): string {
  if (typeof content === 'string') return content;
  try { return JSON.stringify(content, null, 2) ?? String(content); } catch { return String(content); }
}

/** What the site delivered, with the payment as the ledger reports it: "Paid" only once validated (settled: true). */
function DeliveredContent({ result, signedBy, onOpenWallet }: { result: Delivered; signedBy?: string; onOpenWallet: (id: string) => void }) {
  const href = result.explorer ?? explorerTx(result.hash);
  const state = !result.hash ? 'unknown' : result.settled === true ? 'settled' : result.settled === false ? 'failed' : 'pending';
  const amount = formatAmount(result.paid ?? result.price);
  const headline = state === 'settled' ? `Paid ${amount}${signedBy === 'ledger' ? ' · Signed by your Ledger' : ''}`
    : state === 'pending' ? `Payment of ${amount} settling on the ledger…`
    : state === 'failed' ? `The ledger did not validate the ${amount} payment`
    : 'No payment hash was recorded for this delivery';
  const hasContent = result.content !== null && result.content !== undefined;
  return <div className="site-delivered">
    <div className="site-proof" aria-label="Payment proof" data-payment-state={state}>
      <p role={state === 'pending' ? 'status' : undefined}>{headline}</p>
      <p>{result.hash && <ExternalLink href={href} title={result.hash}>Payment on the ledger</ExternalLink>}
        {result.hash && result.wallet && ' · '}
        {result.wallet && <button className="sites-signout" onClick={() => onOpenWallet(result.wallet)}>Open the wallet</button>}</p>
    </div>
    {result.truncated && <p className="site-meta">The site sent more than 100,000 characters; showing the start.</p>}
    {hasContent && <pre className="site-text" tabIndex={0} aria-label="Delivered content">{contentText(result.content)}</pre>}
    {!hasContent && <p className="site-meta">The site delivered an empty response.</p>}
  </div>;
}

function NotDeliveredNote({ body, siteBlocked, onOpenWallet }: { body: NotDelivered; siteBlocked: boolean; onOpenWallet: (id: string) => void }) {
  const paid = !!body.hash;
  const href = body.explorer ?? explorerTx(body.hash);
  const blocked = siteBlocked || body.trust === 'blocked';
  const wallet = walletId(body.wallet);
  const error = typeof body.error === 'string' ? body.error : body.error ? JSON.stringify(body.error) : null;
  return <div className="site-error site-not-delivered" role="alert" data-paid={paid}>
    <p>{paid ? `${REFUSAL_TEXT.not_delivered} ${formatAmount(body.paid)} was paid and nothing came back.`
      : 'Not delivered, and no payment was recorded for this purchase.'}
      {paid && blocked ? ' cereal blocked this site: nobody can pay it again.' : ''}</p>
    <ul>
      {paid && <li><ExternalLink href={href} title={body.hash}>Payment on the ledger</ExternalLink></li>}
      {!paid && <li>If a payment was still in flight, the wallet shows it once the ledger decides.</li>}
      {body.status && <li>Run: {RUN_TITLE[body.status] ?? body.status}</li>}
      {error && <li>{error}</li>}
    </ul>
    {wallet && <button className="sites-signout" onClick={() => onOpenWallet(wallet)}>Open the wallet</button>}
  </div>;
}
