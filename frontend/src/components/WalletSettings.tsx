import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError, describeError, type MetaChange } from '../api';
import type { AppActions } from '../appActions';
import { formatAmount } from '../format';
import { isActive } from '../live';
import { isLive } from '../mode';
import type { Wallet } from '../wallets';

const MAX_NAME = 80;
const NAME_RULE = `Wallet names are 1 to ${MAX_NAME} printable characters.`;

/** What archiving or restoring does to this wallet, honestly: it only hides or unhides it (A06). */
function archiveCopy(wallet: Wallet): string {
  const { status, available } = wallet.live!;
  if (wallet.archived) {
    return isActive(wallet)
      ? 'Restoring only unhides this wallet. Archiving never moved its funds or changed its rules.'
      : `Restoring only unhides this wallet. It stays ${status}${status === 'retired' ? ': its account is deleted on the ledger and cannot come back' : ''}.`;
  }
  if (isActive(wallet)) {
    const held = available === null ? 'Its RLUSD' : `Its ${formatAmount(available)}`;
    return `Archiving hides this wallet. ${held} stays in it and its rules still apply; reclaim to return funds. It is still swept home at expiry.`;
  }
  return `Archiving hides this wallet. It stays ${status}; nothing moves on the ledger, and the export keeps its payments.`;
}

function metaError(error: unknown): string {
  if (error instanceof ApiError && error.kind === 'refused') {
    if (error.refused === 'invalid_name') return NAME_RULE;
    if (error.refused === 'unknown_folder') return 'That folder no longer exists. Pick another one.';
  }
  return describeError(error);
}

/** A05/A06: the selected wallet's name, folder and archive controls inside Settings. Mock: browser state.
 * Live: each control is one POST /subagents/{id}/meta; the response replaces the record, errors show inline. */
export function WalletSettings({ app }: { app: AppActions }) {
  const { selected } = app;
  if (!selected) return null;
  return isLive && selected.live ? <LiveWalletSettings key={selected.id} app={app} wallet={selected} /> : <MockWalletSettings app={app} />;
}

function MockWalletSettings({ app }: { app: AppActions }) {
  const { selected, workspace } = app;
  if (!selected) return null;
  return <div className="settings-wallet"><p>Selected wallet</p><strong>{selected.name}</strong>
    {!selected.archived && <label>Wallet folder<select value={selected.folderId ?? ''} onChange={event => app.moveWallet(selected.id, event.target.value || undefined)}>
      <option value="">Disposable Wallets</option>{workspace.folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
    </select></label>}
    <button className="secondary-button" onClick={app.toggleArchive}>{selected.archived ? 'Restore selected wallet' : 'Archive selected wallet'}</button></div>;
}

type Failure = { field: 'name' | 'other'; message: string };

function LiveWalletSettings({ app, wallet }: { app: AppActions; wallet: Wallet }) {
  const [name, setName] = useState(wallet.name);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure>();
  const [note, setNote] = useState<string>();
  const open = useRef(true);
  useEffect(() => { open.current = true; return () => { open.current = false; }; }, []);
  // A rename that lands from elsewhere (another tab, the poll) replaces the field, so Save never sends a stale name.
  useEffect(() => { setName(wallet.name); }, [wallet.name]);

  /** One metadata write. The response replaces the record now; the refresh then re-reads, so a poll that was already
   * in flight with the old record cannot leave it on screen. */
  async function save(change: MetaChange, field: Failure['field'], done: string): Promise<boolean> {
    setBusy(true); setFailure(undefined); setNote(undefined);
    try {
      const out = await api.updateMeta(wallet.id, change);
      app.live.upsert(out.wallet);
      void app.live.refresh();
      if (open.current) setNote(done);
      return true;
    } catch (e) {
      if (open.current) setFailure({ field, message: metaError(e) }); else app.notify(metaError(e), true);
      return false;
    } finally { if (open.current) setBusy(false); }
  }
  async function rename(event: FormEvent) {
    event.preventDefault();
    const next = name.trim();
    if (!next || next.length > MAX_NAME) { setFailure({ field: 'name', message: NAME_RULE }); return; }
    if (next === wallet.name) { setFailure(undefined); setNote('That is already its name.'); return; }
    await save({ name: next }, 'name', 'Name saved.');
  }
  async function move(folder: string) {
    // Same view change as dragging (App.moveWallet): show the wallet, with its new folder expanded.
    if (await save({ folder: folder || null }, 'other', `Moved to ${folder || 'Disposable Wallets'}.`) && open.current) app.showWallet(wallet.id, folder || undefined);
  }
  async function toggleArchive() {
    const archiving = !wallet.archived;
    if (await save({ archived: archiving }, 'other', '')) {
      if (open.current) app.close();
      app.notify(archiving ? 'Wallet archived. Its funds and account are unchanged.' : `Wallet restored. It is still ${wallet.live!.status}.`);
    }
  }
  const nameError = failure?.field === 'name';

  return <div className="settings-wallet"><p>Selected wallet</p><strong>{wallet.name}</strong>
    <form onSubmit={rename} noValidate>
      <label>Wallet name<input name="wallet-name" value={name} maxLength={MAX_NAME} disabled={busy} aria-invalid={nameError}
        aria-describedby={nameError ? 'wallet-name-error' : undefined} onChange={event => { setName(event.target.value); setFailure(undefined); }} /></label>
      {nameError && <p id="wallet-name-error" className="status-message error" role="alert">{failure.message}</p>}
      <button className="secondary-button" disabled={busy}>Save name</button>
    </form>
    {!wallet.archived && <label>Wallet folder<select value={wallet.folderId ?? ''} disabled={busy} onChange={event => move(event.target.value)}>
      <option value="">Disposable Wallets</option>{app.workspace.folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
    </select></label>}
    <p className="demo-note">{archiveCopy(wallet)}</p>
    <button className="secondary-button" disabled={busy} onClick={toggleArchive}>{wallet.archived ? 'Restore selected wallet' : 'Archive selected wallet'}</button>
    {failure && !nameError && <p className="status-message error" role="alert">{failure.message}</p>}
    {note && !failure && <p className="status-message" role="status">{note}</p>}
  </div>;
}
