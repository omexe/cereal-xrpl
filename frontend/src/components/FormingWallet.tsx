import { useEffect, useMemo, useRef } from 'react';
import { formatAmount } from '../format';
import { draftConstraints, draftMissing, draftSentence, parseDraft } from '../lib/draftWallet';
import { createFormingSphere } from '../lib/formingSphere';
import { CORE_ID, HOME_VIEW, placeSphere, type Position } from '../lib/walletSpheres';
import type { Wallet } from '../wallets';
import { WalletOrganism, crop } from './WalletOrganism';

interface Props {
  text: string;
  wallets: Wallet[];
  totalBalance: number;
  /** What the wallet is and where its money comes from, under the amount. */
  caption: string;
  canCreate: boolean;
  onCreate: () => void;
  onCancel: () => void;
  onSelect: (id: string) => void;
}

/** Home while the user writes a new wallet: the workspace turns blue, the new wallet's sphere forms where it will sit,
 * and the rules it will get read back in large type as they are typed. */
export function FormingWallet({ text, wallets, totalBalance, caption, canCreate, onCreate, onCancel, onSelect }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const sphere = useRef<ReturnType<typeof createFormingSphere> | null>(null);
  const draft = useMemo(() => parseDraft(text), [text]);
  const sentence = draftSentence(draft);
  const missing = draftMissing(draft);
  const ready = !!draftConstraints(draft);
  const active = wallets.filter(wallet => !wallet.archived);

  useEffect(() => {
    sphere.current = createFormingSphere(canvas.current!);
    return () => { sphere.current?.destroy(); sphere.current = null; };
  }, []);
  useEffect(() => {
    // The same placement the sphere map uses, so the new wallet appears exactly where it formed.
    const placed = Array.from({ length: active.length }).reduce<Position[]>(list => [...list, placeSphere(list)], []);
    sphere.current?.update(placeSphere(placed), draft.progress);
  }, [active.length, draft.progress]);

  return <section className="forming" aria-label="New wallet preview">
    <div className="home-illustration organism-frame">
      <WalletOrganism wallets={active} totalBalance={totalBalance} selectedId={CORE_ID} onSelect={onSelect} framed={HOME_VIEW} />
      <div className="organism forming-layer" style={crop(HOME_VIEW)}><canvas ref={canvas} aria-hidden="true" /></div>
    </div>
    <div className="forming-card">
      <div className="forming-actions">
        <button type="button" className="forming-cancel" onClick={onCancel}>Cancel</button>
        <button type="button" className="forming-create" disabled={!canCreate || !ready} onClick={onCreate}>Create wallet</button>
      </div>
      <h1 className="forming-amount">{formatAmount(draft.spend ?? 0)}</h1>
      <p className="forming-caption">{draft.name ? `${draft.name} · ` : ''}{caption}</p>
      <p className={`forming-rules ${sentence ? '' : 'is-hint'}`} aria-live="polite">
        {sentence ?? 'Name it and give it a budget, a time limit and vendors.'}<span className="forming-caret" aria-hidden="true" />
      </p>
      {sentence && missing.length > 0 && <p className="forming-missing">Still needed: {missing.length < 2 ? missing[0] : `${missing.slice(0, -1).join(', ')} and ${missing.at(-1)}`}</p>}
    </div>
  </section>;
}
