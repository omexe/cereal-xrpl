# ap4m/ — Mastercard AP4M x402 Rail on XRPL EVM Testnet (Part 4b)

A cereal subagent pays a merchant over Mastercard's **Agent Pay for Machines (AP4M)** kit on the **XRPL EVM Testnet** (`eip155:1449000`, RPC `https://rpc.testnet.xrplevm.org`), with **no human in the loop**: it hits an HTTP `402 Payment Required`, signs an EIP-712 `Voucher` inside a payment Channel capped at the subagent's budget (`--cap`), the Merchant redeems the voucher on `PaymentLedger`, the AP4M service settles RLUSD from `PooledEscrowVault` to the Merchant payout wallet, and `verify.mjs` independently verifies the `ap4m.claim-receipt.v1` receipt against the chain.

---

## Deployment & Team State (Oct 24, 2026)

| Property | Value |
|---|---|
| **Network** | XRPL EVM Testnet (`eip155:1449000`, chain ID `1449000`) |
| **RPC URL** | `https://rpc.testnet.xrplevm.org` |
| **Explorer** | `https://explorer.testnet.xrplevm.org` |
| **AP4M Service** | `https://hackathon.ap4m.build` |
| **ParticipantRegistry** | `0x4cF27435FE56161aa9b1cffdD87784aa68b7D1E8` |
| **PaymentLedger** | `0xcAB42800A5ECF0D253Fa2581Bb3334B4DAEfaE91` |
| **PooledEscrowVault** | `0x83DD9cD010eb46e96eceF8F7eB0a18f7845AaBC0` |
| **RLUSD Token (18 dec)** | `0x27b57a9D0b8d24EB97259c4E2279e45255e016f3` |
| **Team** | `Cereal` |
| **Agent Wallet** | `0xcb362681022f922b3b5090c3cdc3b57ba6b891b7` (Participant ID `0xb7ff548a3e06db04643dfbd69bc0c062e898a73b9803dfe57a8ebca1e72b81ac`) |
| **Funding Account** | `0x5c63e03942db4da90985f682404a346b58d3fce99472433f4bfa6e61395e28d6` (20.0 RLUSD deposited & active in `PooledEscrowVault`) |
| **Merchant Payout Wallet** | `0x4a7e1cf40ea929ff5bec4d76b060506f3fe59c44` (Merchant ID `0xc01be948b7eae6994cbef40dea79f5a2ef8af335e53772bb943226a1bca04cb5`) |

---

## Setup & How to Run

### 1. Install dependencies
```bash
cd ap4m
npm install
cp .env.example .env
```
Fill in `AGENT_PRIVATE_KEY` (and `MERCHANT_SUBMITTER_KEY`, which can be the same funded EOA or the payout wallet key) in `ap4m/.env`. Never commit `.env`. Both wallets that submit on-chain transactions (Agent opening a Channel; Merchant redeeming a Voucher) need XRP for gas from `https://faucet.testevm.ripple.com`.

### 2. Start the Cereal AP4M x402 Merchant (Terminal 1)
Serves the Ripple Swell 2026 agenda dataset behind HTTP 402 at `http://127.0.0.1:4308/resource` for `0.25` RLUSD per call:
```bash
node ap4m/merchant.mjs --port 4308 --price 0.25
```

### 3. Pay from the Subagent CLI (Terminal 2)
This is the stable CLI contract called by `cereal/subagent.py`:
```bash
node ap4m/pay.mjs --resource http://127.0.0.1:4308/resource --amount 0.25 --cap 1 --job d_7f3a --tag 9a8b7c6d
```
- Opens (or reuses) a Channel capped at `--cap` RLUSD (`1` RLUSD = the subagent's budget).
- Answers the 402 challenge with an EIP-712 `Voucher` (`buyResource` in `ap4m-x402.mjs`).
- Reports the redemption to the AP4M service and calls `settle()` so RLUSD is disbursed to `0x4a7e1cf40ea929ff5bec4d76b060506f3fe59c44` immediately.
- Prints one JSON line:
  ```json
  {"ok":true,"rail":"ap4m","channel_id":"0x...","amount":"0.25","cumulative":"0.25","redeem_tx":"0x...","receipt_id":"https://hackathon.ap4m.build/public/evidence/claims/0x.../0x....json","merchant_payout_delta":"0.25","explorer":"https://explorer.testnet.xrplevm.org/tx/0x..."}
  ```

### 4. Prove Over-Cap Refusal
Asking for an amount above `--cap` (or above the remaining unredeemed capacity on the Channel) is refused before signing or sending any voucher and exits non-zero:
```bash
node ap4m/pay.mjs --resource http://127.0.0.1:4308/resource --amount 1.50 --cap 1 --job d_7f3a --tag 9a8b7c6d
# -> {"ok":false,"rail":"ap4m","refused":"over_cap","amount":"1.50","cap":"1",...}
```

### 5. Verify the Claim Receipt Independently
```bash
node ap4m/verify.mjs <receipt_id_or_claim_id>
```
Wraps `verify-receipt.mjs` (`@ap4m/sdk`'s `verifyClaimReceipt`) to verify the `ap4m.claim-receipt.v1` artifact against the public RPC: checks the `PooledEscrowVault` payout transaction, ERC-20 RLUSD transfer, payout wallet balance observation, redeemed `Voucher`, and `SettlementRecorded` event on `PaymentLedger`.

---

## Metadata (`job` and `tag`) Note

The AP4M protocol's EIP-712 `Voucher(bytes32 channelId, uint256 cumulativeAmount)` struct and `X402PaymentPayload` (`extensions: Record<string, never>`) use strict closed-schema validation (`@ap4m/sdk` rejects unknown fields in `extensions` or the voucher). Therefore:
- On-chain / protocol level: `job` and `tag` are **not** carried inside the EIP-712 `Voucher` or `PAYMENT-SIGNATURE` header (the kit allows no custom metadata fields in those structures).
- Local & CLI level: `pay.mjs` deterministically binds `job` and `tag` into the idempotent x402 `operation` name (`<job>-<tag>-<hash>`), scopes the local channel/purchase state directory per `job`, and echoes `job`, `tag`, and `operation` in the JSON output line so `cereal/export.py` can join AP4M receipts with the cereal job's private `team / project / task` mapping.

---

## Mapping to Mastercard AP4M Judging Criteria (3-Minute Live Demo)

| Judging Criterion | How `ap4m/` Proves It |
|---|---|
| **1. Agent pays an HTTP 402 with no human in the loop** | `pay.mjs` calls `buyResource()` (`ap4m-x402.mjs`), receives `402 Payment Required` with `PAYMENT-REQUIRED`, verifies the Merchant challenge against finalized chain state and the subagent's `--cap`, signs the EIP-712 `Voucher` + `X402ResourceBinding`, and retries with `PAYMENT-SIGNATURE`. |
| **2. `VoucherRedeemed` on `PaymentLedger`** | `merchant.mjs` (`createX402Merchant`) verifies the signature and submits `redeemVoucher` to `0xcAB42800A5ECF0D253Fa2581Bb3334B4DAEfaE91`, emitting `VoucherRedeemed(channelId, claimId, voucherDigest, ...)`. Both Merchant and Agent verify canonical block inclusion of this event. |
| **3. RLUSD reaching the Merchant payout wallet** | `pay.mjs` reports the redemption and invokes `settle()`, which triggers `PooledEscrowVault.executePayout` (`0x83DD9cD010eb46e96eceF8F7eB0a18f7845AaBC0`) to transfer RLUSD (`0x27b57a9D0b8d24EB97259c4E2279e45255e016f3`) to `0x4a7e1cf40ea929ff5bec4d76b060506f3fe59c44`, and measures the on-chain ERC-20 balance delta (`merchant_payout_delta`). |
| **4. Programmatic spending limits (Discover → Authorize → Execute → Settle)** | Each cereal subagent gets a Channel capped at `--cap` RLUSD (its job budget). Any voucher exceeding `cap - redeemed` is refused off-chain by `pay.mjs` (`refused: "over_cap"`) and on-chain by `PaymentLedger`. |
| **5. Verifiable receipt (`ap4m.claim-receipt.v1`)** | `verify.mjs` downloads the published receipt from `/public/evidence/claims/<claimId>/<settlementDigest>.json` and cryptographically verifies the vault payout, token transfer, and `SettlementRecorded` anchor against `https://rpc.testnet.xrplevm.org`. |
