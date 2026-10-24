/**
 * Cereal wrapper around verify-receipt.mjs to verify an ap4m.claim-receipt.v1
 * receipt independently against the public XRPL EVM Testnet RPC.
 *
 * Usage:
 *   node ap4m/verify.mjs <receipt_url>
 *   node ap4m/verify.mjs <claim_id> <settlement_digest>
 *   node ap4m/verify.mjs <claim_id>
 */

import dotenv from 'dotenv';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: join(HERE, '.env'), quiet: true });

async function resolveArgs() {
  const apiUrl = (process.env.AP4M_API_URL || 'https://hackathon.ap4m.build').replace(/\/+$/, '');
  const args = process.argv.slice(2).filter((a) => !a.startsWith('--'));
  const [first, second] = args;

  if (!first) {
    console.error('Usage: node ap4m/verify.mjs <receipt_url | claim_id [settlement_digest]>');
    process.exit(2);
  }

  // Full receipt URL
  if (/^https?:\/\/.+\/public\/evidence\/claims\/0x[0-9a-f]{64}\/0x[0-9a-f]{64}\.json$/i.test(first)) {
    return { apiUrl, verifyArgs: [first] };
  }

  // Path returned by settle(), e.g. /public/evidence/claims/0x.../0x....json
  if (/^\/public\/evidence\/claims\/0x[0-9a-f]{64}\/0x[0-9a-f]{64}\.json$/i.test(first)) {
    return { apiUrl, verifyArgs: [`${apiUrl}${first}`] };
  }

  // claimId + settlementDigest
  if (first && second) {
    return { apiUrl, verifyArgs: [first, second] };
  }

  // Only claimId provided: discover its receipt URL from GET /public/evidence/claims/<claimId>
  if (/^0x[0-9a-f]{64}$/i.test(first)) {
    const resp = await fetch(`${apiUrl}/public/evidence/claims/${first.toLowerCase()}`);
    if (resp.ok) {
      const data = await resp.json();
      const url = data?.receipts?.[0]?.receipt_url || data?.receipt_url || (Array.isArray(data) ? data[0] : null);
      if (typeof url === 'string') {
        const fullUrl = url.startsWith('http') ? url : `${apiUrl}${url}`;
        return { apiUrl, verifyArgs: [fullUrl] };
      }
    }
  }

  return { apiUrl, verifyArgs: [first] };
}

const { apiUrl, verifyArgs } = await resolveArgs();
const rpcUrl = process.env.RPC_URL || process.env.AP4M_RPC_URL || 'https://rpc.testnet.xrplevm.org';

try {
  const out = execFileSync(process.execPath, [join(HERE, 'verify-receipt.mjs'), ...verifyArgs], {
    env: { ...process.env, AP4M_API_URL: apiUrl, RPC_URL: rpcUrl },
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  process.stdout.write(out);
} catch (err) {
  console.error(JSON.stringify({
    verified: false,
    error: (err?.stderr || err?.message || String(err)).trim(),
  }));
  process.exit(err?.status || 1);
}
