import type { AppActions } from '../appActions';

/** A05/A06: the selected wallet's folder and archive controls inside Settings (live: POST /subagents/{id}/meta). */
export function WalletSettings({ app }: { app: AppActions }) {
  const { selected, workspace } = app;
  if (!selected) return null;
  return <div className="settings-wallet"><p>Selected wallet</p><strong>{selected.name}</strong>
    {!selected.archived && <label>Wallet folder<select value={selected.folderId ?? ''} onChange={event => app.moveWallet(selected.id, event.target.value || undefined)}>
      <option value="">Disposable Wallets</option>{workspace.folders.map(folder => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
    </select></label>}
    <button className="secondary-button" onClick={app.toggleArchive}>{selected.archived ? 'Restore selected wallet' : 'Archive selected wallet'}</button></div>;
}
