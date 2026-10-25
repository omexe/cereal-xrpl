/** Plain words for Sites (docs/SITES.md): what a probe found, what each check means, and what each trust tier lets
 * a wallet do. Shared by the sidebar, the Add site dialog and the site view. */
import { ApiError, describeError, REFUSAL_TEXT, type Site, type SiteCheck, type SiteProbe, type SiteTrust } from '../../api';
import { formatAmount, shortAddress } from '../../format';

export type TrustTier = SiteTrust | 'none';

export const TRUST_LABEL: Record<TrustTier, string> = {
  public: 'Public', private: 'Private to you', free: 'Free', blocked: 'Blocked', none: 'Can’t be added',
};

export const TRUST_TEXT: Record<TrustTier, string> = {
  public: 'A cereal-credentialed vendor: cereal co-signs each payment within the wallet’s rules.',
  private: 'Only your wallets can pay it, and your Ledger signs every payment.',
  free: 'Nothing to pay: cereal reads the page directly.',
  blocked: 'Nobody can pay it. cereal keeps the reason and the evidence.',
  none: 'cereal can neither read this site nor pay it in RLUSD on XRPL testnet.',
};

export const CHECK_NAME: Record<string, string> = {
  asset: 'Asset', price: 'Price', payee_exists: 'Payee account', payee_rlusd: 'RLUSD trust line',
  domain_proof: 'Domain proof', payee_history: 'Payee history', credential: 'cereal credential',
};
export const checkName = (check: SiteCheck) => CHECK_NAME[check.name] ?? check.name.replace(/_/g, ' ');
export const checkState = (ok: boolean | null | undefined) => ok === true ? 'passed' : ok === false ? 'failed' : 'could not tell';

export const CREDENTIAL_TEXT: Record<string, string> = {
  valid: 'Valid cereal credential', revoked: 'cereal credential revoked', expired: 'cereal credential expired',
  none: 'No cereal credential',
};
export const credentialText = (credential?: string | null) => credential ? CREDENTIAL_TEXT[credential] ?? `Credential: ${credential}` : null;

export const VERDICT_TEXT: Record<SiteProbe['verdict'], string> = {
  ok: 'No problems found', warn: 'Warnings', block: 'Blocked',
};

/** Why a stored site is blocked, from its code or sentence. */
const BLOCKED_TEXT: Record<string, string> = {
  paid_not_delivered: 'The site took a payment and did not deliver what was paid for.',
  credential_revoked: 'The payee’s cereal credential was revoked.',
  probe: 'An automatic check failed.',
};
export function blockedText(reason?: string | null): string {
  if (!reason) return 'An automatic check failed.';
  return BLOCKED_TEXT[reason] ?? REFUSAL_TEXT[reason] ?? reason;
}

const NETWORKS: Record<string, string> = {
  'xrpl:0': 'XRPL mainnet', 'xrpl:1': 'XRPL testnet', 'xrpl:2': 'XRPL devnet',
  'eip155:84532': 'Base Sepolia', 'base-sepolia': 'Base Sepolia', 'eip155:8453': 'Base', base: 'Base',
  'eip155:1': 'Ethereum', 'eip155:11155111': 'Sepolia', 'eip155:1449000': 'XRPL EVM testnet',
};
const TOKENS: Record<string, string> = {
  '0x036cbd53842c5426634e7929541ec2318f3dcf7e': 'USDC',  // Base Sepolia
  '0x833589fcd6edb6e08f4c7c32d4f71b54bda02913': 'USDC',  // Base
};

/** "524C555344000000000000000000000000000000" → "RLUSD"; EVM token addresses by name when known. */
function assetName(asset?: string, network?: string): string {
  if (!asset) return network?.startsWith('xrpl') ? 'XRP' : 'an unnamed asset';
  if (/^[0-9a-f]{40}$/i.test(asset)) {
    const text = asset.match(/../g)!.map(h => String.fromCharCode(parseInt(h, 16))).join('').replace(/\0+$/, '');
    return /^[\x20-\x7e]+$/.test(text) ? text : asset;
  }
  if (TOKENS[asset.toLowerCase()]) return TOKENS[asset.toLowerCase()];
  return /^0x[0-9a-f]{40}$/i.test(asset) ? `token ${shortAddress(asset)}` : asset;
}
const networkName = (network?: string) => network ? NETWORKS[network] ?? network : 'an unnamed network';

/** What the site wants, from its 402 options: "USDC on Base Sepolia or XRP on XRPL testnet". */
export function wants(probe: Pick<SiteProbe, 'accepts'>): string | null {
  const options = [...new Set((probe.accepts ?? []).map(a => `${assetName(a.asset, a.network)} on ${networkName(a.network)}`))];
  return options.length ? options.join(' or ') : null;
}

/** The probe's kind in plain words: "Free page", "Paid: 0.10 RLUSD to rsV4…", "Can't pay: …", "Not reachable: …". */
export function kindText(probe: Pick<SiteProbe, 'kind' | 'payment' | 'accepts' | 'reason' | 'status'>): string {
  switch (probe.kind) {
    case 'free': return 'Free page';
    case 'payable': return probe.payment
      ? `Paid: ${formatAmount(probe.payment.amount)} to ${shortAddress(probe.payment.pay_to)}` : 'Paid in RLUSD';
    case 'unpayable': {
      const w = wants(probe);
      return w ? `Can’t pay: wants ${w}` : `Can’t pay: ${probe.reason ?? 'no RLUSD option on XRPL testnet'}`;
    }
    default: return `Not reachable: ${probe.reason ?? (probe.status ? `the site answered ${probe.status}` : 'no answer')}`;
  }
}

/** The reason, when it adds something the kind line does not already say. */
export function extraReason(probe: Pick<SiteProbe, 'kind' | 'payment' | 'accepts' | 'reason' | 'status'>): string | null {
  if (!probe.reason) return null;
  return kindText(probe).includes(probe.reason) ? null : probe.reason;
}

/** The trust a site has (stored) or would get (probe). */
export const trustOf = (site: Pick<SiteProbe, 'trust_hint'> & { trust?: SiteTrust }): TrustTier => site.trust ?? site.trust_hint ?? 'none';

/** A refusal's message plus its `reason`, when the backend gave one. */
export function refusalMessage(error: unknown): string {
  const message = describeError(error);
  if (!(error instanceof ApiError)) return message;
  const reason = (error.body as { reason?: unknown } | undefined)?.reason;
  return typeof reason === 'string' && reason && !message.includes(reason) ? `${message} ${reason}` : message;
}

/** A stored site's extra fields (unit 2): evidence kept when it was blocked. */
export interface BlockedInfo { evidence: Record<string, unknown> | null; at?: string; by?: string }
export function blockedInfo(site: Site): BlockedInfo {
  const s = site as Site & { blocked_evidence?: unknown; blocked_at?: unknown; blocked_by?: unknown };
  const evidence = s.blocked_evidence && typeof s.blocked_evidence === 'object' && !Array.isArray(s.blocked_evidence)
    ? s.blocked_evidence as Record<string, unknown> : null;
  return { evidence, at: typeof s.blocked_at === 'string' ? s.blocked_at : undefined, by: typeof s.blocked_by === 'string' ? s.blocked_by : undefined };
}

/** One per purchase attempt. randomUUID needs a secure context; fall back to getRandomValues elsewhere. */
export function newRequestId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map(x => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export function formatWhen(iso?: string | null): string | null {
  const t = Date.parse(iso ?? '');
  if (!Number.isFinite(t)) return null;
  return new Date(t).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}
