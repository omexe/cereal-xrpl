/** Typed client for the cereal service. Every amount is a decimal string in RLUSD on XRPL testnet.
 * Refusals ({ok: false, refused}) are results on the backend; here they throw ApiError('refused') carrying the body,
 * so a caller shows them instead of pretending something happened. Endpoints marked "contract" are implemented by
 * the feature routers in cereal/routes/. */
import { API_BASE } from './mode';
import { loadSession, type SessionUser } from './session';

export type Decimal = string;
export type Status = 'deploying' | 'active' | 'reclaimed' | 'recovered' | 'retired' | 'rejected' | 'failed';

export interface Refusal { ok: false; refused: string; [key: string]: unknown }

export interface DeviceApproval { by?: string; result?: string; threshold?: Decimal; screens?: string[] }

export interface Payment {
  to: string; amount: Decimal; rail?: 'x402' | 'direct' | 'ap4m' | string; resource?: string | null;
  /** true = validated on-ledger success; false = failed; null/undefined = not yet known (presented, pending). */
  ok?: boolean | null; result?: string; hash?: string; explorer?: string; at?: string; validated?: boolean;
  approved_by?: 'ledger' | string; approval?: DeviceApproval;
}

export interface RecordRefusal {
  payee?: string; amount?: Decimal; ok: false; refused: string; at?: string;
  vendor?: { status?: string; revocation?: { hash?: string; explorer?: string; reason?: string } };
  [key: string]: unknown;
}

export interface PlanLine { vendor?: string; url?: string; price?: Decimal; reason?: string; evidence?: unknown }
export interface Plan { item?: string; price?: Decimal; budget?: Decimal; vendor?: string; fallbacks?: PlanLine[]; rejected?: PlanLine[] }

export interface Run {
  id: string; deployment: string; status: 'starting' | 'running' | 'succeeded' | 'failed' | 'timed_out' | 'interrupted';
  started_at?: string; finished_at?: string | null; exit_code?: number | null; plan?: unknown; summary?: string | null; error?: string | null;
}

export interface ApiRecord {
  id: string; parent?: string; task: string; budget: Decimal; currency: 'RLUSD' | string;
  allowed_payees: string[]; vendor_class?: string; refusals?: RecordRefusal[]; expires_at: string; tag?: string;
  subwallet?: string; subagent?: string; status: Status | string; hashes?: Record<string, string | string[] | null>;
  payments?: Payment[]; summary?: string; created_at?: string; finished_at?: string; plan?: Plan;
  approval_threshold?: Decimal | null; name?: string; folder?: string | null; sentence?: string;
  sweep_when_done?: boolean; approval?: DeviceApproval; returned?: Decimal; reclaimed_at?: string;
  /** Live on-ledger RLUSD balance of the subwallet; "0" once reclaimed; null when the ledger could not be read. */
  balance: Decimal | null;
  /** contract (A06): presentation-only archive flag. */
  archived?: boolean;
  /** contract (A01): the latest run of this wallet's task. */
  run?: Run | null;
  /** contract (A04): owner-approved top-ups after the original budget. */
  topups?: { amount: Decimal; hash?: string; at?: string; approval?: DeviceApproval }[];
  [key: string]: unknown;
}

export interface Sweep { deployment: string; wallet?: string; returned: Decimal; at: string; why?: string; hash?: string }

export interface MainWallet {
  address: string; xrp: Decimal; rlusd: Decimal; outstanding_budget: Decimal; active_subagents: number;
  recent_sweeps: Sweep[];
  policy: { vendor_credentials: boolean; issuer: string; device_funding: boolean; ledger_recovery: boolean; device?: string;
    ap4m?: { enabled: boolean; [key: string]: unknown } };
  caps: { MAX_SUBAGENT_BUDGET: number; MAX_OUTSTANDING_BUDGET: number; MAX_ACTIVE_SUBAGENTS: number };
}

export interface Vendor {
  name: string; address: string; role?: string; url?: string; items?: { item: string; price: Decimal }[];
  paid?: { count: number; rlusd: Decimal }; refused?: { count: number };
  credential?: { status: 'valid' | 'revoked' | 'expired' | 'none' | string; issuer?: string; expiration?: string | null;
    revocation?: { hash?: string; explorer?: string; reason?: string; [key: string]: unknown } };
}

export interface SecurityEvent {
  deployment?: string; wallet?: string; at: string; by?: string; kind: string; code?: string;
  what?: string; why?: string; outcome?: string; proof?: string | null;
}

export interface CardVendor { named: string; address?: string | null; name?: string; credential?: string }
export interface WalletCard {
  ok: boolean; name: string; sentence: string; budget: Decimal; currency: string; expires_in_hours: number;
  vendors: CardVendor[]; allowed_payees: string[]; approval_threshold: Decimal | null; sweep_when_done: boolean;
  parsed_by?: string | null; problems: string[]; notes: string[]; summary: string;
  /** contract (R07): digest of the reviewed card; creation is refused if the rebuilt card differs. */
  digest?: string;
}
export interface WalletRequest {
  sentence: string; folder?: string | null; speculos_decision?: 'approve' | 'reject';
  speculos_payment_decision?: 'approve' | 'reject';
  /** contract (R07): the digest of the card the owner reviewed. */ card_digest?: string;
  /** contract (R03): retrying with the same id returns the original wallet. */ request_id?: string;
}
export type CreateResult = ApiRecord & { ok: true; card: WalletCard };

export interface RulesChange {
  sentence?: string; spend?: Decimal; expires_in_hours?: number; merchants?: string[];
  approval_threshold?: Decimal | null; sweep_when_done?: boolean;
}
export interface RulesPreview { ok: boolean; changes: string[]; problems: string[]; notes: string[]; rules?: Partial<ApiRecord> }
export interface RulesResult { ok: true; rules: Partial<ApiRecord>; changes: string[]; hashes?: Record<string, string> }

export interface FundRequest { amount: Decimal; request_id?: string; speculos_decision?: 'approve' | 'reject' }
export interface FundResult { ok: true; amount: Decimal; budget: Decimal; balance: Decimal | null; hashes: Record<string, string | null>; approval?: DeviceApproval }

export interface Folder { id: string; name: string }

// ---- Sites (docs/SITES.md) ----
export type SiteKind = 'free' | 'payable' | 'unpayable' | 'unreachable';
export type SiteTrust = 'public' | 'private' | 'free' | 'blocked';
export interface SiteCheck { name: string; ok: boolean | null; detail: string }
export interface SitePayment {
  network: string; asset: string; issuer: string; amount: Decimal; pay_to: string;
  resource?: string | null; description?: string | null; invoice_id?: string | null;
}
export interface SiteProbe {
  ok: true; url: string; origin: string; host: string; kind: SiteKind; status: number | null; title: string | null;
  payment: SitePayment | null; accepts: { network?: string; asset?: string; amount?: string }[];
  reason: string | null; credential: string | null; checks: SiteCheck[];
  verdict: 'ok' | 'warn' | 'block'; verdict_reasons: string[]; trust_hint: SiteTrust | 'none';
}
export interface Site extends Omit<SiteProbe, 'ok'> {
  id: string; owner: string; name: string; trust: SiteTrust; blocked_reason: string | null;
  added_at: string; probed_at: string; wallets?: string[];
}
export interface SiteOpen {
  ok: true; url: string; status: number; content_type: string | null; title: string | null; text: string;
  truncated: boolean; bytes: number;
}
export interface SiteContent { ok: true; wallet: string; hash: string | null; paid: Decimal | null; content: unknown }
export interface MetaChange { name?: string; folder?: string | null; archived?: boolean }

export class ApiError extends Error {
  constructor(public kind: 'network' | 'http' | 'refused', message: string, public status?: number, public body?: unknown) {
    super(message);
  }
  get refused(): string | undefined { return (this.body as Refusal | undefined)?.refused; }
}

/** Plain-English explanations for refusal codes the backend returns. Unknown codes fall back to the raw code. */
export const REFUSAL_TEXT: Record<string, string> = {
  cap_exceeded: 'That is above a company cap.',
  insufficient_main_balance: 'The main wallet does not hold enough RLUSD.',
  insufficient_main_xrp: 'The main wallet does not hold enough XRP to open another wallet.',
  device_unavailable: 'The Ledger is not connected.',
  owner_rejected: 'Rejected on the Ledger. Nothing was sent.',
  device_error: 'The Ledger did not finish signing. Nothing was sent.',
  card_problems: 'The description is missing something cereal needs.',
  card_changed: 'The rules changed since you reviewed them. Review them again.',
  not_active: 'This wallet is not active.',
  not_reclaimed: 'Reclaim this wallet before retiring it.',
  unknown_or_inactive_deployment: 'This wallet is not active.',
  vendor_not_credentialed: 'That vendor has no valid cereal credential.',
  payee_not_allowed: 'That vendor is not on this wallet’s list.',
  over_budget: 'That is more than this wallet holds.',
  expired: 'This wallet has expired.',
  no_payee_policy: 'Name at least one vendor.',
  subwallet_failed: 'The wallet could not be locked on the ledger. No budget was sent.',
  funding_failed: 'The wallet was locked but funding did not validate.',
  already_running: 'This wallet’s task is already running.',
  use_add_funds: 'Only Add funds can raise a wallet’s budget.',
  not_a_planned_purchase: 'Refused: this wallet may only buy what its plan lists.',
  invalid_url: 'That is not a web address cereal can open.',
  unsafe_url: 'cereal does not open private or local addresses.',
  not_accessible: 'An agent cannot reach this site.',
  site_blocked: 'This site is blocked.',
  not_payable: 'This site does not take RLUSD on XRPL testnet.',
  price_above_cap: 'That costs more than one site purchase may.',
  not_delivered: 'The site was paid but did not deliver.',
  nothing_bought: 'Nothing has been bought from this site yet.',
  invalid_name: 'Pick a name between 1 and 40 characters.',
};

export function describeRefusal(body: Refusal): string {
  return REFUSAL_TEXT[body.refused] ?? `Refused: ${body.refused.replace(/_/g, ' ')}.`;
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  let res: Response;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['content-type'] = 'application/json';
  const session = loadSession();  // Sites: the signed-in user's bearer token (docs/SITES.md)
  if (session) headers.authorization = `Bearer ${session.token}`;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method, headers, body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError('network', 'The cereal service is not reachable.');
  }
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = data && typeof data === 'object' && 'detail' in data ? String((data as { detail: unknown }).detail) : undefined;
    throw new ApiError('http', detail ?? (res.status >= 500 || res.status === 502 ? 'The cereal service is not reachable.' : `${res.status} ${res.statusText}`), res.status, data);
  }
  if (data && typeof data === 'object' && !Array.isArray(data) && (data as Refusal).ok === false && typeof (data as Refusal).refused === 'string') {
    throw new ApiError('refused', describeRefusal(data as Refusal), res.status, data);
  }
  return data as T;
}
const get = <T>(path: string) => request<T>('GET', path);
const post = <T>(path: string, body: unknown = {}) => request<T>('POST', path, body);
const id = (dep: string) => encodeURIComponent(dep);

export const api = {
  health: () => get<{ status: string; main: string; cosigner: string }>('/health'),
  main: () => get<MainWallet>('/main'),
  wallets: () => get<ApiRecord[]>('/subagents'),
  wallet: (dep: string) => get<ApiRecord>(`/subagents/${id(dep)}`),
  vendors: () => get<Vendor[]>('/vendors'),
  events: (limit = 200) => get<SecurityEvent[]>(`/events?limit=${limit}`),
  sweeps: (limit = 10) => get<Sweep[]>(`/sweeps?limit=${limit}`),
  exportUrl: (format: 'csv' | 'json') => `${API_BASE}/export.${format}`,
  previewWallet: (body: WalletRequest) => post<WalletCard>('/wallets/preview', body),
  createWallet: (body: WalletRequest) => post<CreateResult>('/wallets', body),
  done: (dep: string, summary: string) => post<ApiRecord & { swept?: unknown }>(`/subagents/${id(dep)}/done`, { summary }),
  reclaim: (dep: string) => post<{ ok: boolean; returned: Decimal; steps: unknown[] }>(`/subagents/${id(dep)}/reclaim`),
  retire: (dep: string) => post<{ ok: boolean; hash?: string; result?: string }>(`/subagents/${id(dep)}/retire`),
  // contract (A01/A02): cereal/routes/runs.py
  startRun: (dep: string) => post<{ ok: true; run: Run }>(`/subagents/${id(dep)}/run`),
  run: (dep: string) => get<{ ok: true; run: Run | null }>(`/subagents/${id(dep)}/run`),
  // contract (A03): cereal/routes/rules.py
  previewRules: (dep: string, change: RulesChange) => post<RulesPreview>(`/subagents/${id(dep)}/rules/preview`, change),
  updateRules: (dep: string, change: RulesChange) => post<RulesResult>(`/subagents/${id(dep)}/rules`, change),
  // contract (A04): cereal/routes/funding.py
  fund: (dep: string, body: FundRequest) => post<FundResult>(`/subagents/${id(dep)}/fund`, body),
  // contract (A05/A06): cereal/routes/workspace.py
  folders: () => get<Folder[]>('/folders'),
  createFolder: (name: string) => post<{ ok: true; folder: Folder }>('/folders', { name }),
  updateMeta: (dep: string, change: MetaChange) => post<{ ok: true; wallet: ApiRecord }>(`/subagents/${id(dep)}/meta`, change),
  // Sites (docs/SITES.md): routes/sessions.py, sites_probe.py, sites.py, site_access.py
  createSession: (name: string) => post<{ ok: true; user: SessionUser; token: string }>('/session', { name }),
  session: () => get<{ ok: true; user: SessionUser }>('/session'),
  probeSite: (url: string) => post<SiteProbe>('/sites/probe', { url }),
  sites: () => get<Site[]>('/sites'),
  addSite: (url: string) => post<{ ok: true; site: Site }>('/sites', { url }),
  removeSite: (site: string) => post<{ ok: true }>(`/sites/${id(site)}/remove`),
  openSite: (site: string) => post<SiteOpen>(`/sites/${id(site)}/open`),
  buySite: (site: string, body: { speculos_decision?: 'approve' | 'reject'; request_id?: string } = {}) =>
    post<{ ok: true; wallet: ApiRecord; run: Run }>(`/sites/${id(site)}/buy`, body),
  siteContent: (site: string) => get<SiteContent>(`/sites/${id(site)}/content`),
};
