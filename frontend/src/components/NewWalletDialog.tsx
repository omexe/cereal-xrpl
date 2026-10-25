import { useEffect, useRef, useState, type FormEvent } from 'react';
import { AlertCircle, CheckCircle, XCircle } from '@untitledui/icons';
import { api, ApiError, describeError, REFUSAL_TEXT, type CardVendor, type CreateResult, type Refusal, type WalletCard } from '../api';
import type { AppActions } from '../appActions';
import { explorerTx, formatAmount, shortAddress } from '../format';
import { isLive } from '../mode';
import { defaultConstraints, populateMockWallet } from '../wallets';
import { Dialog } from './Dialog';

/** I05: New wallet. Mock: a browser-only demo wallet. Live: preview the card, then create on testnet. */
export function NewWalletDialog({ app, description }: { app: AppActions; description: string }) {
  async function createMockWallet(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const name = String(data.get('name')).trim();
    if (!name) return;
    const id = crypto.randomUUID();
    const folderId = String(data.get('folder') || '');
    const saved = await app.setWorkspace(previous => ({ ...previous, wallets: [...previous.wallets, populateMockWallet({
      id, name, description: String(data.get('description') || '').trim(), transactions: [], balance: 0, archived: false, folderId: folderId || undefined,
      constraints: { ...defaultConstraints, merchants: [...defaultConstraints.merchants] },
    })] }));
    if (!saved) return;
    app.showWallet(id, folderId || undefined); app.close(); app.notify('Demo wallet created with mock funds and activity.');
  }
  if (isLive) return <LiveNewWalletDialog app={app} description={description} />;
  return <Dialog title="New wallet" onClose={app.close}><form onSubmit={createMockWallet}>
    <p className="dialog-description">Create a wallet for an agent task. Mock funds, spending rules, and sample activity are included.</p>
    <label>Wallet name<input name="name" required maxLength={80} placeholder="e.g. Lead enrichment" autoFocus /></label>
    <label>Task description<textarea name="description" maxLength={1000} defaultValue={description} placeholder="What should this wallet be used for?" /></label>
    <label>Folder<select name="folder"><option value="">Disposable wallets</option>{app.workspace.folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label>
    <p className="demo-note">Demo wallet · stored in this browser · no on-chain account is created.</p>
    <button className="primary-button form-submit">Create wallet</button>
  </form></Dialog>;
}

/** reviewing: POST /wallets/preview. approving: POST /wallets is waiting on the owner's Ledger. locking: the device
 * approved (or device funding is off) and cereal is locking and funding the subwallet. */
type Busy = 'reviewing' | 'approving' | 'locking' | null;
interface Failure { message: string; evidence: string[] }

const REJECTED = 'Rejected on your Ledger. Nothing was sent.';
/** Refusals that are the final answer for this request id: a retry would only replay them, so the next press of
 * Create is a new request. Everything else (caps, balance, device, network) is re-evaluated with the same id. */
const FINAL = new Set(['owner_rejected', 'device_error', 'subwallet_failed', 'funding_failed', 'request_id_reused']);

/** One per reviewed card. randomUUID needs a secure context (https or localhost); opened over a LAN address, fall back
 * to getRandomValues, which works everywhere. */
function newRequestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map(x => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

function duration(hours: number): string {
  if (hours >= 24) { const days = Number((hours / 24).toFixed(2)); return `${days} ${days === 1 ? 'day' : 'days'}`; }
  const h = Number(hours.toFixed(2));
  return `${h} ${h === 1 ? 'hour' : 'hours'}`;
}

/** valid → allowed. revoked, or not in cereal's directory (unknown), or any other state → not allowed. */
function credentialState(v: CardVendor): { state: string; allowed: boolean } {
  if (!v.address) return { state: 'unknown', allowed: false };
  if (v.credential === 'valid') return { state: 'valid', allowed: true };
  return { state: v.credential || 'unknown', allowed: false };
}

/** The evidence behind a refusal, in plain words: the cap and what was asked, the balance, the device. */
function evidence(body: Refusal): string[] {
  const out: string[] = [];
  const str = (key: string) => (body[key] === undefined || body[key] === null ? undefined : String(body[key]));
  const cap = str('cap'), limit = str('limit'), requested = str('requested');
  if (cap === 'MAX_ACTIVE_SUBAGENTS') {
    if (limit) out.push(`Limit: ${limit} active wallets`);
    if (str('active')) out.push(`Active now: ${str('active')}`);
  } else {
    if (cap) out.push(cap === 'MAX_OUTSTANDING_BUDGET' ? 'Cap: total budget out in wallets' : 'Cap: budget per wallet');
    if (limit) out.push(`Limit: ${formatAmount(limit)}`);
    if (str('outstanding')) out.push(`Already out in wallets: ${formatAmount(str('outstanding'))}`);
  }
  if (str('rlusd')) out.push(`Main wallet holds: ${formatAmount(str('rlusd'))}`);
  if (requested) out.push(`Requested: ${formatAmount(requested)}`);
  if (str('hint')) out.push(String(body.hint));
  if (str('deployment')) out.push(`Record: ${str('deployment')}`);
  return out;
}

function fundingHash(result: CreateResult): string | undefined {
  const fund = result.hashes?.fund;
  return Array.isArray(fund) ? fund[0] ?? undefined : fund ?? undefined;
}

function LiveNewWalletDialog({ app, description }: { app: AppActions; description: string }) {
  const [sentence, setSentence] = useState(description);
  const [folder, setFolder] = useState('');
  const [speculos, setSpeculos] = useState<'approve' | 'reject'>('approve');
  const [card, setCard] = useState<WalletCard>();
  const [requestId, setRequestId] = useState(newRequestId);
  const [busy, setBusy] = useState<Busy>(null);
  const [failure, setFailure] = useState<Failure>();
  const [notice, setNotice] = useState<string>();
  /** Guards Create against a second press before React re-renders the disabled button. */
  const creating = useRef(false);
  /** While creating: the sentence and the record ids that existed before, to find the new record in the poll. */
  const pending = useRef<{ sentence: string; before: Set<string> } | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  // Progress from the record itself: once its budget approval is on file, cereal is locking and funding it.
  const { records } = app.live;
  useEffect(() => {
    if (busy !== 'approving' || !pending.current) return;
    const { sentence: s, before } = pending.current;
    const rec = records.find(r => !before.has(r.id) && r.sentence === s);
    if (rec && (rec.approval?.result === 'approved' || rec.subwallet)) setBusy('locking');
  }, [busy, records]);

  function showCard(next: WalletCard) { setCard(next); setRequestId(newRequestId()); }

  async function review(event: FormEvent) {
    event.preventDefault();
    const text = sentence.trim();
    if (!text || busy) return;
    setBusy('reviewing'); setFailure(undefined); setNotice(undefined);
    try { showCard(await api.previewWallet({ sentence: text })); }
    catch (e) { setFailure({ message: describeError(e), evidence: [] }); }
    finally { setBusy(null); }
  }

  function edit() { if (busy) return; setCard(undefined); setFailure(undefined); setNotice(undefined); }

  async function create() {
    if (!card?.ok || creating.current) return;
    creating.current = true;
    pending.current = { sentence: card.sentence, before: new Set(app.live.records.map(r => r.id)) };
    setBusy(app.live.main?.policy.device_funding === false ? 'locking' : 'approving');
    setFailure(undefined); setNotice(undefined);
    try {
      const result = await api.createWallet({
        sentence: card.sentence, folder: folder || null, card_digest: card.digest, request_id: requestId,
        ...(import.meta.env.DEV ? { speculos_decision: speculos } : {}),
      });
      app.live.upsert(result);
      // Closed mid-flight: the user moved on, so only the status line reports it; never steal the current view.
      if (mounted.current) { app.showWallet(result.id, result.folder || undefined); app.close(); }
      const fund = fundingHash(result);
      const name = result.name || card.name;
      // A replay returns the wallet as it is now: say so if it is no longer active.
      app.notify((result.status === 'active' ? `${name} is active on testnet with ${formatAmount(result.budget)}.`
        : `${name} was created earlier and is now ${result.status}.`) + (fund ? ` Funding transaction: ${explorerTx(fund)}` : ''));
    } catch (e) {
      const body = e instanceof ApiError && e.kind === 'refused' ? e.body as Refusal & { card?: WalletCard } : undefined;
      const code = body?.refused;
      if (code && FINAL.has(code)) setRequestId(newRequestId());
      if (body?.deployment) app.live.refresh();
      let shown: Failure | undefined;
      if (code === 'card_changed' && body?.card) {
        showCard(body.card); setNotice(REFUSAL_TEXT.card_changed);
      } else if (code === 'card_problems' && body?.card) {
        showCard(body.card); shown = { message: REFUSAL_TEXT.card_problems, evidence: [] };
      } else if (code === 'owner_rejected') {
        shown = { message: REJECTED, evidence: [] };
      } else if (code === 'deploy_interrupted') {
        // Same request id kept on purpose: pressing again replays this answer instead of deploying a second wallet.
        shown = { message: 'Creation stopped partway on testnet and was not retried. Check the record before creating another wallet.', evidence: evidence(body!) };
      } else if (code === 'in_progress') {
        shown = { message: 'This wallet is still being created on testnet. Wait a moment, then press Create on testnet again; it will not be created twice.', evidence: [] };
      } else if (body) {
        shown = { message: describeError(e), evidence: evidence(body) };
      } else {
        shown = { message: describeError(e), evidence: ['Pressing Create on testnet again sends the same request: if cereal created the wallet, it returns that wallet instead of a second one.'] };
      }
      // Closed mid-flight: the dialog is gone, so the outcome goes to the status line instead of disappearing.
      if (mounted.current) setFailure(shown);
      else app.notify(shown?.message ?? REFUSAL_TEXT.card_changed, true);
    } finally {
      creating.current = false; pending.current = null;
      if (mounted.current) setBusy(null);
    }
  }

  const folderName = folder || 'Disposable wallets';
  const errorBox = failure && <div className="wallet-error" role="alert"><p>{failure.message}</p>
    {failure.evidence.length > 0 && <ul>{failure.evidence.map(line => <li key={line}>{line}</li>)}</ul>}</div>;
  const progress = busy && <p className="wallet-progress" role="status" aria-live="polite">
    {busy === 'reviewing' ? 'Reading your description…'
      : busy === 'approving' ? 'Waiting for approval on your Ledger…' : 'Locking and funding the wallet on testnet…'}
    {busy !== 'reviewing' && <span>30–90 s is normal. Keep this open; pressing again never creates a second wallet.</span>}
  </p>;

  if (!card) return <Dialog title="New wallet" onClose={app.close}><form onSubmit={review}>
    <p className="dialog-description">Describe the wallet in one sentence: budget, how long, which vendors, and when to ask you.</p>
    <label>Describe the wallet<textarea name="sentence" maxLength={1000} value={sentence} autoFocus disabled={!!busy}
      placeholder="Market sizing: spend up to 1 RLUSD over 2 days, only at Vendor A and Vendor C. Ask me above 0.2. Sweep back when done."
      onChange={event => setSentence(event.target.value)} /></label>
    <label>Folder<select name="folder" value={folder} disabled={!!busy} onChange={event => setFolder(event.target.value)}>
      <option value="">Disposable wallets</option>{app.workspace.folders.map(f => <option key={f.id} value={f.name}>{f.name}</option>)}
    </select></label>
    {progress}{errorBox}
    <button className="primary-button form-submit" disabled={!sentence.trim() || !!busy}>Review wallet</button>
  </form></Dialog>;

  const parser = !card.parsed_by || card.parsed_by === 'fallback-parser' ? 'the backup parser' : `Claude (${card.parsed_by})`;
  return <Dialog title="Review wallet" onClose={app.close}>
    <p className="dialog-description">This is exactly what cereal and the ledger will enforce. Nothing is on testnet until you create it.</p>
    {notice && <p className="wallet-notice" role="alert"><AlertCircle />{notice}</p>}
    <section className="wallet-card" aria-label="Wallet card" data-ok={card.ok}>
      <p className="wallet-card-summary">{card.summary}</p>
      <dl className="wallet-card-rules">
        <div><dt>Name</dt><dd>{card.name}</dd></div>
        <div><dt>Budget</dt><dd data-field="budget">{formatAmount(card.budget)}</dd></div>
        <div><dt>Duration</dt><dd>{duration(card.expires_in_hours)}</dd></div>
        <div><dt>Vendors</dt><dd>{card.vendors.length ? <ul className="card-vendors">{card.vendors.map((v, i) => {
          const { state, allowed } = credentialState(v);
          return <li key={`${v.named}-${i}`} className={`card-vendor ${allowed ? '' : 'not-allowed'}`} data-credential={state}>
            {allowed ? <CheckCircle aria-hidden /> : state === 'revoked' ? <XCircle aria-hidden /> : <AlertCircle aria-hidden />}
            <span>{v.name ?? v.named}</span>
            <span className="card-vendor-state">{allowed ? 'credential valid' : `${state} · not allowed`}</span>
            {v.address && <span className="card-address" title={v.address}>{shortAddress(v.address)}</span>}
          </li>;
        })}</ul> : 'Any vendor with a valid cereal credential'}</dd></div>
        <div><dt>Ask me above</dt><dd>{card.approval_threshold ? `${formatAmount(card.approval_threshold)} (your Ledger signs instead of cereal)` : 'No approval threshold'}</dd></div>
        <div><dt>When done</dt><dd>{card.sweep_when_done ? 'Sweep leftovers back to the main wallet' : 'Keep leftovers in the wallet'}</dd></div>
        <div><dt>Folder</dt><dd>{folderName}</dd></div>
      </dl>
      {card.problems.length > 0 && <ul className="card-problems" aria-label="Problems">{card.problems.map(p => <li key={p}>{p}</li>)}</ul>}
      {card.notes.length > 0 && <ul className="card-notes" aria-label="Notes">{card.notes.map(n => <li key={n}>{n}</li>)}</ul>}
      <p className="card-parser">Read by {parser}.</p>
    </section>
    {import.meta.env.DEV && <label className="dev-only">Speculos emulator: approve / reject
      <select value={speculos} disabled={!!busy} onChange={event => setSpeculos(event.target.value === 'reject' ? 'reject' : 'approve')}>
        <option value="approve">Emulator approves the budget</option>
        <option value="reject">Emulator rejects the budget</option>
      </select>
      <span className="demo-note">Development only: picks the button the Speculos emulator presses. A real Ledger always waits for its owner.</span>
    </label>}
    {progress}{errorBox}
    <div className="wallet-card-actions">
      <button type="button" className="secondary-button" disabled={!!busy} onClick={edit}>Edit</button>
      <button type="button" className="primary-button" disabled={!card.ok || !!busy} onClick={create}>Create on testnet</button>
    </div>
  </Dialog>;
}
