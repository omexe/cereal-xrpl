import { useState } from 'react';
import { ArrowUpRight } from '@untitledui/icons';
import { CHAT_PATH, isTestEnvironment } from '../mode';
import type { Wallet } from '../wallets';
import type { ResearchRun } from '../researchDemo';
import { resetResearchWallet } from '../researchDemo';
import { mutateWorkspace } from '../workspaceStore';

export function DemoSettings({ wallets, runs, selectedId }: { wallets: Wallet[]; runs: ResearchRun[]; selectedId?: string }) {
  const [walletId, setWalletId] = useState(selectedId ?? wallets[0]?.id ?? '');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const wallet = wallets.find(item => item.id === walletId);
  const hasActivity = runs.some(run => run.walletId === walletId);
  return <section className="demo-settings" aria-labelledby="demo-tools-title">
    <h3 id="demo-tools-title">Developer tools</h3>
    <p className="dialog-description">Open the separate research chat demo, then name any existing wallet in your prompt. Its current rules and activity stay in Cereal.</p>
    <a className="research-launch" href={CHAT_PATH} target="cereal-research-chat" rel="noopener">{isTestEnvironment ? 'Open test chat' : 'Open demo chat'} <ArrowUpRight /></a>
    <p className="demo-note">Example: “Research XRPL. Use my XRP research wallet for payments.”</p>
    <details><summary>Demo scenario & replay</summary>
      <p className="demo-note">Paid sources: Ledger Lens ($1.20), Venture Atlas ($7.50), Open Ledger Index ($0.65). Token Insider is always blocked by a fictional fraud signal. Your wallet’s existing merchant list, budget, and approval threshold determine every other outcome.</p>
      <label>Wallet activity to reset<select value={walletId} onChange={event => { setWalletId(event.target.value); setConfirm(false); setMessage(''); }}>
        {!wallets.length && <option value="">No wallets</option>}{wallets.map(item => <option key={item.id} value={item.id}>{item.name}{item.archived ? ' (archived)' : ''}</option>)}
      </select></label>
      {!confirm ? <button className="secondary-button" disabled={!wallet || wallet.archived || !hasActivity} onClick={() => setConfirm(true)}>Reset research session</button>
        : <div className="demo-reset-confirm"><p className="dialog-description">Stop {wallet?.name}’s demo sessions and reverse their simulated payments and returns? Existing transactions, rules, funding, and other wallets are preserved.</p>
          <div className="approval-actions"><button className="primary-button" disabled={busy} onClick={async () => {
            setBusy(true); setMessage('');
            try { await mutateWorkspace(state => resetResearchWallet(state, walletId)); setConfirm(false); setMessage('Research session reset. Existing wallet history and rules preserved.'); }
            catch (error) { setMessage(error instanceof Error ? error.message : 'Could not reset demo activity.'); }
            finally { setBusy(false); }
          }}>{busy ? 'Resetting…' : 'Confirm reset'}</button><button className="research-outline" disabled={busy} onClick={() => setConfirm(false)}>Cancel</button></div>
        </div>}
    </details>
    {message && <p className="demo-note" role="status">{message}</p>}
    <p className="demo-note">Local simulation · No live browsing, model calls, or real payments.</p>
  </section>;
}
