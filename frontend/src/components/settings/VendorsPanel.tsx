import { useCallback, useEffect, useRef, useState } from 'react';
import { api, describeError, type Vendor } from '../../api';
import { explorerAccount, explorerTx, formatAmount, shortAddress } from '../../format';
import { ExternalLink, formatTime, plural, RefreshButton, Section } from './parts';

function credentialText(vendor: Vendor): string {
  const credential = vendor.credential;
  switch (credential?.status ?? 'none') {
    case 'valid': return credential?.expiration ? `Valid credential until ${formatTime(credential.expiration)}` : 'Valid credential';
    case 'revoked': return 'Credential revoked';
    case 'expired': return 'Credential expired';
    case 'none': return 'No credential';
    default: return `Credential ${credential?.status}`;
  }
}

function VendorCard({ vendor }: { vendor: Vendor }) {
  const status = vendor.credential?.status ?? 'none';
  const revocation = vendor.credential?.revocation;
  const revocationHref = revocation?.explorer ?? explorerTx(revocation?.hash);
  const items = vendor.items ?? [];
  const paid = vendor.paid?.count ?? 0;
  return <li className="settings-card settings-vendor" data-vendor={vendor.name} data-credential={status}>
    <div className="settings-card-head"><strong>{vendor.name}</strong>
      <ExternalLink href={explorerAccount(vendor.address)} title={vendor.address}>{shortAddress(vendor.address)}</ExternalLink></div>
    <p className="settings-credential">
      <span>{credentialText(vendor)}{status === 'revoked' && revocation?.reason ? `: ${revocation.reason}` : ''}</span>
      {status === 'revoked' && (revocationHref
        ? <ExternalLink href={revocationHref}>Revocation transaction</ExternalLink>
        : <span className="settings-sub">No revocation transaction recorded</span>)}
    </p>
    <dl className="settings-card-meta">
      <dt>Items</dt><dd data-field="items">{items.length ? items.map(i => `${i.item} ${formatAmount(i.price)}`).join(' · ') : 'No priced items'}</dd>
      <dt>Paid</dt><dd data-field="paid">{plural(paid, 'payment')} · {formatAmount(vendor.paid?.rlusd ?? '0')}</dd>
      <dt>Refused</dt><dd data-field="refused">{plural(vendor.refused?.count ?? 0, 'payment')}</dd>
    </dl>
  </li>;
}

/** The panel's own GET /vendors result, tied to the store list it was read against. */
interface OwnRead { base: Vendor[]; list?: Vendor[]; error?: string }

/** I06: every vendor cereal knows, its on-ledger credential, prices, and what was paid or refused (GET /vendors).
 * app.live.vendors is the source. Refresh reads GET /vendors right away; that result (or its error) is shown until
 * the store's own 60-second read delivers a newer list. */
export function VendorsPanel({ vendors }: { vendors: Vendor[] }) {
  const store = useRef(vendors);
  store.current = vendors;
  const [own, setOwn] = useState<OwnRead>();
  const [loading, setLoading] = useState(false);
  const alive = useRef(true);
  const latest = useRef(0);
  const load = useCallback(async () => {
    const ticket = ++latest.current;
    const base = store.current;
    setLoading(true);
    try {
      const list = await api.vendors();
      if (alive.current && ticket === latest.current) setOwn({ base, list });
    } catch (e) {
      if (alive.current && ticket === latest.current) setOwn({ base, error: describeError(e) });
    } finally {
      if (alive.current && ticket === latest.current) setLoading(false);
    }
  }, []);
  // The store's list is empty until its first read finishes; then the panel reads once itself.
  useEffect(() => {
    alive.current = true;
    if (!store.current.length) load();
    return () => { alive.current = false; };
  }, [load]);
  const current = own?.base === vendors ? own : undefined;
  const shown = current?.list ?? vendors;
  return <Section name="vendors" title="Vendors" action={<RefreshButton label="Refresh vendors" busy={loading} onClick={load} />}>
    <p className="settings-note">Trust is an XLS-70 credential cereal issues on the ledger. A revocation is a public CredentialDelete transaction.</p>
    {current?.error && <p className="settings-error" role="alert">Could not read vendors: {current.error}</p>}
    {shown.length
      ? <ul className="settings-cards">{shown.map(v => <VendorCard key={v.address} vendor={v} />)}</ul>
      : loading ? <p className="settings-note" role="status">Loading vendors…</p>
        : !current?.error && <p className="settings-empty">No vendors are registered with cereal yet.</p>}
  </Section>;
}
