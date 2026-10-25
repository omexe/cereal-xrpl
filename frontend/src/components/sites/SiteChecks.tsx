import { AlertTriangle, CheckCircle, XCircle } from '@untitledui/icons';
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
