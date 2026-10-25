import { explorerAccount, formatAmount, trimDecimal } from '../../format';
import type { LiveData } from '../../store';
import { ExternalLink, formatTime, Section } from './parts';

const SERVICE_STATE: Record<LiveData['status'], string> = { loading: 'Connecting…', ready: 'Reachable', error: 'Not reachable' };

/** Whether the cereal service answers, and the main wallet it reports (GET /main through app.live). */
export function ConnectionPanel({ live, archived }: { live: LiveData; archived: number }) {
  const { status, error, main, updatedAt } = live;
  return <Section name="connection" title="Connection">
    <dl className="settings-rows">
      <dt>Mode</dt><dd data-field="mode">Live · XRPL testnet</dd>
      <dt>Service</dt><dd data-field="service" className={status === 'error' ? 'settings-down' : undefined}>{SERVICE_STATE[status]}</dd>
      <dt>Main wallet</dt><dd data-field="address">{main ? <ExternalLink href={explorerAccount(main.address)}>{main.address}</ExternalLink> : '—'}</dd>
      <dt>RLUSD</dt><dd data-field="rlusd">{main ? formatAmount(main.rlusd) : '—'}</dd>
      <dt>XRP</dt><dd data-field="xrp">{main ? `${trimDecimal(String(main.xrp))} XRP` : '—'}</dd>
      <dt>Outstanding budget</dt><dd data-field="outstanding">{main ? formatAmount(main.outstanding_budget) : '—'}</dd>
      <dt>Active wallets</dt><dd data-field="active">{main ? `${main.active_subagents} of ${main.caps.MAX_ACTIVE_SUBAGENTS}` : '—'}</dd>
      <dt>Archived wallets</dt><dd data-field="archived">{archived}</dd>
      <dt>Last updated</dt><dd data-field="updated">{updatedAt ? formatTime(updatedAt) : 'Not yet'}</dd>
    </dl>
    {status === 'loading' && !main && <p className="settings-note" role="status">Connecting to the cereal service…</p>}
    {status === 'error' && <p className="settings-error" role="alert">
      {error ?? 'The cereal service is not reachable.'} {main ? 'These are the last values it reported. ' : ''}Retrying automatically.
    </p>}
  </Section>;
}
