import type { LiveInfo } from './live';

export interface Constraints {
  spend: number;
  days: number;
  merchants: string[];
  approval: number;
  sweep: boolean;
}

export interface DemoTransaction {
  id: string;
  title: string;
  merchant: string;
  amount: number;
  durationSeconds: number;
  timestamp: string;
}

const sampleTransactions: DemoTransaction[] = [
  { id: 'demo-5', title: 'Medtech company profiles', merchant: 'HubSpot', amount: 1.40, durationSeconds: 34, timestamp: '2026-10-24T15:42:00-04:00' },
  { id: 'demo-4', title: 'Enrich decision-maker contacts', merchant: 'Clearbit', amount: 0.90, durationSeconds: 21, timestamp: '2026-10-24T15:40:00-04:00' },
  { id: 'demo-3', title: 'Find matching prospects', merchant: 'Apollo', amount: 0.75, durationSeconds: 18, timestamp: '2026-10-24T15:38:00-04:00' },
  { id: 'demo-2', title: 'Sync qualified leads to CRM', merchant: 'HubSpot', amount: 0.80, durationSeconds: 12, timestamp: '2026-10-24T15:35:00-04:00' },
  { id: 'demo-1', title: 'Verify company domains', merchant: 'Clearbit', amount: 0.55, durationSeconds: 9, timestamp: '2026-10-24T15:32:00-04:00' },
];

export interface Wallet {
  id: string;
  /** live mode only: the backend record and its exact amounts (see live.ts). Mock wallets never have it. */
  live?: LiveInfo;
  name: string;
  description?: string;
  mockDataVersion?: number;
  transactions?: DemoTransaction[];
  balance: number;
  archived: boolean;
  folderId?: string;
  constraints: Constraints;
}

export interface Folder { id: string; name: string }
export interface Workspace { wallets: Wallet[]; folders: Folder[] }
export const STORAGE_KEY = 'cereal-demo-v1';
export const defaultConstraints: Constraints = {
  spend: 20, days: 2, merchants: ['HubSpot', 'Clearbit', 'Apollo'], approval: 5, sweep: true,
};

const walletNames = [
  'Lead enrichment', 'Prospect discovery', 'CRM updates', 'Contact verification',
  'Market sizing', 'Competitor research', 'October outreach', 'Pilot research',
];
const folderNames: Record<string, string> = { 'research-1': 'Sales operations', 'research-2': 'Market research' };

const mockProfiles = [
  { match: /lead|enrich/i, description: 'Enrich medtech leads with verified company and contact data.', spend: 20, days: 2, approval: 5, balance: 1125.40,
    tasks: ['Medtech company profiles', 'Enrich decision-maker contacts', 'Find matching prospects', 'Sync qualified leads to CRM', 'Verify company domains'] },
  { match: /prospect|apollo/i, description: 'Find US healthcare prospects and qualify them for the sales team.', spend: 75, days: 3, approval: 15, balance: 248.65,
    tasks: ['Find healthcare buying teams', 'Expand target account list', 'Verify prospect company size', 'Discover operations leaders', 'Deduplicate prospect records', 'Export qualified prospects'] },
  { match: /crm|sync/i, description: 'Keep CRM accounts, contacts, and deal stages up to date.', spend: 50, days: 7, approval: 10, balance: 186.20,
    tasks: ['Sync account owners', 'Update deal stages', 'Merge duplicate contacts', 'Refresh company records', 'Import meeting notes', 'Reconcile account domains'] },
  { match: /contact|verif/i, description: 'Verify contact details before the next outbound campaign.', spend: 30, days: 2, approval: 5, balance: 94.80,
    tasks: ['Verify work email addresses', 'Check contact job titles', 'Match contacts to accounts', 'Flag outdated company records', 'Enrich missing phone numbers', 'Export verified contact list'] },
  { match: /market|sizing/i, description: 'Estimate the addressable market for a healthcare analytics product.', spend: 120, days: 5, approval: 25, balance: 520.35,
    tasks: ['Find healthcare analytics companies', 'Segment accounts by revenue', 'Count enterprise buying teams', 'Enrich regional company data', 'Compare customer segments', 'Compile market sizing inputs'] },
  { match: /competitor|pricing|research/i, description: 'Research competing vendors and build a comparable company dataset.', spend: 90, days: 4, approval: 20, balance: 312.50,
    tasks: ['Find competing vendors', 'Enrich competitor profiles', 'Map competitor customer segments', 'Identify category leaders', 'Compare company growth signals', 'Export competitor research'] },
  { match: /outreach|campaign/i, description: 'Prepare a qualified contact list for the October outreach campaign.', spend: 60, days: 3, approval: 10, balance: 42.75,
    tasks: ['Build outreach account list', 'Find campaign contacts', 'Verify campaign email addresses', 'Enrich personalization fields', 'Sync campaign members', 'Archive campaign results'] },
  { match: /pilot/i, description: 'Identify pilot customers and validate their fit for the product.', spend: 45, days: 4, approval: 10, balance: 68.20,
    tasks: ['Identify pilot customer accounts', 'Find product champions', 'Enrich pilot company profiles', 'Verify pilot contact details', 'Sync shortlisted accounts', 'Compile pilot research summary'] },
];

/** Deterministic local fixtures: repeat loads never generate new activity or money. */
export function populateMockWallet(wallet: Wallet, profileIndex?: number): Wallet {
  if (wallet.mockDataVersion === 1) return wallet;
  const matched = mockProfiles.findIndex(profile => profile.match.test(wallet.name));
  const hash = Array.from(wallet.id).reduce((sum, character) => sum + character.charCodeAt(0), 0);
  const index = profileIndex ?? (matched >= 0 ? matched : hash % mockProfiles.length);
  const profile = mockProfiles[index];
  const hasDefaultRules = JSON.stringify({ ...wallet.constraints, merchants: wallet.constraints.merchants.map(merchant => merchant.toLowerCase()) })
    === JSON.stringify({ ...defaultConstraints, merchants: defaultConstraints.merchants.map(merchant => merchant.toLowerCase()) });
  const constraints = hasDefaultRules ? { ...wallet.constraints, spend: profile.spend, days: profile.days, approval: profile.approval,
    merchants: [...defaultConstraints.merchants] } : wallet.constraints;
  const merchants = constraints.merchants.length ? constraints.merchants : defaultConstraints.merchants;
  const transactions = wallet.transactions?.length ? wallet.transactions : profile.tasks.map((title, i) => ({
    id: `${wallet.id}-mock-${i + 1}`, title, merchant: merchants[i % merchants.length],
    amount: Math.round(constraints.spend * [0.12, 0.09, 0.07, 0.055, 0.04, 0.025][i] * 100) / 100,
    durationSeconds: [34, 21, 18, 12, 9, 27][i] + index * 2,
    timestamp: new Date(Date.parse('2026-10-24T18:30:00-04:00') - index * 3600000 - i * 180000).toISOString(),
  }));
  return { ...wallet, mockDataVersion: 1, constraints, transactions,
    description: wallet.description?.trim() ? wallet.description : profile.description,
    balance: wallet.balance > 0 ? wallet.balance : profile.balance };
}

export function initialWorkspace(): Workspace {
  return {
    folders: Object.entries(folderNames).map(([id, name]) => ({ id, name })),
    wallets: Array.from({ length: 8 }, (_, i) => populateMockWallet({
      id: `wallet-${i + 1}`, name: walletNames[i], balance: i === 0 ? 1125.40 : 0,
      transactions: i === 0 ? sampleTransactions.map(transaction => ({ ...transaction })) : [],
      archived: i >= 6, folderId: i === 4 || i === 5 ? 'research-2' : undefined,
      constraints: { ...defaultConstraints, merchants: [...defaultConstraints.merchants] },
    }, i)),
  };
}

// Only public, simulated UI state is persisted. No addresses, seeds, or credentials.
export function loadWorkspace(): Workspace {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null');
    if (!value || typeof value !== 'object') return initialWorkspace();
    const state = value as Workspace;
    if (!Array.isArray(state.wallets) || !Array.isArray(state.folders)) return initialWorkspace();
    const valid = state.wallets.every(w => typeof w.id === 'string' && typeof w.name === 'string'
      && (w.description === undefined || typeof w.description === 'string')
      && typeof w.archived === 'boolean' && Number.isFinite(w.balance) && w.balance >= 0
      && w.constraints && Number.isFinite(w.constraints.spend) && w.constraints.spend > 0
      && Number.isFinite(w.constraints.days) && w.constraints.days > 0
      && Number.isFinite(w.constraints.approval) && w.constraints.approval >= 0
      && typeof w.constraints.sweep === 'boolean' && Array.isArray(w.constraints.merchants)
      && w.constraints.merchants.every(m => typeof m === 'string'));
    const foldersValid = state.folders.every(f => typeof f.id === 'string' && typeof f.name === 'string');
    return valid && foldersValid && new Set(state.wallets.map(w => w.id)).size === state.wallets.length
      ? {
        ...state,
        // Refresh only the original placeholder labels; retain user edits and all wallet data.
        folders: state.folders.map(folder => ({ ...folder,
          name: folder.name === 'Market Research' ? folderNames[folder.id] ?? folder.name : folder.name,
        })),
        wallets: state.wallets.map(wallet => {
          const index = walletNames.findIndex((_, i) => wallet.id === `wallet-${i + 1}`);
          const transactions = wallet.transactions === undefined
            ? (wallet.id === 'wallet-1' ? sampleTransactions.map(transaction => ({ ...transaction })) : [])
            : (Array.isArray(wallet.transactions) ? wallet.transactions.filter(transaction => transaction
              && typeof transaction.id === 'string' && typeof transaction.title === 'string'
              && typeof transaction.merchant === 'string' && Number.isFinite(transaction.amount) && transaction.amount >= 0
              && Number.isFinite(transaction.durationSeconds) && transaction.durationSeconds >= 0
              && typeof transaction.timestamp === 'string' && Number.isFinite(Date.parse(transaction.timestamp))) : []);
          return populateMockWallet({ ...wallet, transactions, name: wallet.name === 'Hubspot Product X Research' && index >= 0 ? walletNames[index] : wallet.name }, index >= 0 ? index : undefined);
        }),
      } : initialWorkspace();
  } catch { return initialWorkspace(); }
}

export function parseConstraints(text: string): Constraints | null {
  // Deliberately require a complete supported sentence: never silently apply a partial policy.
  const match = text.trim().match(/^spend up to \$(\d+(?:\.\d{1,2})?) over (\d+) days?, only at ([\w .,&-]+)\. ask me above \$(\d+(?:\.\d{1,2})?)\. (sweep back|keep funds) when done\.?$/i);
  if (!match) return null;
  const merchants = match[3].split(/,|\band\b|&/i).map(x => x.trim()).filter(Boolean);
  if (![+match[1], +match[2], +match[4]].every(Number.isFinite)
    || +match[1] <= 0 || +match[2] <= 0 || +match[2] > 365 || !merchants.length) return null;
  return { spend: +match[1], days: +match[2], merchants, approval: +match[4], sweep: match[5].toLowerCase() === 'sweep back' };
}
