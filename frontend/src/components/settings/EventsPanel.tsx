import { api, REFUSAL_TEXT, type SecurityEvent } from '../../api';
import { ExternalLink, formatTime, plural, RefreshButton, Section, useRead } from './parts';

export const EVENT_LIMIT = 50;
const readEvents = () => api.events(EVENT_LIMIT);

const label = (kind: string) => { const text = kind.replace(/_/g, ' '); return text.charAt(0).toUpperCase() + text.slice(1); };
/** A bare refusal code ("device_error") reads as its plain-English sentence; prose from the service is kept. */
const reason = (why?: string) => !why ? '—' : Object.hasOwn(REFUSAL_TEXT, why) ? REFUSAL_TEXT[why] : why;

function EventCard({ event }: { event: SecurityEvent }) {
  return <li className="settings-card settings-event" data-kind={event.kind}>
    <div className="settings-card-head"><strong>{label(event.kind)}</strong><time dateTime={event.at}>{formatTime(event.at)}</time></div>
    {event.what && <p data-field="what">{event.what}</p>}
    <dl className="settings-card-meta">
      <dt>Wallet</dt><dd data-field="wallet">{event.wallet ?? event.deployment ?? '—'}</dd>
      <dt>Why</dt><dd data-field="why" title={event.code}>{reason(event.why)}</dd>
      <dt>Outcome</dt><dd data-field="outcome">{event.outcome ?? '—'}</dd>
      {event.by && <><dt>By</dt><dd data-field="by">{event.by}</dd></>}
      <dt>Proof</dt><dd data-field="proof">{event.proof
        ? <ExternalLink href={event.proof}>View on testnet</ExternalLink> : 'No ledger transaction'}</dd>
    </dl>
  </li>;
}

/** I07: the security feed (GET /events): every refusal and owner approval, who decided, why, and the proof. */
export function EventsPanel() {
  const { data: events, loading, error, reload } = useRead(readEvents);
  return <Section name="events" title="Security events" action={<RefreshButton label="Refresh security events" busy={loading} onClick={reload} />}>
    <p className="settings-note">Every refusal and owner approval, newest first{events?.length ? ` · latest ${plural(events.length, 'event')}` : ''}.</p>
    {error && <p className="settings-error" role="alert">Could not read security events: {error}</p>}
    {events === undefined
      ? loading && <p className="settings-note" role="status">Loading security events…</p>
      : events.length === 0
        ? <p className="settings-empty">No security events yet. Refused payments, skipped vendors and owner approvals appear here with their proof.</p>
        : <ol className="settings-cards settings-events" tabIndex={0} aria-label="Security events">
          {events.map((event, i) => <EventCard key={`${event.at}-${event.kind}-${i}`} event={event} />)}
        </ol>}
  </Section>;
}
