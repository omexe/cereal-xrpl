/** I04/V04: pure mapping from a backend record (GET /subagents/{id}) to the live wallet view. Amounts stay RLUSD decimal
 * strings. A payment is spending only once it settled with a validated hash (CLAUDE.md: never claim settlement
 * without one); refused attempts, cereal's or the ledger's, are evidence and never spending. */
import { REFUSAL_TEXT, type ApiRecord, type Payment, type Plan, type RecordRefusal, type Vendor } from './api';
import { explorerTx, shortAddress, sumDecimals } from './format';
import { resourceTitle } from './live';

/** XRPL EVM sidechain explorer: AP4M redemptions and channel closes carry 0x hashes, not XRPL ones. */
export const EVM_EXPLORER = 'https://explorer.testnet.xrplevm.org';

export type NameOf = (address?: string | null) => string;

/** Payee names from the vendor directory; a URL payee (AP4M) shows its host; anything else a short address. */
export function nameLookup(vendors: Vendor[] = []): NameOf {
  const known = new Map(vendors.map(v => [v.address, v.name]));
  return address => {
    if (!address) return 'Unknown payee';
    const name = known.get(address);
    if (name) return name;
    if (/^https?:\/\//i.test(address)) { try { return new URL(address).host; } catch { return address; } }
    return shortAddress(address);
  };
}

/** Explorer link for a transaction hash. The backend's own link wins when it is a plain https URL. */
export function txLink(hash?: string | null, explorer?: unknown): string | undefined {
  if (typeof explorer === 'string' && /^https:\/\//i.test(explorer)) return explorer;
  if (!hash) return undefined;
  return /^0x/i.test(hash) ? `${EVM_EXPLORER}/tx/${hash}` : explorerTx(hash);
}

export const shortHash = (hash: string) => hash.length > 14 ? `${hash.slice(0, 6)}…${hash.slice(-4)}` : hash;

const isDecimal = (v: unknown): v is string => typeof v === 'string' && /^\d+(\.\d+)?$/.test(v);

export type PaymentStatus = 'settled' | 'pending' | 'failed';

/** Settled = a success the ledger validated, with its hash: XRPL rails carry validated=true, AP4M redemptions are read
 * back from the XRPL EVM chain. ok=true without that evidence is still "not settled yet"; ok=false is failed. */
export function paymentStatus(p: Payment): PaymentStatus {
  if (p.ok === false) return 'failed';
  if (p.ok === true && p.hash && (p.validated === true || p.rail === 'ap4m')) return 'settled';
  return 'pending';
}

const STATUS_RANK: Record<PaymentStatus, number> = { pending: 0, failed: 1, settled: 2 };

/** One entry per ledger transaction: a hash recorded twice (a re-presented x402 blob) counts once, keeping its most
 * final state. Entries without a hash are kept as they are. Order: first appearance. */
export function uniquePayments(payments: Payment[] = []): Payment[] {
  const out: Payment[] = [];
  const at = new Map<string, number>();
  for (const p of payments) {
    const i = p.hash ? at.get(p.hash) : undefined;
    if (i === undefined) { if (p.hash) at.set(p.hash, out.length); out.push(p); continue; }
    if (STATUS_RANK[paymentStatus(p)] > STATUS_RANK[paymentStatus(out[i])]) out[i] = p;
  }
  return out;
}

/** Validated spending and money still in flight, from unique payments. */
export function spending(payments: Payment[]): { spent: string; pending: string } {
  return {
    spent: sumDecimals(payments.filter(p => paymentStatus(p) === 'settled').map(p => p.amount)),
    pending: sumDecimals(payments.filter(p => paymentStatus(p) === 'pending').map(p => p.amount)),
  };
}

export interface MerchantTotal { address: string; merchant: string; amount: string; color: string }

/** Settled spending per merchant, in the order each merchant was first paid. One bar segment and legend entry each. */
export function settledByMerchant(payments: Payment[], nameOf: NameOf): MerchantTotal[] {
  const groups = new Map<string, string[]>();
  for (const p of payments) if (paymentStatus(p) === 'settled') groups.set(p.to, [...(groups.get(p.to) ?? []), p.amount]);
  return [...groups].map(([address, amounts], i) => ({
    address, merchant: nameOf(address), amount: sumDecimals(amounts), color: `var(--color-chart-${i % 3 + 1})`,
  }));
}

/** Bar width of one merchant: its settled total over the greater of the budget and total settled spending. */
export function segmentWidth(amount: string, spent: string, budget: string): number {
  const scale = Math.max(Number(spent), Number(budget));
  return scale > 0 ? Number(amount) / scale * 100 : 0;
}

export const RAIL_LABEL: Record<string, string> = { x402: 'x402', direct: 'direct', ap4m: 'AP4M' };
const railLabel = (rail: unknown) => typeof rail === 'string' && rail ? RAIL_LABEL[rail] ?? rail : undefined;

export interface PaymentItem {
  kind: 'payment'; key: string; at?: string; title: string; address: string; merchant: string; amount: string;
  state: PaymentStatus; stateLabel: string; rail?: string; hash?: string; link?: string;
  /** Present when the owner's Ledger signed instead of cereal (the payment was above the approval threshold). */
  ledger?: { threshold: string | null };
}

export interface RefusalItem {
  /** refusal: cereal refused to co-sign (nothing was signed or sent). ledger: the ledger itself rejected an attempt
   * (tef: never applied; tec: included, no RLUSD moved), reported by a subagent or demo beat. */
  kind: 'refusal' | 'ledger'; key: string; at?: string; code: string; reason: string; stateLabel: string;
  detail?: string; payee?: string; amount?: string; rail?: string; hash?: string; link?: string; linkLabel?: string;
  verified?: boolean | null;
  /** cereal refusals: the public CredentialDelete that revoked this vendor, when that is why cereal refused. */
  revocation?: { hash?: string; link?: string; reason?: string };
}

export type ActivityItem = PaymentItem | RefusalItem;

export function paymentStateLabel(p: Payment): string {
  const state = paymentStatus(p);
  if (state === 'settled') return 'Settled';
  if (state === 'pending') return 'Pending — not settled yet';
  // A preliminary tesSUCCESS that never validated is a failure to validate, not a success code.
  return p.result && !/^tes/.test(p.result) ? `Failed ${p.result}` : 'Failed — never validated';
}

function paymentTitle(p: Payment): string {
  if (p.resource) return resourceTitle(p.resource);
  return p.rail === 'direct' ? 'Direct payment' : p.rail === 'ap4m' ? 'AP4M payment' : 'Payment';
}

export function toPaymentItem(p: Payment, index: number, rec: ApiRecord, nameOf: NameOf): PaymentItem {
  const threshold = p.approval?.threshold ?? rec.approval_threshold ?? null;
  return {
    kind: 'payment', key: p.hash ? `payment-${p.hash}` : `payment-${index}`, at: p.at, title: paymentTitle(p),
    address: p.to, merchant: nameOf(p.to), amount: p.amount, state: paymentStatus(p), stateLabel: paymentStateLabel(p),
    rail: railLabel(p.rail), hash: p.hash ?? undefined, link: txLink(p.hash, p.explorer),
    ledger: p.approved_by === 'ledger' ? { threshold } : undefined,
  };
}

/** Plain English for the codes cereal records on a refused payment (cereal/events.py PLAIN, worded for the owner). */
const REFUSAL_REASON: Record<string, string> = {
  payee_not_allowed: 'This vendor isn’t on the wallet’s list',
  over_budget: 'More than this wallet had left',
  expired: 'The wallet’s time had run out',
  not_rlusd: 'Wrong currency; only RLUSD is accepted',
  partial_payment_not_allowed: 'Payment shape not allowed (partial payment)',
  paths_not_allowed: 'Payment shape not allowed (payment paths)',
  send_max_not_allowed: 'Payment shape not allowed (it could overpay)',
  memo_mismatch: 'The payment wasn’t tagged to this wallet',
  owner_rejected: 'You said no on your Ledger',
  device_unavailable: 'Your Ledger wasn’t connected',
  device_error: 'Your Ledger didn’t finish signing',
  price_above_limit: 'The price was above what the subagent may pay',
  unknown_or_inactive_deployment: 'The wallet wasn’t active',
  not_a_subwallet_payment: 'It wasn’t a payment from this wallet',
  ap4m_error: 'The AP4M payment did not go through',
};

const CREDENTIAL_REASON: Record<string, string> = {
  revoked: 'The vendor’s cereal credential was revoked',
  expired: 'The vendor’s cereal credential had expired',
  pending: 'The vendor hadn’t accepted its cereal credential',
};

export function refusalCode(r: RecordRefusal): string {
  return r.refused || (typeof r.result === 'string' ? r.result : '') || 'refused';
}

export function refusalReason(r: RecordRefusal): string {
  const code = refusalCode(r);
  if (code === 'vendor_not_credentialed') return CREDENTIAL_REASON[r.vendor?.status ?? ''] ?? 'The vendor has no cereal credential';
  return REFUSAL_REASON[code] ?? REFUSAL_TEXT[code]?.replace(/\.$/, '') ?? code.replace(/_/g, ' ');
}

const str = (v: unknown) => typeof v === 'string' || typeof v === 'number' ? String(v) : undefined;

function refusalDetail(r: RecordRefusal): string | undefined {
  const code = refusalCode(r);
  const remaining = str(r.remaining);
  if (code === 'over_budget' && isDecimal(remaining)) return `${remaining} RLUSD was left`;
  const threshold = str(r.threshold) ?? str((r.approval as { threshold?: unknown } | undefined)?.threshold);
  if (threshold && /^(device_|owner_)/.test(code)) return `Asked your Ledger: above the ${threshold} RLUSD threshold`;
  return undefined;
}

export function toRefusalItem(r: RecordRefusal, index: number, nameOf: NameOf): RefusalItem {
  const code = refusalCode(r);
  const revocation = r.vendor?.revocation;
  return {
    kind: 'refusal', key: `refusal-${index}`, at: r.at, code, reason: refusalReason(r), detail: refusalDetail(r),
    stateLabel: 'Refused · nothing sent',
    payee: nameOf(r.payee ?? (typeof r.to === 'string' ? r.to : undefined)),
    // not_rlusd records the offered amount in another currency (XRP drops, another IOU): never label it RLUSD.
    amount: code !== 'not_rlusd' && isDecimal(r.amount) ? r.amount : undefined,
    rail: railLabel(r.rail),
    revocation: revocation && (revocation.hash || revocation.explorer)
      ? { hash: revocation.hash, link: txLink(revocation.hash, revocation.explorer), reason: revocation.reason } : undefined,
  };
}

/** Ledger-level refusals a subagent or demo beat reported (POST /subagents/{id}/events; cereal/events.py). */
export interface LedgerEvent { kind: string; result?: string; hash?: string | null; verified?: boolean | null; at?: string; detail?: unknown }

const LEDGER_EVENT: Record<string, string> = {
  hijack_alone: 'A hijacked subagent signed a payment by itself',
  stolen_keys_drain: 'Stolen subagent and cereal keys tried to take more than the wallet holds',
  stolen_keys_main_wallet: 'Stolen keys tried to spend from the main wallet',
  prove_lock: 'The subagent signed a payment by itself (lock check)',
};
const LEDGER_RESULT: Record<string, string> = {
  tefBAD_QUORUM: 'One signature isn’t enough to move this wallet’s money',
  tecPATH_PARTIAL: 'More than the wallet holds; no RLUSD moved',
  tefBAD_SIGNATURE: 'These keys can’t touch the main wallet',
  tefMASTER_DISABLED: 'The wallet’s master key is disabled',
};

export function toLedgerItem(e: LedgerEvent, index: number): RefusalItem {
  const result = e.result ?? 'refused';
  const hash = typeof e.hash === 'string' && e.hash ? e.hash : undefined;
  const verified = e.verified ?? null;
  return {
    kind: 'ledger', key: `ledger-${index}`, at: e.at, code: result, verified,
    reason: LEDGER_EVENT[e.kind] ?? e.kind.replace(/_/g, ' '), stateLabel: `Blocked by the ledger · ${result}`,
    detail: [LEDGER_RESULT[result], verified === true ? 'Verified on the ledger' : verified === false
      ? 'Not verified: the ledger shows a different result' : 'Reported by the subagent; no transaction to check']
      .filter(Boolean).join(' · '),
    hash, link: txLink(hash), linkLabel: hash ? shortHash(hash) : undefined,
  };
}

const ledgerEvents = (rec: ApiRecord): LedgerEvent[] =>
  Array.isArray(rec.events) ? (rec.events as unknown[]).filter((e): e is LedgerEvent =>
    !!e && typeof e === 'object' && typeof (e as LedgerEvent).kind === 'string') : [];

/** Payments, cereal's refusals and the ledger's in one list, newest first (entries without a time keep their order,
 * last). Payments are unique per hash. */
export function activityItems(rec: ApiRecord, nameOf: NameOf): ActivityItem[] {
  const items: ActivityItem[] = [
    ...uniquePayments(rec.payments).map((p, i) => toPaymentItem(p, i, rec, nameOf)),
    ...(rec.refusals ?? []).map((r, i) => toRefusalItem(r, i, nameOf)),
    ...ledgerEvents(rec).map(toLedgerItem),
  ];
  const time = (item: ActivityItem) => { const t = Date.parse(item.at ?? ''); return Number.isFinite(t) ? t : -Infinity; };
  return items.map((item, i) => ({ item, i })).sort((a, b) => time(b.item) - time(a.item) || a.i - b.i).map(({ item }) => item);
}

/** "2 settled · 1 refused · 3 blocked by the ledger"; empty when nothing happened. */
export function activitySummary(items: ActivityItem[]): string {
  const count = (pred: (item: ActivityItem) => boolean) => items.filter(pred).length;
  const parts: [number, string][] = [
    [count(i => i.kind === 'payment' && i.state === 'settled'), 'settled'],
    [count(i => i.kind === 'payment' && i.state === 'pending'), 'pending'],
    [count(i => i.kind === 'payment' && i.state === 'failed'), 'failed'],
    [count(i => i.kind === 'refusal'), 'refused'],
    [count(i => i.kind === 'ledger'), 'blocked by the ledger'],
  ];
  return parts.filter(([n]) => n > 0).map(([n, label]) => `${n} ${label}`).join(' · ');
}

const PLAN_REASON: Record<string, string> = {
  not_on_your_list: 'not one of the vendors you named',
  vendor_revoked: 'its cereal credential is revoked',
  vendor_expired: 'its cereal credential expired',
  vendor_pending: 'it hasn’t accepted its cereal credential',
  vendor_none: 'it has no cereal credential',
  vendor_unreachable: 'it did not answer',
  no_rlusd_option: 'it does not take RLUSD',
  price_above_limit: 'its price is above the limit',
};

export function planReason(reason?: string): string {
  if (!reason) return 'skipped';
  const http = reason.match(/^no_paywall_http_(\d+)$/);
  if (http) return `its paywall answered HTTP ${http[1]}`;
  return PLAN_REASON[reason] ?? reason.replace(/_/g, ' ');
}

export interface Skipped { vendor: string; price?: string; reason: string; link?: string }

/** The planner's skipped vendors, one line per vendor and reason (a vendor skipped for two items appears once). */
export function planSkipped(plan?: Plan | null): Skipped[] {
  const seen = new Set<string>();
  const out: Skipped[] = [];
  for (const line of plan?.rejected ?? []) {
    const vendor = line.vendor || 'A vendor';
    const id = `${vendor}|${line.reason ?? ''}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const evidence = line.evidence;
    const hash = typeof evidence === 'string' ? evidence
      : evidence && typeof evidence === 'object' ? str((evidence as { hash?: unknown }).hash) : undefined;
    out.push({ vendor, price: isDecimal(line.price) ? line.price : undefined, reason: planReason(line.reason),
      link: hash ? txLink(hash) : undefined });
  }
  return out;
}

export interface Proof { key: string; label: string; hash: string; link: string }

/** Lifecycle order. Keys this list does not know (a top-up's trust-line raise, say) sit after funding, before reclaim. */
const PROOF_ORDER = ['activate', 'lock', 'fund', 'topup', 'topups', '*', 'reclaim', 'recover', 'ap4m_close', 'retire'];
const PROOF_LABEL: Record<string, string> = {
  activate: 'Activate', lock: 'Lock', fund: 'Fund', topup: 'Top-up', topups: 'Top-up', reclaim: 'Reclaim',
  recover: 'Recover', retire: 'Retire', ap4m_close: 'AP4M channel close',
};
/** The sequential lock (cereal/lock.py): TrustSet limit = budget, SignerListSet, AccountSet asfDisableMaster. */
const LOCK_STEPS = ['Lock · trust line', 'Lock · signer list', 'Lock · master key off'];
const AFTER_FUNDING = PROOF_ORDER.indexOf('*');

const proofLabel = (key: string) => PROOF_LABEL[key] ?? (key.charAt(0).toUpperCase() + key.slice(1)).replace(/_/g, ' ');
const proofRank = (key: string) => { const i = PROOF_ORDER.indexOf(key); return i < 0 ? AFTER_FUNDING : i; };

/** Every lifecycle transaction on the record (activate, lock, fund, reclaim, retire, and any other key such as a
 * top-up), each with its explorer link, where its result can be read. Missing (null) hashes are left out. */
export function lifecycleProofs(rec: ApiRecord): Proof[] {
  const seen = new Set<string>();
  const entries: { rank: number; proof: Proof }[] = [];
  const add = (rank: number, key: string, label: string, hash: string) => {
    const link = txLink(hash);
    if (seen.has(hash) || !link) return;
    seen.add(hash);
    entries.push({ rank, proof: { key, label, hash, link } });
  };
  const hashes = rec.hashes ?? {};
  for (const key of Object.keys(hashes)) {
    const raw = hashes[key];
    const values = (Array.isArray(raw) ? raw : [raw]).filter((h): h is string => typeof h === 'string' && h.length > 0);
    values.forEach((hash, i) => add(proofRank(key), `hash-${key}-${i}`,
      key === 'lock' && values.length === LOCK_STEPS.length ? LOCK_STEPS[i]
        : values.length > 1 ? `${proofLabel(key)} ${i + 1}/${values.length}` : proofLabel(key), hash));
  }
  // Top-ups recorded only in `topups` (A04), not in `hashes`.
  (rec.topups ?? []).forEach((topup, i) => {
    if (topup.hash) add(proofRank('topups'), `topup-record-${i}`, `Top-up ${isDecimal(topup.amount) ? `${topup.amount} RLUSD` : ''}`.trim(), topup.hash);
  });
  return entries.map((e, i) => ({ ...e, i })).sort((a, b) => a.rank - b.rank || a.i - b.i).map(e => e.proof);
}

/** The wallet's window as the card states it: "1 day", "3 days", "1 hour", "1.5 hours", "45 minutes"; null when the
 * record has no usable times. created_at and expires_at are stamped microseconds apart, so round to the minute. */
export function durationLabel(createdAt?: string, expiresAt?: string): string | null {
  const ms = Date.parse(expiresAt ?? '') - Date.parse(createdAt ?? '');
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'}`;
  const minutes = Math.max(1, Math.round(ms / 60_000));
  if (minutes < 60) return plural(minutes, 'minute');
  if (minutes % 1440 === 0) return plural(minutes / 1440, 'day');
  return plural(Math.round(minutes / 60 * 100) / 100, 'hour');
}

export const isExpired = (expiresAt?: string, now = Date.now()) => {
  const t = Date.parse(expiresAt ?? '');
  return Number.isFinite(t) && now >= t;
};

export const STATUS_LABEL: Record<string, string> = {
  active: 'Active', deploying: 'Deploying', reclaimed: 'Reclaimed', recovered: 'Recovered', retired: 'Retired',
  rejected: 'Rejected', failed: 'Failed',
};
export const statusLabel = (status: string) => STATUS_LABEL[status] ?? status.replace(/_/g, ' ');
