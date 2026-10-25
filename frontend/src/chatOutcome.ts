import { describeRefusal, type Refusal } from './api';

/** Explain only the backend's result; lack of a catalog match is not a permission denial. */
export function chatRefusal(body: Refusal): string {
  switch (body.refused) {
    case 'nothing_to_buy':
      return 'I couldn’t retrieve the requested data because none of Cereal’s connected vendors offers it. No payment was made. You can ask for a resource in the connected catalog, or connect a source that provides this data.';
    case 'payee_not_allowed':
      return 'I couldn’t retrieve the data because your wallet doesn’t allow payments to this vendor. No payment was made. You can review the allowed vendors in Cereal or use a different wallet.';
    case 'no_trusted_vendor': {
      const rejected = body.rejected && typeof body.rejected === 'object' ? Object.values(body.rejected).flat() : [];
      const reasons = rejected.map(r => r && typeof r === 'object' && 'reason' in r ? String(r.reason) : '');
      if (reasons.length && reasons.every(r => r === 'not_on_your_list'))
        return 'I couldn’t retrieve the data because the vendors offering it aren’t allowed by your wallet’s rules. No payment was made. You can review the allowed vendors in Cereal or use a different wallet.';
      return 'I couldn’t retrieve the data because no available vendor passed Cereal’s checks and this wallet’s rules. No payment was made. You can review the vendors in Cereal or try another source.';
    }
    case 'over_budget':
      if (body.remaining != null && Number(body.remaining) === 0)
        return 'This wallet is out of funds, so I couldn’t pay for this request. No payment was made. Add funds in Cereal or name another wallet. You can keep asking questions here.';
      return 'I couldn’t retrieve the data because its cost exceeds this wallet’s available budget. No payment was made. You can add funds in Cereal or choose a less expensive source.';
    case 'payment_pending':
      return 'An earlier payment for this data is still awaiting confirmation. I haven’t charged you again. You can keep chatting while Cereal checks its outcome.';
    case 'already_running':
      return 'This wallet already has a task running in Cereal, so I haven’t started another one. You can follow its progress in Cereal.';
    case 'already_bought':
      return 'This wallet already purchased the requested resources. I haven’t charged it again. You can view the previous result and activity in Cereal.';
    default:
      return `I couldn’t start this request. ${describeRefusal(body)} You can review the wallet in Cereal.`;
  }
}
