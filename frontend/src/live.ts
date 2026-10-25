/** I01: the live data contract. Maps the cereal service's records onto the UI's Wallet view model while keeping every
 * exact amount as a decimal string in `wallet.live`. Treasury, available, budget, spent, pending and returned are
 * distinct fields; a payment counts as spent only once the ledger validated it. */
import type { ApiRecord, Folder, Payment, Vendor } from './api';
import { shortAddress, sumDecimals } from './format';
import type { Wallet, Workspace } from './wallets';

export interface LiveInfo {
  status: string;
  /** The subwallet's address on testnet. */
  address?: string;
  /** On-ledger RLUSD the wallet holds now; null when the ledger could not be read. */
  available: string | null;
  /** RLUSD the owner approved for this wallet (the original budget plus any top-ups). */
  budget: string;
  /** Validated payments only. */
  spent: string;
  /** Payments handed to a vendor or submitted but not yet validated. */
  pending: string;
  /** RLUSD returned to the main wallet when the wallet was reclaimed. */
  returned: string;
  approval: string | null;
  expiresAt: string;
  createdAt?: string;
  payees: string[];
  record: ApiRecord;
}

export const ACTIVE_STATUSES = ['active', 'deploying'];
export const isActive = (wallet: Wallet) => !wallet.live || ACTIVE_STATUSES.includes(wallet.live.status);

export const paymentState = (p: Payment): 'settled' | 'failed' | 'pending' =>
  p.ok === true ? 'settled' : p.ok === false ? 'failed' : 'pending';

export function vendorName(address: string, vendors: Vendor[]): string {
  return vendors.find(v => v.address === address)?.name ?? shortAddress(address);
}

/** "http://localhost:8003/swell/agenda" → "Swell agenda". */
export function resourceTitle(resource?: string | null): string {
  if (!resource) return 'Payment';
  try {
    const parts = new URL(resource).pathname.split('/').filter(Boolean);
    const text = parts.join(' ').replace(/[-_]/g, ' ');
    return text ? text[0].toUpperCase() + text.slice(1) : 'Payment';
  } catch { return resource; }
}

export function toWallet(rec: ApiRecord, vendors: Vendor[]): Wallet {
  const payments = rec.payments ?? [];
  const created = rec.created_at ? Date.parse(rec.created_at) : NaN;
  const expires = Date.parse(rec.expires_at);
  const days = Number.isFinite(created) && Number.isFinite(expires) ? Math.max(1, Math.ceil((expires - created) / 86_400_000)) : 1;
  const budget = rec.budget;
  const live: LiveInfo = {
    status: rec.status, address: rec.subwallet, available: rec.balance ?? null, budget,
    spent: sumDecimals(payments.filter(p => paymentState(p) === 'settled').map(p => p.amount)),
    pending: sumDecimals(payments.filter(p => paymentState(p) === 'pending').map(p => p.amount)),
    returned: rec.returned ?? '0', approval: rec.approval_threshold ?? null, expiresAt: rec.expires_at,
    createdAt: rec.created_at, payees: rec.allowed_payees ?? [], record: rec,
  };
  return {
    id: rec.id, name: rec.name || rec.task, description: rec.sentence || rec.task, live,
    balance: Number(rec.balance ?? 0), archived: rec.archived === true, folderId: rec.folder || undefined,
    constraints: {
      spend: Number(budget), days, approval: Number(rec.approval_threshold ?? 0), sweep: rec.sweep_when_done === true,
      merchants: (rec.allowed_payees ?? []).map(address => vendorName(address, vendors)),
    },
    transactions: payments.map((p, i) => ({
      id: p.hash ?? `${rec.id}-payment-${i}`, title: resourceTitle(p.resource), merchant: vendorName(p.to, vendors),
      amount: Number(p.amount), durationSeconds: 0, timestamp: p.at ?? rec.created_at ?? new Date(0).toISOString(),
    })),
  };
}

/** Active wallets first, newest first within each group. Folders are keyed by name in the UI (records store the
 * folder's name), whatever id the backend gives them. */
export function toWorkspace(records: ApiRecord[], vendors: Vendor[], folders: Folder[]): Workspace {
  const wallets = records.map(rec => toWallet(rec, vendors)).sort((a, b) =>
    Number(isActive(b)) - Number(isActive(a)) || Date.parse(b.live?.createdAt ?? '') - Date.parse(a.live?.createdAt ?? ''));
  const names = [...folders.map(f => f.name), ...wallets.map(w => w.folderId).filter((f): f is string => !!f)];
  return { wallets, folders: [...new Set(names)].map(name => ({ id: name, name })) };
}
