/**
 * AP4M Hackathon — verify a payment receipt
 * FOR HACKATHON USE ONLY
 *
 * Downloads an ap4m.claim-receipt.v1 receipt from the AP4M service and checks it against the
 * chain: the vault payout and its token transfer, the payout
 * wallet balances, the redeemed Voucher, and the settlement digest recorded on the ledger.
 *
 * Prerequisites (Node.js 22.13 or later):
 *   npm install ethers@6.17.0 <AP4M_API_URL>/sdk/ap4m-sdk.tgz
 *
 * Usage:
 *   AP4M_API_URL=https://... node verify-receipt.mjs <claimId> <settlementDigest>
 *   node verify-receipt.mjs <receipt URL>
 * Optional: RPC_URL, an RPC node you choose for an independent check (default: the RPC URL the
 * service publishes in /public/config).
 *
 * The service publishes the contract addresses the receipt is checked against. Compare the
 * printed ledger, vault and token addresses with the published event deployment.
 */

import { ethers } from 'ethers';
import { fetchClaimReceipt, parseClaimReceiptContext, verifyClaimReceipt } from '@ap4m/sdk';

function target() {
  const [first, second] = process.argv.slice(2);
  const receiptUrl = first?.match(/^(https?:\/\/.+)\/public\/evidence\/claims\/(0x[0-9a-f]{64})\/(0x[0-9a-f]{64})\.json$/);
  if (receiptUrl) return { apiUrl: receiptUrl[1], claimId: receiptUrl[2], settlementDigest: receiptUrl[3] };
  if (process.env.AP4M_API_URL && first && second) {
    return { apiUrl: process.env.AP4M_API_URL.replace(/\/+$/, ''), claimId: first.toLowerCase(), settlementDigest: second.toLowerCase() };
  }
  console.error('Usage: node verify-receipt.mjs <receipt URL>\n   or: AP4M_API_URL=... node verify-receipt.mjs <claimId> <settlementDigest>');
  process.exit(2);
}

const { apiUrl, claimId, settlementDigest } = target();

async function publishedRpcUrl() {
  const config = await fetch(`${apiUrl}/public/config`).then((response) => (response.ok ? response.json() : null), () => null);
  const rpcUrl = config?.network?.rpcUrl;
  if (!rpcUrl) throw new Error('The service publishes no RPC URL; set RPC_URL.');
  return rpcUrl;
}
const local = /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(apiUrl);

const response = await fetch(`${apiUrl}/public/evidence/context`);
if (!response.ok) throw new Error(`Receipt context unavailable (${response.status})`);
const published = await response.json();
if (published.schemaId !== 'ap4m.hackathon-service.evidence-context.v1') throw new Error('unsupported receipt context');
const context = parseClaimReceiptContext(published.receipt);

const RPC_URL = process.env.RPC_URL || await publishedRpcUrl();
const provider = new ethers.JsonRpcProvider(RPC_URL);
const network = await provider.getNetwork();
if (network.chainId.toString() !== context.chainId) throw new Error(`RPC_URL is chain ${network.chainId}, the receipt is for chain ${context.chainId}`);

const receipt = await fetchClaimReceipt({ evidenceBaseUrl: `${apiUrl}/public/evidence`, allowHttp: local }, claimId, settlementDigest);
if (!receipt) throw new Error('No receipt is published for this Claim and settlement digest yet.');

await verifyClaimReceipt(provider, context, receipt);
console.log(JSON.stringify({
  verified: true,
  claimId,
  settlementDigest,
  amount: ethers.formatUnits(receipt.vaultPayoutEvidence.amount, 18),
  payout: receipt.vaultPayoutEvidence.payout,
  payoutTransaction: receipt.vaultPayoutEvidence.transactionHash,
  settlementTransaction: receipt.settlementTransaction.transactionHash,
  checkedAgainst: { chainId: context.chainId, ledger: context.ledger, vault: context.vault, token: context.token, rpcUrl: RPC_URL },
}, null, 2));
