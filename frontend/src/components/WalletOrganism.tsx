import { useEffect, useRef } from 'react';
import type { Wallet } from '../wallets';
import { CORE, createWalletSpheres } from '../lib/walletSpheres';

interface Props {
  wallets: Wallet[];
  totalBalance: number;
  selectedId?: string;
  onSelect: (id: string) => void;
}

/** Canvas draws the detached dotted spheres; SVG provides accessible controls. */
export function WalletOrganism({ wallets, totalBalance, selectedId, onSelect }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const renderer = useRef<ReturnType<typeof createWalletSpheres> | null>(null);
  const activeWallets = wallets.filter(wallet => !wallet.archived);
  const idsKey = JSON.stringify(activeWallets.map(wallet => wallet.id));
  const count = activeWallets.length;
  const totalLabel = `Total wallet: $${totalBalance.toFixed(2)} across ${count} active wallets`;

  useEffect(() => {
    renderer.current = createWalletSpheres(canvas.current!, svg.current!);
    return () => { renderer.current?.destroy(); renderer.current = null; };
  }, []);
  useEffect(() => { renderer.current?.update(JSON.parse(idsKey), selectedId); }, [idsKey, selectedId]);

  return <div className="organism" data-wallet-count={count}>
    <canvas ref={canvas} aria-hidden="true" />
    <svg ref={svg} viewBox="0 0 727 727" role="group" aria-label={`Total wallet with ${count} orbiting active wallets`}>
      <title>{totalLabel}</title>
      <g className="total-wallet-core" role="img" aria-label={totalLabel}>
        <title>{totalLabel}</title>
        <circle cx={CORE.x} cy={CORE.y} r={CORE.radius} fill="transparent" />
      </g>
      {activeWallets.map((wallet, index) => <g key={wallet.id} data-wallet-id={wallet.id} className="wallet-cluster"
        role="button" tabIndex={0} aria-label={`${wallet.name}, wallet ${index + 1}`}
        aria-pressed={wallet.id === selectedId} onClick={() => onSelect(wallet.id)}
        onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(wallet.id); } }}>
        <title>{wallet.name} · ${wallet.balance.toFixed(2)}</title>
        <circle className="cluster-target" cx={CORE.x} cy={CORE.y} r="0" />
      </g>)}
    </svg>
    {!count && <p className="organism-caption">No active wallets.</p>}
  </div>;
}
