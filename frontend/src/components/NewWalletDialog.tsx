import type { FormEvent } from 'react';
import type { AppActions } from '../appActions';
import { isLive } from '../mode';
import { defaultConstraints, populateMockWallet } from '../wallets';
import { Dialog } from './Dialog';

/** I05: New wallet. Mock: a browser-only demo wallet. Live: preview the card, then create on testnet. */
export function NewWalletDialog({ app, description }: { app: AppActions; description: string }) {
  function createMockWallet(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const name = String(data.get('name')).trim();
    if (!name) return;
    const id = crypto.randomUUID();
    const folderId = String(data.get('folder') || '');
    app.setWorkspace(previous => ({ ...previous, wallets: [...previous.wallets, populateMockWallet({
      id, name, description: String(data.get('description') || '').trim(), transactions: [], balance: 0, archived: false, folderId: folderId || undefined,
      constraints: { ...defaultConstraints, merchants: [...defaultConstraints.merchants] },
    })] }));
    app.showWallet(id, folderId || undefined); app.close(); app.notify('Demo wallet created with mock funds and activity.');
  }
  if (isLive) return <Dialog title="New wallet" onClose={app.close}><form onSubmit={event => event.preventDefault()}>
    <p className="dialog-description">Describe the wallet in one sentence: budget, time, vendors, and when to ask you.</p>
    <label>Description<textarea name="sentence" maxLength={1000} defaultValue={description} /></label>
    <p className="demo-note">Live wallet creation is not connected yet.</p>
    <button className="primary-button form-submit" disabled>Review wallet</button>
  </form></Dialog>;
  return <Dialog title="New wallet" onClose={app.close}><form onSubmit={createMockWallet}>
    <p className="dialog-description">Create a wallet for an agent task. Mock funds, spending rules, and sample activity are included.</p>
    <label>Wallet name<input name="name" required maxLength={80} placeholder="e.g. Lead enrichment" autoFocus /></label>
    <label>Task description<textarea name="description" maxLength={1000} defaultValue={description} placeholder="What should this wallet be used for?" /></label>
    <label>Folder<select name="folder"><option value="">Disposable wallets</option>{app.workspace.folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}</select></label>
    <p className="demo-note">Demo wallet · stored in this browser · no on-chain account is created.</p>
    <button className="primary-button form-submit">Create wallet</button>
  </form></Dialog>;
}
