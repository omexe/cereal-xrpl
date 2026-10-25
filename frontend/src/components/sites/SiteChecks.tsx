import { AlertTriangle, CheckCircle, SlashCircle01, XCircle } from '@untitledui/icons';
import type { SiteCheck, SiteProbe } from '../../api';
import { checkName, checkState, credentialText, extraReason, kindText, TRUST_LABEL, TRUST_TEXT, VERDICT_TEXT, type TrustTier } from './siteText';

type Probed = Omit<SiteProbe, 'ok'>;

/** A trust tier as a small marker (sidebar rows) or a labelled badge (site view, probe card). */
export function TrustMarker({ trust }: { trust: TrustTier }) {
  return <span className="site-marker" data-trust={trust} aria-hidden="true" />;
}

export function TrustBadge({ trust }: { trust: TrustTier }) {
  return <span className="site-trust" data-trust={trust}>{TRUST_LABEL[trust]}</span>;
}

/** What the trust means for who pays and who signs, in one line. */
export function TrustNote({ trust, prefix }: { trust: TrustTier; prefix?: string }) {
  return <div className="site-trust-note" data-trust={trust}>
    <p>{prefix && <span className="site-trust-prefix">{prefix} </span>}<TrustBadge trust={trust} /></p>
    <p className="site-trust-text">{TRUST_TEXT[trust]}</p>
  </div>;
}

function CheckIcon({ ok }: { ok: boolean | null }) {
  return ok === true ? <CheckCircle aria-hidden="true" /> : ok === false ? <XCircle aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />;
}

export function CheckList({ checks }: { checks: SiteCheck[] }) {
  if (!checks.length) return null;
  return <ul className="site-checks" aria-label="Automatic checks">
    {checks.map(check => <li key={check.name} className="site-check" data-check={check.name} data-ok={String(check.ok)}>
      <CheckIcon ok={check.ok} />
      <span className="site-check-name">{checkName(check)}<span className="sr-only">: {checkState(check.ok)}</span></span>
      <span className="site-check-detail">{check.detail}</span>
    </li>)}
  </ul>;
}

/** The probe's findings: kind, credential, each check, and the verdict with its reasons. */
export function ProbeFindings({ probe }: { probe: Probed }) {
  const credential = probe.kind === 'payable' ? credentialText(probe.credential) : null;
  const reason = extraReason(probe);
  // A site cereal can neither read nor pay has no checks: its reason says why, and the trust note says it can't be added.
  const showVerdict = probe.kind === 'payable' && (probe.checks.length > 0 || probe.verdict_reasons.length > 0);
  return <>
    <p className="site-kind" data-kind={probe.kind}>{kindText(probe)}</p>
    {reason && <p className="site-reason">{reason}</p>}
    {probe.payment?.description && <p className="site-reason">{probe.payment.description}</p>}
    {credential && <p className="site-credential" data-credential={probe.credential ?? 'none'}>{credential}</p>}
    <CheckList checks={probe.checks} />
    {showVerdict && <div className="site-verdict" data-verdict={probe.verdict}>
      <p>Verdict: {VERDICT_TEXT[probe.verdict] ?? probe.verdict}</p>
      {probe.verdict_reasons.length > 0 && <ul aria-label="Verdict reasons">{probe.verdict_reasons.map(r => <li key={r}>{r}</li>)}</ul>}
    </div>}
  </>;
}

const archiveDate = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });

/** Why cereal can't use a site, as a notice the owner can't miss: a bot wall named plainly (and never bypassed), a
 * paywall in another currency, or a site that can't be reached. Offers a public archived copy when there is one. */
export function SiteNotice({ probe, onUseArchive }: { probe: Probed; onUseArchive?: (url: string) => void }) {
  if (probe.kind !== 'unreachable' && probe.kind !== 'unpayable') return null;
  const host = probe.host || probe.url;
  const walled = !!probe.blocked_by;
  const heading = walled ? `${host} blocks AI agents`
    : probe.kind === 'unpayable' ? `cereal can’t pay ${host}` : `cereal can’t reach ${host}`;
  const body = walled
    ? `This site uses ${probe.blocked_by === 'a captcha' ? 'a captcha' : `${probe.blocked_by}’s bot protection`} to keep automated visitors out. Only a person in a browser can get past it, so cereal can’t read it or buy from it, and it won’t try to get around it. Nothing was paid.`
    : probe.reason ?? 'cereal can neither read this site nor pay it in RLUSD on XRPL testnet. Nothing was paid.';
  return <div className="site-notice" role="alert" data-kind={probe.kind} data-walled={walled ? 'true' : undefined}>
    <SlashCircle01 aria-hidden="true" />
    <div>
      <p className="site-notice-heading">{heading}</p>
      <p>{body}</p>
      {walled && probe.archive && <>
        <p className="site-notice-hint">The {probe.archive.source} has a public copy from {archiveDate.format(new Date(probe.archive.timestamp))}.
          It is an older snapshot, not the live site.</p>
        {onUseArchive && <button type="button" className="secondary-button" onClick={() => onUseArchive(probe.archive!.url)}>Use the archived copy</button>}
      </>}
    </div>
  </div>;
}
