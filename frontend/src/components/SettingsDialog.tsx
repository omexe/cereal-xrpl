import type { AppActions } from '../appActions';
import { isLive } from '../mode';
import { Dialog } from './Dialog';
import { WalletSettings } from './WalletSettings';

/** Settings. Live (I06/I07): backend status, vendors, security events, exports. */
export function SettingsDialog({ app }: { app: AppActions }) {
  const archived = app.workspace.wallets.filter(w => w.archived).length;
  return <Dialog title="Workspace settings" onClose={app.close}>
    <div className="settings-summary"><span>Mode</span><strong>{isLive ? 'Live · XRPL testnet' : 'Local demo'}</strong><span>Active wallets</span><strong>{app.activeWallets.length}</strong><span>Archived wallets</span><strong>{archived}</strong></div>
    <p className="dialog-description">{isLive
      ? `Wallets, balances, and rules come from the cereal service${app.live.status === 'error' ? ' (not reachable right now)' : ''}. Payments settle on XRPL testnet.`
      : 'Wallets, balances, and constraints are simulated and saved in this browser. No wallet service or Ledger device is connected.'}</p>
    <WalletSettings app={app} />
  </Dialog>;
}
