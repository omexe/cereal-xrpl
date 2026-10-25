import type { SetStateAction } from 'react';
import type { Session } from './session';
import type { LiveData } from './store';
import type { Wallet, Workspace } from './wallets';

/** What App hands each dialog and slot. Mock-mode writes go through setWorkspace/updateWallet; live-mode writes go
 * through `api` and then `live.refresh()` / `live.upsert()`. */
export interface AppActions {
  workspace: Workspace;
  /** Wallets that are not archived (live: whatever their lifecycle state). */
  activeWallets: Wallet[];
  selected?: Wallet;
  selectedId?: string;
  setSelectedId: (id: string | undefined) => void;
  isHome: boolean;
  live: LiveData;
  /** mock mode only */
  setWorkspace: (update: SetStateAction<Workspace>) => Promise<Workspace | undefined>;
  /** mock mode only: merge fields into one wallet */
  updateWallet: (id: string, update: Partial<Wallet>) => Promise<Workspace | undefined>;
  /** Open a wallet's view (after creating it). */
  showWallet: (id: string, folderId?: string) => void;
  moveWallet: (id: string, folderId?: string) => void;
  toggleArchive: () => void;
  /** Status line under the content; error=true keeps it visible and styles it as an alert. */
  notify: (message: string, error?: boolean) => void;
  close: () => void;
  /** Sites (docs/SITES.md): the signed-in user, if any, and the site views. */
  session: Session | null;
  setSession: (session: Session | null) => void;
  selectedSiteId?: string;
  openSite: (siteId: string) => void;
  openAddSite: (url?: string) => void;
}
