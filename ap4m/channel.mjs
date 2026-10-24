/**
 * Read one AP4M Channel's on-chain state from PaymentLedger (no key needed). cereal uses this as the source of truth
 * for what a subagent spent on the AP4M rail, so a crash after a redemption can never hide a payment.
 *
 * Usage: node ap4m/channel.mjs <channelId>   → one JSON line {ok, channel_id, redeemed, cap, status, valid_before,
 *                                                redemptions: [{tx, amount, cumulative, block}]} (recent ~20k blocks)
 */
import { ethers } from 'ethers';
import hackathonSdk from './ap4m-hackathon-sdk.cjs';

const LEDGER = process.env.PAYMENT_LEDGER || '0xcAB42800A5ECF0D253Fa2581Bb3334B4DAEfaE91';
const RPC = process.env.AP4M_RPC_URL || 'https://rpc.testnet.xrplevm.org';
const id = process.argv[2] || '';
if (!/^0x[0-9a-fA-F]{64}$/.test(id)) {
  console.log(JSON.stringify({ ok: false, error: 'usage: node ap4m/channel.mjs <0x channelId>' }));
  process.exit(2);
}
try {
  const provider = new ethers.JsonRpcProvider(RPC);
  const st = await hackathonSdk.getChannelState(provider, LEDGER, id);
  const iface = new ethers.Interface(['event VoucherRedeemed(bytes32 indexed channelId,bytes32 indexed claimId,bytes32 indexed voucherDigest,bytes32 allocationId,address agent,bytes32 merchantId,address payout,address submitter,uint256 previousCumulativeAmount,uint256 cumulativeAmount,uint256 amount)']);
  const topic = iface.getEvent('VoucherRedeemed').topicHash;
  const head = await provider.getBlockNumber();
  const redemptions = [];
  for (let to = head; to > head - 20000 && to > 0; to -= 5000) {
    const logs = await provider.getLogs({ address: LEDGER, topics: [topic, id], fromBlock: Math.max(0, to - 4999), toBlock: to });
    for (const l of logs) {
      const e = iface.parseLog(l);
      redemptions.push({ tx: l.transactionHash, block: l.blockNumber, amount: ethers.formatUnits(e.args.amount, 18),
        cumulative: ethers.formatUnits(e.args.cumulativeAmount, 18), payout: e.args.payout });
    }
  }
  redemptions.sort((a, b) => a.block - b.block);
  console.log(JSON.stringify({ ok: true, channel_id: id, redeemed: ethers.formatUnits(st.redeemed, 18),
    cap: ethers.formatUnits(st.cap, 18), status: st.status, valid_before: Number(st.validBefore), redemptions }));
} catch (err) {
  console.log(JSON.stringify({ ok: false, channel_id: id, error: err?.message ?? String(err) }));
  process.exit(1);
}
