import { useState } from 'react';
import type { DemoPayment } from '../researchDemo';
import { decidePayment, money } from '../researchDemo';
import { mutateWorkspace } from '../workspaceStore';

export function paymentLabel(payment: DemoPayment) {
  return payment.status === 'paid' ? payment.approvedBy ? 'Approved by you' : 'Allowed automatically'
    : payment.status === 'pending' ? 'Approval required' : payment.status === 'blocked' ? 'Blocked'
    : payment.status === 'denied' ? 'Denied by you' : 'Cancelled';
}

/** Requests use the same activity cards as completed transactions on every wallet. */
export function PaymentRequest({ payment }: { payment: DemoPayment }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function decide(approve: boolean) {
    setBusy(true); setError('');
    try { await mutateWorkspace(state => decidePayment(state, payment.id, approve)); }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not save your decision. Please retry.'); }
    finally { setBusy(false); }
  }
  return <article className="transaction-card payment-request" data-payment-id={payment.id}>
    <div className="transaction-main"><h3>{payment.title}</h3><span className="transaction-merchant">{payment.merchant}</span><span className="transaction-amount">{money(payment.amount)}</span></div>
    <div className="transaction-meta"><span className={`payment-badge ${payment.status}`}>{paymentLabel(payment)}</span><span>Not charged</span></div>
    <p className="payment-reason">{payment.reason}</p>
    {payment.status === 'pending' && <div className="approval-actions"><button className="primary-button" disabled={busy} onClick={() => void decide(true)}>{busy ? 'Saving…' : `Approve ${money(payment.amount)}`}</button><button className="research-outline" disabled={busy} onClick={() => void decide(false)}>Deny payment</button></div>}
    {error && <p className="research-error" role="alert">{error}</p>}
  </article>;
}
