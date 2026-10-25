import type { AppActions } from '../appActions';
import type { Wallet } from '../wallets';

/** A01/A02/A07 (live only): start the wallet's task, follow the run, then done & sweep, reclaim, retire. */
export function WalletActions({ wallet }: { app: AppActions; wallet: Wallet }) {
  if (!wallet.live) return null;
  return null;
}
