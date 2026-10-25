import { useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError, describeError, type ApiRecord, type RulesChange, type RulesPreview, type RulesResult } from '../api';
import type { AppActions } from '../appActions';
import { explorerTx, formatAmount, shortAddress } from '../format';
import type { LiveInfo } from '../live';
import { isLive } from '../mode';
import type { Constraints, Wallet } from '../wallets';
import { Dialog } from './Dialog';

/** A03: edit a wallet's spending rules, from the blue rule buttons or a sentence typed in the wallet composer.
 * Mock: browser state. Live: preview, then apply on the backend (sentence = the composer's text, if any). */
export function ConstraintsDialog({ app, sentence }: { app: AppActions; sentence?: string }) {
  const selected = app.selected!;
  if (!isLive) return <MockConstraints app={app} sentence={sentence} />;
  if (selected.live) return <LiveConstraints app={app} wallet={selected} live={selected.live} sentence={sentence} />;
  return <Dialog title="Spending rules" onClose={app.close}>
    <p className="dialog-description">This wallet has not loaded from the cereal service yet. Nothing was changed.</p>
  </Dialog>;
}

function MockConstraints({ app, sentence }: { app: AppActions; sentence?: string }) {
  const selected = app.selected!;
  const [draftConstraints, setDraftConstraints] = useState<Constraints>(() => ({ ...selected.constraints }));
  const [mode, setMode] = useState<'sentence' | 'fields'>('sentence');
  const [text, setText] = useState(sentence ?? '');
  const [previewText, setPreviewText] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const started = useRef(false);
  async function preview() {
    setBusy(true); setError(''); setPreviewText(undefined);
    try {
      const out = await api.previewDemoRules(text, selected.name, selected.constraints);
      if (out.ok && out.constraints) { setDraftConstraints(out.constraints); setPreviewText(text); }
      else setError(out.problems.join(' '));
    } catch (err) { setError(describeError(err)); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    if (started.current || !sentence) return;
    started.current = true; void preview();
  }, []);
  return <Dialog title="Wallet constraints" onClose={app.close}><form onSubmit={async event => {
    event.preventDefault();
    if (selected.archived || busy || (mode === 'sentence' && previewText !== text)) return;
    const merchants = mode === 'fields'
      ? String(new FormData(event.currentTarget).get('merchants')).split(',').map(m => m.trim()).filter(Boolean)
      : draftConstraints.merchants;
    if (!merchants.length) return;
    if (!await app.updateWallet(selected.id, { constraints: { ...draftConstraints, merchants } })) return;
    app.close(); app.notify('Demo wallet constraints updated.');
  }}><p className="dialog-description">Describe how to change the rules for {selected.name}. AI proposes the edit for you to review. Rules are saved for this demo; no payments are executed.</p>
    {mode === 'sentence' ? <>
      <label>Requested change<textarea value={text} maxLength={1000} disabled={busy} onChange={e => setText(e.target.value)} autoFocus
        placeholder="e.g. Halve my approval threshold and keep the remaining funds." /></label>
      <button type="button" className="text-button rules-switch" disabled={busy} onClick={() => { setMode('fields'); setError(''); }}>Edit the fields instead</button>
      <button type="button" className="secondary-button" disabled={!text.trim() || busy} onClick={() => void preview()}>{busy ? 'Understanding…' : 'Preview changes'}</button>
      {previewText === text && <section className="rules-preview" aria-label="Preview of the change" aria-live="polite">
        <p>Spend up to ${draftConstraints.spend} over {draftConstraints.days} days, only at {draftConstraints.merchants.join(', ')}. Ask me above ${draftConstraints.approval}. {draftConstraints.sweep ? 'Sweep back' : 'Keep funds'} when done.</p>
      </section>}
    </> : <>
      <div className="form-grid"><label>Spend limit ($)<input type="number" min="0.01" step="0.01" required value={draftConstraints.spend} onChange={e => setDraftConstraints({ ...draftConstraints, spend: +e.target.value })} autoFocus /></label>
      <label>Duration (days)<input type="number" min="1" max="365" step="1" required value={draftConstraints.days} onChange={e => setDraftConstraints({ ...draftConstraints, days: +e.target.value })} /></label></div>
      <label>Allowed merchants<input name="merchants" required defaultValue={draftConstraints.merchants.join(', ')} /></label>
      <label>Ask for approval above ($)<input type="number" min="0" step="0.01" required value={draftConstraints.approval} onChange={e => setDraftConstraints({ ...draftConstraints, approval: +e.target.value })} /></label>
      <label className="checkbox-label"><input type="checkbox" checked={draftConstraints.sweep} onChange={e => setDraftConstraints({ ...draftConstraints, sweep: e.target.checked })} />Sweep back when done</label>
      <button type="button" className="text-button rules-switch" onClick={() => { setMode('sentence'); setPreviewText(undefined); }}>Describe a change with AI</button>
    </>}
    {error && <p role="alert">{error}</p>}
    <button className="primary-button form-submit" disabled={selected.archived || busy || (mode === 'sentence' && previewText !== text)}>Save constraints</button>
  </form></Dialog>;
}

interface RulesForm { spend: string; hours: string; merchants: string[]; approval: string; noThreshold: boolean; sweep: boolean }
type Applied = RulesResult & { notes?: string[]; returned?: string; explorer?: string; wallet?: ApiRecord };
interface Previewed { key: string; result: RulesPreview }
interface Failure { message: string; problems: string[]; link?: string }

const MAX_HOURS = 168;
/** Refusals specific to this dialog; the shared ones come from REFUSAL_TEXT via describeError. */
const RULES_REFUSALS: Record<string, string> = {
  rules_problems: 'cereal refused this change. Nothing was changed.',
  return_failed: 'The excess did not go back to the main wallet, so no rule was changed.',
  return_unknown: 'cereal could not confirm the return, so no rule was changed.',
};

function formFrom(live: LiveInfo): RulesForm {
  const left = Math.max(0, (Date.parse(live.expiresAt) - Date.now()) / 3_600_000);
  return {
    spend: live.budget, hours: String(Math.round(left * 10) / 10), merchants: [...live.payees],
    approval: live.approval ?? '', noThreshold: live.approval === null, sweep: live.record.sweep_when_done === true,
  };
}

/** "0.50" and "0.5" are the same amount; anything that is not a plain decimal compares as typed. */
const sameAmount = (a: string, b: string) => {
  const norm = (s: string) => /^\d+(\.\d+)?$/.test(s.trim()) ? s.trim().replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '').replace(/^0+(?=\d)/, '') : s.trim();
  return norm(a) === norm(b);
};
const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every(x => b.includes(x));

/** Only the fields the owner changed: an untouched duration must not move the expiry. */
function changeFrom(form: RulesForm, initial: RulesForm): RulesChange {
  const change: RulesChange = {};
  if (!sameAmount(form.spend, initial.spend)) change.spend = form.spend.trim();
  if (form.hours.trim() !== initial.hours) change.expires_in_hours = Number(form.hours.trim() || 0);
  if (!sameSet(form.merchants, initial.merchants)) change.merchants = form.merchants;
  if (form.noThreshold !== initial.noThreshold || (!form.noThreshold && !sameAmount(form.approval, initial.approval)))
    change.approval_threshold = form.noThreshold ? null : form.approval.trim();
  if (form.sweep !== initial.sweep) change.sweep_when_done = form.sweep;
  return change;
}

const credentialText: Record<string, string> = {
  valid: 'Credentialed', revoked: 'Revoked', pending: 'Credential not accepted', expired: 'Credential expired',
  none: 'No credential', unknown: 'Not in cereal’s directory',
};

function LiveConstraints({ app, wallet, live, sentence }: { app: AppActions; wallet: Wallet; live: LiveInfo; sentence?: string }) {
  const [initial] = useState(() => formFrom(live));
  const [form, setForm] = useState(initial);
  const [mode, setMode] = useState<'sentence' | 'fields'>('sentence');
  const [text, setText] = useState(sentence ?? '');
  const [preview, setPreview] = useState<Previewed>();
  const [applied, setApplied] = useState<Applied>();
  const [busy, setBusy] = useState<'preview' | 'apply' | null>(null);
  const [failure, setFailure] = useState<Failure>();
  const started = useRef(false);
  const vendors = app.live.vendors;
  // With vendor credentials off (a service setting), the co-signer pays any listed vendor, so none is blocked here.
  const credentialsRequired = app.live.main?.policy.vendor_credentials !== false;
  const editable = live.status === 'active' && !wallet.archived;

  const change: RulesChange = mode === 'sentence' ? { sentence: text.trim() } : changeFrom(form, initial);
  const key = JSON.stringify(change);
  const empty = mode === 'sentence' ? !text.trim() : !Object.keys(change).length;
  const current = preview?.key === key;
  const canApply = !!preview && current && preview.result.ok && !!preview.result.resolved_change && !busy && editable;

  const options = useMemo(() => {
    const list = vendors.map(v => ({ address: v.address, name: v.name, status: v.credential?.status ?? 'unknown',
      reason: v.credential?.revocation?.reason }));
    for (const address of initial.merchants)
      if (!list.some(o => o.address === address)) list.push({ address, name: shortAddress(address), status: 'unknown', reason: undefined });
    return list;
  }, [vendors, initial.merchants]);

  async function runPreview(next: RulesChange = change) {
    setBusy('preview'); setFailure(undefined);
    try {
      const result = await api.previewRules(wallet.id, next);
      setPreview({ key: JSON.stringify(next), result });
    } catch (error) {
      setPreview(undefined); setFailure(failureOf(error));
    } finally { setBusy(null); }
  }

  async function runApply() {
    if (!preview || !canApply) return;
    setBusy('apply'); setFailure(undefined);
    try {
      const out = await api.updateRules(wallet.id, preview.result.resolved_change!) as Applied;
      app.live.upsert(out.wallet ?? { ...live.record, ...out.rules } as ApiRecord);
      setApplied(out);
      const link = explorerTx(out.hashes?.return);
      app.notify(link && out.returned ? `Spending rules updated. ${formatAmount(out.returned)} returned to the main wallet: ${link}`
        : 'Spending rules updated.');
      void app.live.refresh();
    } catch (error) {
      setFailure(failureOf(error));
    } finally { setBusy(null); }
  }

  // Opened from the composer: preview the typed sentence right away.
  useEffect(() => {
    if (started.current || !sentence || !editable) return;
    started.current = true;
    void runPreview({ sentence: sentence.trim() });
  }, []);

  if (!editable) return <Dialog title="Spending rules" onClose={app.close}>
    <p className="dialog-description">{wallet.name} is {wallet.archived ? 'archived' : live.status}; its rules no longer change.</p>
    <button className="primary-button form-submit" onClick={app.close}>Close</button>
  </Dialog>;

  if (applied) {
    const link = explorerTx(applied.hashes?.return);
    return <Dialog title="Spending rules updated" onClose={app.close}><div className="rules-result" role="status">
      <p className="dialog-description">cereal enforces these rules for {wallet.name} from the next payment it co-signs.</p>
      <ul className="rules-list">{applied.changes.map(line => <li key={line}>{line}</li>)}</ul>
      {link && applied.returned && <p className="rules-return">{formatAmount(applied.returned)} went back to the main wallet on XRPL testnet.{' '}
        <a href={link} target="_blank" rel="noreferrer">View the return transaction</a></p>}
      <button className="primary-button form-submit" onClick={app.close} autoFocus>Done</button>
    </div></Dialog>;
  }

  const set = (update: Partial<RulesForm>) => setForm(previous => ({ ...previous, ...update }));
  const toggleMerchant = (address: string, on: boolean) =>
    set({ merchants: on ? [...form.merchants, address] : form.merchants.filter(a => a !== address) });
  return <Dialog title="Spending rules" onClose={app.close}><form noValidate onSubmit={event => { event.preventDefault(); if (!empty && !busy) void runPreview(); }}>
    <p className="dialog-description">Change what {wallet.name} may spend. It holds {formatAmount(live.available)} now: {formatAmount(live.spent)} spent, {formatAmount(live.pending)} pending.</p>
    {mode === 'sentence' ? <>
      <label>Requested change<textarea value={text} maxLength={1000} disabled={!!busy} onChange={event => setText(event.target.value)}
        placeholder="e.g. Halve my approval threshold and stop using Vendor C." autoFocus /></label>
      <button type="button" className="text-button rules-switch" disabled={!!busy} onClick={() => { setMode('fields'); setPreview(undefined); setFailure(undefined); }}>Edit the fields instead</button>
    </> : <>
      <div className="form-grid">
        <label>Spend limit (RLUSD)<input type="number" min="0" step="any" inputMode="decimal" value={form.spend} disabled={!!busy} onChange={event => set({ spend: event.target.value })} autoFocus /></label>
        <label>Duration (hours from now)<input type="number" min="0.1" max={MAX_HOURS} step="any" inputMode="decimal" value={form.hours} disabled={!!busy} onChange={event => set({ hours: event.target.value })} /></label>
      </div>
      <fieldset className="rules-merchants" disabled={!!busy}>
        <legend>Allowed merchants</legend>
        {!initial.merchants.length && <p className="demo-note">Any credentialed vendor today. Check vendors to narrow the list.</p>}
        {!options.length && <p className="demo-note">Loading cereal’s vendor directory…</p>}
        {options.map(option => {
          const checked = form.merchants.includes(option.address);
          // A vendor without a valid credential can be removed, never added.
          const blocked = credentialsRequired && option.status !== 'valid' && !checked;
          return <label key={option.address} className="checkbox-label rules-merchant">
            <input type="checkbox" checked={checked} disabled={blocked} onChange={event => toggleMerchant(option.address, event.target.checked)} />
            <span>{option.name}<small className={option.status === 'valid' ? undefined : 'rules-untrusted'}>
              {credentialText[option.status] ?? option.status}{option.reason ? `: ${option.reason}` : ''}</small></span>
          </label>;
        })}
      </fieldset>
      <label>Ask for approval above (RLUSD)<input type="number" min="0" step="any" inputMode="decimal" value={form.approval} disabled={!!busy || form.noThreshold}
        onChange={event => set({ approval: event.target.value })} /></label>
      <label className="checkbox-label"><input type="checkbox" checked={form.noThreshold} disabled={!!busy} onChange={event => set({ noThreshold: event.target.checked })} />No approval threshold</label>
      <label className="checkbox-label"><input type="checkbox" checked={form.sweep} disabled={!!busy} onChange={event => set({ sweep: event.target.checked })} />Sweep back when done</label>
      <button type="button" className="text-button rules-switch" disabled={!!busy} onClick={() => { setMode('sentence'); setPreview(undefined); setFailure(undefined); }}>Describe a change with AI</button>
    </>}

    {preview && <section className="rules-preview" aria-label="Preview of the change" aria-live="polite">
      {preview.result.changes.length > 0 && <><h3>Changes</h3><ul className="rules-list">{preview.result.changes.map(line => <li key={line}>{line}</li>)}</ul></>}
      {preview.result.problems.length > 0 && <><h3>Problems</h3><ul className="rules-list rules-problems">{preview.result.problems.map(line => <li key={line}>{line}</li>)}</ul></>}
      {preview.result.notes.length > 0 && <><h3>Notes</h3><ul className="rules-list rules-notes">{preview.result.notes.map(line => <li key={line}>{line}</li>)}</ul></>}
      {!current && <p className="demo-note">You changed the rules after this preview. Preview again before applying.</p>}
    </section>}
    {failure && <div className="rules-failure" role="alert"><p>{failure.message}</p>
      {failure.problems.length > 0 && <ul className="rules-list">{failure.problems.map(line => <li key={line}>{line}</li>)}</ul>}
      {failure.link && <a href={failure.link} target="_blank" rel="noreferrer">View the transaction</a>}
    </div>}

    <div className="rules-actions">
      <button type="submit" className="secondary-button" disabled={empty || !!busy}>{busy === 'preview' ? (mode === 'sentence' ? 'Understanding…' : 'Checking…') : 'Preview changes'}</button>
      <button type="button" className="primary-button" disabled={!canApply} onClick={() => void runApply()}>{busy === 'apply' ? 'Applying…' : 'Apply changes'}</button>
    </div>
    {empty && mode === 'fields' && <p className="demo-note">Change a rule above, then preview it.</p>}
  </form></Dialog>;
}

function failureOf(error: unknown): Failure {
  if (error instanceof ApiError && error.kind === 'refused') {
    const body = (error.body ?? {}) as { refused?: string; problems?: unknown; explorer?: unknown };
    const problems = Array.isArray(body.problems) ? body.problems.map(String) : [];
    return { message: (body.refused && RULES_REFUSALS[body.refused]) || error.message, problems,
      link: typeof body.explorer === 'string' ? body.explorer : undefined };
  }
  return { message: describeError(error), problems: [] };
}
