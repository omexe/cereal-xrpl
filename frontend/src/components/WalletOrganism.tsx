import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import type { Wallet } from '../wallets';
import { CORE, CORE_ID, DURATION, SIZE, createWalletSpheres, type View } from '../lib/walletSpheres';

interface Props {
  wallets: Wallet[];
  totalBalance: number;
  selectedId?: string;
  onSelect: (id: string) => void;
  /** Makes the aggregate core a control: it highlights, then this runs. */
  onHome?: () => void;
  /** Crops to this region so the spheres fill a fixed frame (`.organism-frame`). */
  framed?: View;
}

const press = (action: () => void) => (event: KeyboardEvent) => {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); action(); }
};
// The canvas is sized so the view fills the frame; the frame clips everything outside it.
export const crop = (view: View): CSSProperties => ({
  width: `${SIZE / view.width * 100}%`, left: `${-view.x / view.width * 100}%`, top: `${-view.y / view.height * 100}%`,
});

/** Canvas draws the detached dotted spheres; SVG provides accessible controls. */
export function WalletOrganism({ wallets, totalBalance, selectedId, onSelect, onHome, framed }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const renderer = useRef<ReturnType<typeof createWalletSpheres> | null>(null);
  const timer = useRef(0);
  // A clicked sphere takes the highlight first, so the move reads as one motion before the page changes.
  const [pending, setPending] = useState<string>();
  const activeWallets = wallets.filter(wallet => !wallet.archived);
  const idsKey = JSON.stringify(activeWallets.map(wallet => wallet.id));
  const count = activeWallets.length;
  const totalLabel = `Total wallet: $${totalBalance.toFixed(2)} across ${count} active wallets`;
  const highlighted = pending ?? selectedId;

  useEffect(() => {
    renderer.current = createWalletSpheres(canvas.current!, svg.current!);
    return () => { renderer.current?.destroy(); renderer.current = null; clearTimeout(timer.current); };
  }, []);
  useEffect(() => { renderer.current?.update(JSON.parse(idsKey), highlighted); }, [idsKey, highlighted]);
  useEffect(() => setPending(undefined), [selectedId]);

  function go(id: string, action: () => void) {
    if (id === highlighted) return;
    clearTimeout(timer.current);
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { action(); return; }
    setPending(id);
    timer.current = window.setTimeout(action, DURATION);
  }

  return <div className="organism" data-wallet-count={count} style={framed && crop(framed)}>
    <canvas ref={canvas} aria-hidden="true" />
    <svg ref={svg} viewBox={`0 0 ${SIZE} ${SIZE}`} role="group" aria-label={`Total wallet with ${count} orbiting active wallets`}>
      <title>{totalLabel}</title>
      {onHome
        ? <g className="total-wallet-core" role="button" tabIndex={0} aria-label={`Home. ${totalLabel}`} aria-pressed={highlighted === CORE_ID}
          onClick={() => go(CORE_ID, onHome)} onKeyDown={press(() => go(CORE_ID, onHome))}>
          <title>Home · {totalLabel}</title>
          <circle className="cluster-target" cx={CORE.x} cy={CORE.y} r={CORE.radius} />
        </g>
        : <g className="total-wallet-core" role="img" aria-label={totalLabel}>
          <title>{totalLabel}</title>
          <circle cx={CORE.x} cy={CORE.y} r={CORE.radius} fill="transparent" />
        </g>}
      {activeWallets.map((wallet, index) => <g key={wallet.id} data-wallet-id={wallet.id} className="wallet-cluster"
        role="button" tabIndex={0} aria-label={`${wallet.name}, wallet ${index + 1}`}
        aria-pressed={wallet.id === highlighted} onClick={() => go(wallet.id, () => onSelect(wallet.id))}
        onKeyDown={press(() => go(wallet.id, () => onSelect(wallet.id)))}>
        <title>{wallet.name} · ${wallet.balance.toFixed(2)}</title>
        <circle className="cluster-target" cx={CORE.x} cy={CORE.y} r="0" />
      </g>)}
    </svg>
    {!count && <p className="organism-caption">No active wallets.</p>}
  </div>;
}
