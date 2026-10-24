/**
 * Cereal x402 Merchant on Mastercard AP4M (XRPL EVM Testnet, chain 1449000).
 *
 * Serves the Swell agenda JSON resource behind HTTP 402 at GET /resource using
 * the kit's createX402Merchant() helper, redeeming each EIP-712 Voucher on-chain
 * on PaymentLedger and settling RLUSD to the team's merchant payout wallet.
 *
 * Usage:
 *   node ap4m/merchant.mjs [--port 4308] [--price 0.25] [--state-dir ./ap4m/merchant-state]
 */

import dotenv from 'dotenv';
import { ethers } from 'ethers';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { createX402Merchant, loadX402Context } from './ap4m-x402.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: join(HERE, '.env'), quiet: true });

const DEFAULT_MERCHANT_ID = '0xc01be948b7eae6994cbef40dea79f5a2ef8af335e53772bb943226a1bca04cb5';
const DEFAULT_MERCHANT_PAYOUT = '0x4a7e1cf40ea929ff5bec4d76b060506f3fe59c44';

export const SWELL_AGENDA_RESOURCE = {
  dataset: 'swell-nyc-hackathon-sample-agenda',
  note: 'Sample data for the demo, not an official agenda; no real speakers are listed.',
  vendor: 'Cereal Data Vendor (AP4M)',
  rail: 'ap4m',
  network: 'eip155:1449000',
  sessions: [
    { id: 'sample-01', title: 'Agent wallets with budget-exact limits', startsAt: '2026-10-25T13:00:00Z' },
    { id: 'sample-02', title: 'Vendor credentials and vouchers for agents', startsAt: '2026-10-25T14:30:00Z' },
  ],
};

async function main() {
  const { values } = parseArgs({
    options: {
      port: { type: 'string' },
      price: { type: 'string' },
      'resource-url': { type: 'string' },
      'state-dir': { type: 'string' },
    },
    strict: false,
  });

  const apiUrl = (process.env.AP4M_API_URL || 'https://hackathon.ap4m.build').replace(/\/+$/, '');
  const merchantId = process.env.MERCHANT_ID || DEFAULT_MERCHANT_ID;
  const merchantPayout = process.env.MERCHANT_PAYOUT || DEFAULT_MERCHANT_PAYOUT;
  const submitterKey = process.env.MERCHANT_SUBMITTER_KEY || process.env.AGENT_PRIVATE_KEY || '';
  const priceRlusd = String(values.price || process.env.PRICE_RLUSD || '0.25');
  const port = Number(values.port || process.env.PORT || 4308);
  const resourceUrl = String(values['resource-url'] || process.env.RESOURCE_URL || `http://127.0.0.1:${port}/resource`);
  // Incorporate price into default state directory name so changing --price does not collide with an earlier SQLite identity
  const defaultStateDir = join(HERE, `merchant-state-${priceRlusd.replace(/[^a-zA-Z0-9_-]/g, '_')}`);
  const stateDirectory = resolve(String(values['state-dir'] || process.env.MERCHANT_STATE_DIRECTORY || defaultStateDir));

  if (!submitterKey) {
    console.error(JSON.stringify({
      ok: false,
      refused: 'missing_submitter_key',
      hint: 'Set MERCHANT_SUBMITTER_KEY (or AGENT_PRIVATE_KEY) in ap4m/.env with a funded XRPL EVM Testnet key for redemption gas.',
    }));
    process.exit(1);
  }

  const context = await loadX402Context(apiUrl);
  const configResp = await fetch(`${apiUrl}/public/config`);
  const config = await configResp.json();
  const rpcUrl = process.env.AP4M_RPC_URL || config?.network?.rpcUrl || 'https://rpc.testnet.xrplevm.org';
  const provider = new ethers.JsonRpcProvider(rpcUrl);
  const submitter = new ethers.Wallet(submitterKey, provider);

  const merchant = createX402Merchant({
    context,
    provider,
    submitter,
    stateDirectory,
    resourceUrl,
    merchantParticipantId: merchantId,
    payout: merchantPayout,
    amount: ethers.parseUnits(priceRlusd, 18).toString(),
    content: SWELL_AGENDA_RESOURCE,
  });

  merchant.server.listen(port, '127.0.0.1', () => {
    console.log(JSON.stringify({
      ok: true,
      event: 'merchant_listening',
      resource_url: resourceUrl,
      price_rlusd: priceRlusd,
      merchant_id: merchantId,
      payout: merchantPayout,
      submitter: submitter.address,
      chain_id: config?.network?.chainId ?? 1449000,
    }));
  });

  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.once(signal, () => {
      merchant.close().finally(() => process.exit(0));
    });
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error(JSON.stringify({ ok: false, error: err?.message ?? String(err) }));
    process.exit(1);
  });
}
