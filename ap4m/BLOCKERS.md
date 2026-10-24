# Blockers for Live Testnet Execution (`ap4m/`)

All code, kit helpers (`ap4m-x402.mjs`, `verify-receipt.mjs`, `ap4m-hackathon-sdk.cjs`, `@ap4m/sdk`), merchant server (`ap4m/merchant.mjs`), agent CLI (`ap4m/pay.mjs`), and receipt verifier (`ap4m/verify.mjs`) are built and ready.

To run the live on-chain transaction and populate the remaining hashes in `ap4m/EVIDENCE.md`, we need Andrew to complete two human-only prerequisites (per the Rules in `docs/briefs/GEMINI-AP4M.md`):

1. **Fund XRPL EVM Testnet XRP for gas** from `https://faucet.testevm.ripple.com`:
   - Agent wallet `0xcb362681022f922b3b5090c3cdc3b57ba6b891b7` currently has `0 XRP` on XRPL EVM Testnet (`chainId: 1449000`) and needs gas to send the `PooledEscrowVault` channel-binding request transaction (`requestChannel`).
   - The Merchant submitter wallet (either `0xcb362681022f922b3b5090c3cdc3b57ba6b891b7` or `0x4a7e1cf40ea929ff5bec4d76b060506f3fe59c44`, whichever key is set as `MERCHANT_SUBMITTER_KEY`) also needs XRP gas to submit `redeemVoucher` on `PaymentLedger`.

2. **Add private key(s) to `/Users/andrewpaik/XRP HACKS/cereal-xrpl-ap4m/ap4m/.env`** (gitignored):
   ```dotenv
   AGENT_PRIVATE_KEY=0x...
   # Optional if using the same key as AGENT_PRIVATE_KEY to submit redemptions:
   MERCHANT_SUBMITTER_KEY=0x...
   ```

Once those two items are in place, tell me and I will immediately execute `merchant.mjs`, `pay.mjs`, and `verify.mjs` and commit the live transaction hashes into `ap4m/EVIDENCE.md`.
