/**
 * Close one AP4M Channel: the agent signs the service's final checkpoint (off-chain) and the AP4M service submits
 * closeChannel on-chain, returning the Channel's unused cap to the team budget. cereal calls this when it reclaims a
 * subagent, so a finished subagent never holds a Channel open (the service limits how many can be open at once).
 *
 * Usage: node ap4m/close.mjs <channelId>   → one JSON line {ok, channel_id, tx_hash} or {ok: false, error}
 */
import dotenv from 'dotenv';
import { ethers } from 'ethers';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import hackathonSdk from './ap4m-hackathon-sdk.cjs';

const HERE = dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: join(HERE, '.env'), quiet: true });
const { signIn, closeChannel } = hackathonSdk;

const channelId = process.argv[2] || '';
const out = (o, code = 0) => { console.log(JSON.stringify(o)); process.exit(code); };
if (!/^0x[0-9a-fA-F]{64}$/.test(channelId)) out({ ok: false, error: 'usage: node ap4m/close.mjs <0x channelId>' }, 2);
const key = process.env.AGENT_PRIVATE_KEY || '';
if (!key) out({ ok: false, channel_id: channelId, error: 'missing AGENT_PRIVATE_KEY in ap4m/.env' }, 1);

try {
  const apiUrl = (process.env.AP4M_API_URL || 'https://hackathon.ap4m.build').replace(/\/+$/, '');
  const rpcUrl = process.env.AP4M_RPC_URL || 'https://rpc.testnet.xrplevm.org';
  const wallet = new ethers.Wallet(key, new ethers.JsonRpcProvider(rpcUrl));
  const { token } = await signIn(apiUrl, process.env.TEAM_NAME || 'Cereal', wallet);
  const closed = await closeChannel(apiUrl, token, wallet, channelId);
  out({ ok: true, channel_id: channelId, tx_hash: closed?.tx_hash ?? null, status: closed?.status ?? null });
} catch (err) {
  out({ ok: false, channel_id: channelId, error: err?.message ?? String(err) }, 1);
}
