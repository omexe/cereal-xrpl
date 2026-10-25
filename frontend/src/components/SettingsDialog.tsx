import type { AppActions } from '../appActions';
import { isLive } from '../mode';
import { DemoSettings } from './DemoSettings';
import { Dialog } from './Dialog';
import { WalletSettings } from './WalletSettings';
import { ConnectionPanel } from './settings/ConnectionPanel';
import { EventsPanel } from './settings/EventsPanel';
import { ExportPanel } from './settings/ExportPanel';
import { PolicyPanel } from './settings/PolicyPanel';
import { SweepsPanel } from './settings/SweepsPanel';
import { VendorsPanel } from './settings/VendorsPanel';

/** Settings. Live (I06/I07): service status, policy, vendors, security events, sweeps, exports, all from the
 * cereal service. Mock: the original local-demo summary. */
export function SettingsDialog({ app }: { app: AppActions }) {
  const archived = app.workspace.wallets.filter(w => w.archived).length;
  if (isLive) return <Dialog title="Workspace settings" onClose={app.close}>
    <div className="settings-live">
      <p className="dialog-description">Wallets, balances, rules, and vendors come from the cereal service. Payments settle on XRPL testnet.</p>
      <ConnectionPanel live={app.live} archived={archived} />
      <WalletSettings app={app} />
      <PolicyPanel main={app.live.main} />
      <VendorsPanel vendors={app.live.vendors} />
      <EventsPanel />
      <SweepsPanel main={app.live.main} />
      <ExportPanel />
    </div>
  </Dialog>;
  return <Dialog title="Workspace settings" onClose={app.close}>
    <div className="settings-summary"><span>Mode</span><strong>Local demo</strong><span>Active wallets</span><strong>{app.activeWallets.length}</strong><span>Archived wallets</span><strong>{archived}</strong></div>
    <p className="dialog-description">Wallets, balances, and constraints are simulated and saved in this browser. No wallet service or Ledger device is connected.</p>
    <WalletSettings app={app} />
    <DemoSettings wallets={app.workspace.wallets} runs={app.workspace.researchRuns ?? []} selectedId={app.selectedId} />
  </Dialog>;
}
