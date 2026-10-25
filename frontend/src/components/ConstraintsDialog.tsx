import { useState } from 'react';
import type { AppActions } from '../appActions';
import { isLive } from '../mode';
import type { Constraints } from '../wallets';
import { Dialog } from './Dialog';

/** A03: edit a wallet's spending rules, from the blue rule buttons or a sentence typed in the wallet composer.
 * Mock: browser state. Live: preview, then apply on the backend (sentence = the composer's text, if any). */
export function ConstraintsDialog({ app, sentence }: { app: AppActions; sentence?: string }) {
  const selected = app.selected!;
  const [draftConstraints, setDraftConstraints] = useState<Constraints>(() => ({ ...selected.constraints }));
  if (isLive) return <Dialog title="Wallet constraints" onClose={app.close}>
    <p className="dialog-description">Spending rules for {selected.name}.{sentence ? ` Requested: “${sentence}”` : ''}</p>
    <p className="demo-note">Editing live rules is not connected yet. Nothing was changed.</p>
  </Dialog>;
  return <Dialog title="Wallet constraints" onClose={app.close}><form onSubmit={event => {
    event.preventDefault(); if (selected.archived) return;
    const data = new FormData(event.currentTarget);
    const merchants = String(data.get('merchants')).split(',').map(m => m.trim()).filter(Boolean);
    if (!merchants.length) return;
    app.updateWallet(selected.id, { constraints: { ...draftConstraints, merchants } }); app.close(); app.notify('Demo wallet constraints updated.');
  }}><p className="dialog-description">Set spending rules for {selected.name}. Rules are saved for this demo; no payments are executed.</p>
    <div className="form-grid"><label>Spend limit ($)<input type="number" min="0.01" step="0.01" required value={draftConstraints.spend} onChange={e => setDraftConstraints({ ...draftConstraints, spend: +e.target.value })} autoFocus /></label>
    <label>Duration (days)<input type="number" min="1" max="365" step="1" required value={draftConstraints.days} onChange={e => setDraftConstraints({ ...draftConstraints, days: +e.target.value })} /></label></div>
    <label>Allowed merchants<input name="merchants" required defaultValue={draftConstraints.merchants.join(', ')} /></label>
    <label>Ask for approval above ($)<input type="number" min="0" step="0.01" required value={draftConstraints.approval} onChange={e => setDraftConstraints({ ...draftConstraints, approval: +e.target.value })} /></label>
    <label className="checkbox-label"><input type="checkbox" checked={draftConstraints.sweep} onChange={e => setDraftConstraints({ ...draftConstraints, sweep: e.target.checked })} />Sweep back when done</label>
    <button className="primary-button form-submit" disabled={selected.archived}>Save constraints</button>
  </form></Dialog>;
}
