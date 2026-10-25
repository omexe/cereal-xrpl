import type { MainWallet } from '../../api';
import { explorerTx, formatAmount } from '../../format';
import { ExternalLink, formatTime, Section } from './parts';

/** Leftovers that came back to the main wallet (GET /main recent_sweeps), each with its transaction. */
export function SweepsPanel({ main }: { main?: MainWallet }) {
  const sweeps = main?.recent_sweeps ?? [];
  return <Section name="sweeps" title="Recent sweeps">
    <p className="settings-note">RLUSD that returned to the main wallet when a wallet finished, expired, or was recovered.</p>
    {!main ? <p className="settings-note">Sweeps load with the main wallet.</p>
      : !sweeps.length ? <p className="settings-empty">No sweeps yet. Leftover RLUSD returns here when a wallet is done.</p>
        : <ul className="settings-cards">{sweeps.map((sweep, i) => {
          const href = explorerTx(sweep.hash);
          return <li key={`${sweep.deployment}-${sweep.at}-${i}`} className="settings-card settings-sweep" data-deployment={sweep.deployment}>
            <div className="settings-card-head"><strong>{sweep.wallet ?? sweep.deployment}</strong><time dateTime={sweep.at}>{formatTime(sweep.at)}</time></div>
            <dl className="settings-card-meta">
              <dt>Returned</dt><dd data-field="returned">{formatAmount(sweep.returned)}</dd>
              <dt>Why</dt><dd data-field="why">{sweep.why ?? '—'}</dd>
              <dt>Proof</dt><dd data-field="proof">{href ? <ExternalLink href={href}>View on testnet</ExternalLink> : 'No transaction recorded'}</dd>
            </dl>
          </li>;
        })}</ul>}
  </Section>;
}
