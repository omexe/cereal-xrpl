import type { AppActions } from '../appActions';
import { formatAmount } from '../format';
import { isLive } from '../mode';
import { Dialog } from './Dialog';

/** A04: Add funds. Mock: changes the demo balance only. Live: an owner-approved top-up on testnet. */
export function FundsDialog({ app }: { app: AppActions }) {
  const selected = app.selected!;
  if (isLive) return <Dialog title="Add funds" onClose={app.close}>
    <p className="dialog-description">Available balance: {formatAmount(selected.live?.available)}.</p>
    <p className="demo-note">Live funding is not connected yet. No payment was made.</p>
  </Dialog>;
  return <Dialog title="Add demo funds" onClose={app.close}><form onSubmit={event => {
    event.preventDefault(); const amount = Number(new FormData(event.currentTarget).get('amount'));
    if (!Number.isFinite(amount) || amount <= 0 || amount > 1000000) return;
    app.updateWallet(selected.id, { balance: Math.round((selected.balance + amount) * 100) / 100 }); app.close(); app.notify('Demo balance updated. No payment was made.');
  }}><p className="dialog-description">Available balance: {formatAmount(selected.balance)}. This changes the demo balance only.</p>{app.isHome && <label>Wallet to fund<select value={app.selectedId} onChange={event => app.setSelectedId(event.target.value)}>{app.activeWallets.map(wallet => <option key={wallet.id} value={wallet.id}>{wallet.name}</option>)}</select></label>}<label>Amount (USD)<input name="amount" type="number" min="0.01" max="1000000" step="0.01" placeholder="100.00" required autoFocus /></label><button className="primary-button form-submit">Add demo funds</button></form></Dialog>;
}
