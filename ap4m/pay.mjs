/**
 * Cereal subagent CLI for the Mastercard AP4M rail (Part 4b).
 *
 * Contract called from cereal/subagent.py:
 *   node ap4m/pay.mjs --resource <url> --amount 0.25 --cap 1 --job <deployment_id> --tag <tag>
 *
 * Opens or reuses a Channel capped at --cap RLUSD (the subagent's budget), answers the
 * Merchant's HTTP 402 challenge with an EIP-712 Voucher via buyResource(), reports the
 * redemption, settles RLUSD to the Merchant payout wallet, and prints one JSON line:
 *   {"ok":true,"rail":"ap4m","channel_id":...,"amount":...,"cumulative":...,"redeem_tx":...,"receipt_id":...,"merchant_payout_delta":...,"explorer":...}
 *
 * Refusals (including over-cap requests) print:
 *   {"ok":false,"refused":"<reason>",...}
 * and exit with non-zero status before signing or sending any voucher.
 */

import dotenv from 'dotenv';
import { ethers } from 'ethers';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import hackathonSdk from './ap4m-hackathon-sdk.cjs';
import { buyResource, loadX402Context } from './ap4m-x402.mjs';

const { signIn, requestChannel, listChannels, getChannelState, settle, closeChannel } = hackathonSdk;

const HERE = dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: join(HERE, '.env'), quiet: true });

const ERC20_ABI = ['function balanceOf(address account) view returns (uint256)'];

function emitAndExit(payload, code = 0) {
  console.log(JSON.stringify(payload));
  process.exit(code);
}

function refuse(reason, extra = {}) {
  emitAndExit({ ok: false, rail: 'ap4m', refused: reason, ...extra }, 1);
}

function buildOperationName(job, tag, nonce) {
  const cleanJob = String(job || 'cereal')
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 20) || 'cereal';
  const cleanTag = String(tag || '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '')
    .slice(0, 16);
  const digest = createHash('sha256')
    .update(`${job || ''}|${tag || ''}|${nonce}`)
    .digest('hex')
    .slice(0, 12);
  const candidate = [cleanJob, cleanTag, digest].filter(Boolean).join('-').slice(0, 63).replace(/-+$/g, '');
  return /^[a-z0-9]/.test(candidate) ? candidate : `p-${candidate}`.slice(0, 63);
}

function loadStateIndex(stateDir) {
  const indexPath = join(stateDir, 'cereal-channels.json');
  try {
    return JSON.parse(readFileSync(indexPath, 'utf8'));
  } catch {
    return { channelsByJob: {}, purchaseSeq: 0 };
  }
}

function saveStateIndex(stateDir, index) {
  mkdirSync(stateDir, { recursive: true, mode: 0o700 });
  const indexPath = join(stateDir, 'cereal-channels.json');
  writeFileSync(indexPath, JSON.stringify(index, null, 2) + '\n', { mode: 0o600 });
}

async function main() {
  const { values } = parseArgs({
    options: {
      resource: { type: 'string' },
      amount: { type: 'string' },
      cap: { type: 'string' },
      job: { type: 'string' },
      tag: { type: 'string' },
      channel: { type: 'string' },
      operation: { type: 'string' },
      close: { type: 'boolean', default: false },
    },
    strict: false,
  });

  const resourceUrl = String(values.resource || process.env.RESOURCE_URL || 'http://127.0.0.1:4308/resource');
  const amountStr = String(values.amount || '0.25');
  const capStr = String(values.cap || process.env.CHANNEL_CAP || '1');
  const job = String(values.job || '');
  const tag = String(values.tag || '');

  let amountWei;
  let capWei;
  try {
    amountWei = ethers.parseUnits(amountStr, 18);
    capWei = ethers.parseUnits(capStr, 18);
  } catch (err) {
    return refuse('invalid_amount_or_cap', { amount: amountStr, cap: capStr, error: err?.message ?? String(err) });
  }

  if (amountWei <= 0n || capWei <= 0n) {
    return refuse('non_positive_amount_or_cap', { amount: amountStr, cap: capStr });
  }

  // Immediate local cap check before touching the network or private key
  if (amountWei > capWei) {
    return refuse('over_cap', {
      amount: amountStr,
      cap: capStr,
      job: job || null,
      tag: tag || null,
      message: `Requested payment ${amountStr} RLUSD exceeds channel cap ${capStr} RLUSD`,
    });
  }

  const agentKey = process.env.AGENT_PRIVATE_KEY || '';
  if (!agentKey || agentKey === 'YOUR_AGENT_PRIVATE_KEY_HERE') {
    return refuse('missing_agent_private_key', {
      hint: 'Set AGENT_PRIVATE_KEY in ap4m/.env (never commit it).',
    });
  }

  const apiUrl = (process.env.AP4M_API_URL || 'https://hackathon.ap4m.build').replace(/\/+$/, '');
  const teamName = process.env.TEAM_NAME || 'Cereal';
  const merchantId = process.env.MERCHANT_ID || undefined;

  const configResp = await fetch(`${apiUrl}/public/config`);
  const config = await configResp.json();
  if (!configResp.ok) {
    return refuse('service_config_unavailable', { error: config?.error ?? configResp.status });
  }

  const rpcUrl = process.env.AP4M_RPC_URL || config.network.rpcUrl;
  const explorerBase = (config.network.explorerUrl || 'https://explorer.testnet.xrplevm.org').replace(/\/+$/, '');
  const ledgerAddress = process.env.PAYMENT_LEDGER || config.contracts.paymentLedger;
  const rlusdAddress = config.contracts.rlusdToken;

  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const agentWallet = new ethers.Wallet(agentKey, provider);
  const rlusdToken = new ethers.Contract(rlusdAddress, ERC20_ABI, provider);

  const context = await loadX402Context(apiUrl);
  const { token } = await signIn(apiUrl, teamName, agentWallet);

  const baseStateDir = resolve(process.env.STATE_DIRECTORY || join(HERE, 'agent-state'));
  const stateIndex = loadStateIndex(baseStateDir);

  // Resolve or open a Channel capped at --cap RLUSD
  let channelId = String(values.channel || process.env.CHANNEL_ID || (job && stateIndex.channelsByJob?.[job]) || '');
  let channelPayout = process.env.MERCHANT_PAYOUT || '0x4a7e1cf40ea929ff5bec4d76b060506f3fe59c44';

  let freshChannel = false;
  const openChannels = await listChannels(apiUrl, token);
  const nowSec = Math.floor(Date.now() / 1000);

  if (channelId) {
    const found = openChannels.find((c) => c.channel_id.toLowerCase() === channelId.toLowerCase() && c.channel_status === 'open');
    if (!found) {
      channelId = '';
    } else {
      channelPayout = found.payout || channelPayout;
    }
  }

  if (!channelId && !job) {
    // Standalone runs only: reuse an open channel with exactly this cap. A cereal subagent (--job) always gets its
    // own Channel so two subagents' budgets never share one cap.
    for (const candidate of openChannels) {
      if (candidate.channel_status !== 'open') continue;
      if (BigInt(candidate.cap_wei) === capWei) {
        const st = await getChannelState(provider, ledgerAddress, candidate.channel_id);
        if (st.status === 1 && Number(st.validBefore) > nowSec + 30) {
          channelId = candidate.channel_id;
          channelPayout = candidate.payout || channelPayout;
          break;
        }
      }
    }
  }

  if (!channelId) {
    const gasBalance = await provider.getBalance(agentWallet.address);
    if (gasBalance === 0n) {
      return refuse('insufficient_gas', {
        agent_wallet: agentWallet.address,
        faucet: config.network.faucetUrl || 'https://faucet.testevm.ripple.com',
        message: 'Agent wallet holds 0 XRP on XRPL EVM Testnet and cannot send the vault transaction to open a Channel.',
      });
    }
    freshChannel = true;
    const created = await requestChannel(apiUrl, token, agentWallet, {
      capRlusd: capStr,
      merchantId,
      rpcUrl,
    });
    channelId = created.channel_id;
    channelPayout = created.payout || channelPayout;
  }

  if (job) {
    stateIndex.channelsByJob[job] = channelId;
    saveStateIndex(baseStateDir, stateIndex);
  }

  // An unfinished purchase for this job (voucher signed and presented, outcome never confirmed) is resumed with its
  // original arguments: the kit re-presents the SAME signed voucher, so this can never pay twice.
  const subagentStateDir = join(baseStateDir, job ? `job-${job.replace(/[^a-zA-Z0-9_-]/g, '_')}` : 'default');
  let resumeOperation = null;
  try {
    const retained = JSON.parse(readFileSync(join(subagentStateDir, 'purchase.json'), 'utf8'));
    if (retained && retained.complete === false) {
      const it = retained.intent || {};
      if (it.resourceUrl === resourceUrl && String(it.channelId).toLowerCase() === channelId.toLowerCase()
          && BigInt(it.maximumAmount) === amountWei) {
        resumeOperation = it.operation;
      } else {
        return refuse('unresolved_purchase', { channel_id: channelId, operation: it.operation, resource: it.resourceUrl,
          max_amount: ethers.formatUnits(BigInt(it.maximumAmount || 0), 18),
          message: 'resume the unfinished purchase with its original --resource and --amount first' });
      }
    }
  } catch { /* no retained purchase */ }

  // Check on-chain channel state & enforce cap before signing any voucher
  const stateBefore = await getChannelState(provider, ledgerAddress, channelId);
  const effectiveCapWei = stateBefore.cap < capWei ? stateBefore.cap : capWei;
  if (!resumeOperation && stateBefore.redeemed + amountWei > effectiveCapWei) {
    return refuse('over_cap', {
      channel_id: channelId,
      amount: amountStr,
      cap: ethers.formatUnits(effectiveCapWei, 18),
      redeemed: ethers.formatUnits(stateBefore.redeemed, 18),
      requested_cumulative: ethers.formatUnits(stateBefore.redeemed + amountWei, 18),
      job: job || null,
      tag: tag || null,
    });
  }

  const payoutBalanceBefore = await rlusdToken.balanceOf(channelPayout);

  stateIndex.purchaseSeq = Number(stateIndex.purchaseSeq || 0) + 1;
  saveStateIndex(baseStateDir, stateIndex);
  const operation = resumeOperation || (values.operation
    ? String(values.operation)
    : buildOperationName(job, tag, `${Date.now()}-${stateIndex.purchaseSeq}`));

  let purchase;
  const RETRYABLE = /retry the same operation|resume the same operation|managed open binding|chain_head_stale|HTTP 5\d\d|HTTP 409/i;
  let attempts = 0;
  for (;;) {
    attempts += 1;
    try {
      purchase = await buyResource({
        context,
        provider,
        wallet: agentWallet,
        stateDirectory: subagentStateDir,
        resourceUrl,
        channelId,
        maximumAmount: amountWei.toString(),
        operation,
      });
      break;
    } catch (err) {
      const msg = err?.message ?? String(err);
      // A Channel opened seconds ago is not yet in the finalized block the challenge is checked against.
      const notFinalYet = freshChannel && /exceeds the configured purchase authority|Merchant must return an x402/i.test(msg);
      if (attempts < 12 && (RETRYABLE.test(msg) || (notFinalYet && attempts < 8))) {
        await new Promise((r) => setTimeout(r, 6000));
        continue;
      }
      purchase = { error: err };
      break;
    }
  }
  if (purchase.error) {
    const err = purchase.error;
    const msg = err?.message ?? String(err);
    if (/exceeds the configured purchase authority/i.test(msg)) {
      return refuse('over_cap', {
        channel_id: channelId,
        amount: amountStr,
        cap: ethers.formatUnits(effectiveCapWei, 18),
        redeemed: ethers.formatUnits(stateBefore.redeemed, 18),
        job: job || null,
        tag: tag || null,
        error: msg,
      });
    }
    return refuse('x402_purchase_failed', {
      channel_id: channelId,
      operation,
      attempts,
      job: job || null,
      tag: tag || null,
      error: msg,
    });
  }

  const stateAfter = await getChannelState(provider, ledgerAddress, channelId);

  // Report redemption to AP4M service so settlement happens immediately
  const recordResp = await fetch(`${apiUrl}/public/participant/record-redemption`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ tx_hash: purchase.transactionHash }),
  });
  const warnings = [];
  if (!recordResp.ok) {
    const errBody = await recordResp.json().catch(() => ({}));
    warnings.push(`record_redemption_failed: ${errBody?.error ?? recordResp.status}`);
  }

  // The voucher is redeemed on-chain at this point: money has moved. Settlement only releases it to the payout
  // wallet, and the service also settles on its own, so a failure here is a warning, never a refusal.
  let settled = {};
  try { settled = await settle(apiUrl, token, channelId); }
  catch (err) { warnings.push(`settle_pending: ${err?.message ?? String(err)}`); }
  const payoutBalanceAfter = await rlusdToken.balanceOf(channelPayout);
  const payoutDeltaWei = payoutBalanceAfter - payoutBalanceBefore;

  const receiptUrl = settled.receipt_url
    ? (settled.receipt_url.startsWith('http') ? settled.receipt_url : `${apiUrl}${settled.receipt_url}`)
    : (settled.receipts?.find((r) => r.claim_id?.toLowerCase() === purchase.claimId?.toLowerCase())?.receipt_url ?? null);

  let closedTx = null;
  if (values.close) {
    const closed = await closeChannel(apiUrl, token, agentWallet, channelId);
    closedTx = closed.tx_hash;
  }

  emitAndExit({
    ok: true,
    rail: 'ap4m',
    channel_id: channelId,
    // what this voucher actually redeemed on-chain (the merchant may charge less than --amount, the maximum)
    amount: ethers.formatUnits(stateAfter.redeemed - stateBefore.redeemed, 18),
    max_amount: ethers.formatUnits(amountWei, 18),
    cumulative: ethers.formatUnits(stateAfter.redeemed, 18),
    merchant_payout: channelPayout,
    redeem_tx: purchase.transactionHash,
    claim_id: purchase.claimId,
    settlement_tx: settled.settlement_tx ?? null,
    payout_tx: settled.payout_tx ?? null,
    receipt_id: receiptUrl || purchase.claimId,
    // Measured on-chain balance change of the payout wallet (0 if the payout had not landed when we read it);
    // the service's own settled amount is reported separately, never substituted for the measurement.
    merchant_payout_delta: ethers.formatUnits(payoutDeltaWei, 18),
    settled_amount: settled.amount_rlusd ?? null,
    explorer: `${explorerBase}/tx/${purchase.transactionHash}`,
    job: job || null,
    tag: tag || null,
    operation,
    attempts,
    resumed: Boolean(resumeOperation),
    settled: Boolean(settled.settlement_tx || settled.payout_tx || settled.receipt_url),
    ...(warnings.length ? { warnings } : {}),
    resource: purchase.resource ?? null,
    ...(closedTx ? { close_tx: closedTx } : {}),
  }, 0);
}

main().catch((err) => {
  refuse('unexpected_error', { error: err?.message ?? String(err) });
});
