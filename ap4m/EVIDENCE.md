# AP4M On-Chain Evidence (XRPL EVM Testnet, Chain 1449000)

## Verified Pre-Existing On-Chain State (Oct 24, 2026)

| Object | Identifier / Hash | Details |
|---|---|---|
| **ParticipantRegistry** | `0x4cF27435FE56161aa9b1cffdD87784aa68b7D1E8` | Registered Team "Cereal" Agent & Merchant |
| **Agent Participant ID** | `0xb7ff548a3e06db04643dfbd69bc0c062e898a73b9803dfe57a8ebca1e72b81ac` | Bound to Agent EOA `0xcb362681022f922b3b5090c3cdc3b57ba6b891b7` (`status = 1 Active`) |
| **Merchant Participant ID** | `0xc01be948b7eae6994cbef40dea79f5a2ef8af335e53772bb943226a1bca04cb5` | Bound to Payout EOA `0x4a7e1cf40ea929ff5bec4d76b060506f3fe59c44` (`status = 1 Active`) |
| **PooledEscrowVault** | `0x83DD9cD010eb46e96eceF8F7eB0a18f7845AaBC0` | Holds Cereal's 20.0 RLUSD budget deposit |
| **Active Funding Account ID** | `0x5c63e03942db4da90985f682404a346b58d3fce99472433f4bfa6e61395e28d6` | `deposited = 20.0 RLUSD`, `activeReserved = 20.0 RLUSD`, `status = 1 Active` |
| **PaymentLedger** | `0xcAB42800A5ECF0D253Fa2581Bb3334B4DAEfaE91` | Verifies EIP-712 `Voucher` signatures and records settlements |
| **RLUSD Token** | `0x27b57a9D0b8d24EB97259c4E2279e45255e016f3` | 18 decimals on XRPL EVM Testnet |

---

## Live Run Evidence (Oct 24, 2026, ~21:00 UTC)

First live run by Gemini from its clone (job `d_ap4m01`, 0.25 RLUSD, cap 1), after Andrew saved the agent key and Claude bridged 5 XRP of gas to the agent wallet (XRPL testnet tx `885A558F…` through Axelar's testnet gateway). Every hash below was re-checked on-chain from the main clone: the `VoucherRedeemed` log, the payout wallet's RLUSD balance, and the receipt.

Once `ap4m/.env` is populated with `AGENT_PRIVATE_KEY` and the wallet holds XRP gas from `https://faucet.testevm.ripple.com`, run:
```bash
# Terminal 1
node ap4m/merchant.mjs --port 4308 --price 0.25

# Terminal 2: Paid 402 call
node ap4m/pay.mjs --resource http://127.0.0.1:4308/resource --amount 0.25 --cap 1 --job d_ap4m01 --tag 7f3a9c12

# Terminal 2: Over-cap refusal check (verified offline & online)
node ap4m/pay.mjs --resource http://127.0.0.1:4308/resource --amount 1.50 --cap 1 --job d_ap4m01 --tag 7f3a9c12

# Terminal 2: Independent receipt verification
node ap4m/verify.mjs <receipt_id>
```

| Step | Output / Transaction Hash |
|---|---|
| **Over-cap refusal (`--amount 1.50 --cap 1`)** | `{"ok":false,"rail":"ap4m","refused":"over_cap","amount":"1.50","cap":"1","job":"d_ap4m01","tag":"7f3a9c12","message":"Requested payment 1.50 RLUSD exceeds channel cap 1 RLUSD"}` (exit code `1`) |
| **Cumulative on-chain over-cap refusal (`--amount 0.80 --cap 1`)** | `{"ok":false,"rail":"ap4m","refused":"over_cap","channel_id":"0x2c34d28c8f558324a937f4880f7066cad00ef686e7f3bc6a8771c45363d6bdb9","amount":"0.80","cap":"1.0","redeemed":"0.25","requested_cumulative":"1.05","job":"d_ap4m01","tag":"7f3a9c12"}` (exit code `1`) |
| **Channel ID (`--cap 1`)** | `0x2c34d28c8f558324a937f4880f7066cad00ef686e7f3bc6a8771c45363d6bdb9`, opened by the agent in vault request tx [`0xea9584df…`](https://explorer.testnet.xrplevm.org/tx/0xea9584df9b4351ceee8a01e3c49630bc8644ae5e706e9c43eea57f011e7a543e), vault bind tx [`0xecc07f22…`](https://explorer.testnet.xrplevm.org/tx/0xecc07f221fdd9acbfcad39581257a987c57a9f602b4ce5cda365300e4e38027b), and `openChannel` tx [`0x05cdd637…`](https://explorer.testnet.xrplevm.org/tx/0x05cdd637e921b0192d6ae73b1b1d39689f3a683f91a54acf7a7abb4aa164a1ac) (20:58:49 UTC) |
| **`VoucherRedeemed` tx (`redeem_tx`)** | [`0x701727ff6b4fa8dd6685aa467c4772f7a52cc55117600901de453b5c1082196c`](https://explorer.testnet.xrplevm.org/tx/0x701727ff6b4fa8dd6685aa467c4772f7a52cc55117600901de453b5c1082196c) on PaymentLedger, block 9224046: amount 0.25, cumulative 0.25, payout `0x4A7e…9c44` |
| **Claim ID (`claim_id`)** | `0x35c57918aa1f1c07da331a2f1069f1c96e7e43e55ece1cbc95114cf459097b73` |
| **Vault Payout tx (`payout_tx`)** | [`0xf7cf03425db8c1e09e7c5442956c99590e117ad85bdbd69f8d4674996eec801b`](https://explorer.testnet.xrplevm.org/tx/0xf7cf03425db8c1e09e7c5442956c99590e117ad85bdbd69f8d4674996eec801b) |
| **Settlement Recorded tx (`settlement_tx`)** | [`0x5d88b85cc104f87029839cfcee9f71e1a9776931f8a472c7b58ef3b7148e89cb`](https://explorer.testnet.xrplevm.org/tx/0x5d88b85cc104f87029839cfcee9f71e1a9776931f8a472c7b58ef3b7148e89cb) |
| **Merchant Payout RLUSD Delta** | +0.25 RLUSD: the payout wallet's RLUSD balance read on-chain is 0.25 after the run (it held none before) |
| **Verified Receipt (`ap4m.claim-receipt.v1`)** | `verified: true`, amount 0.25, checked against chain 1449000 (ledger, vault, token) via `node ap4m/verify.mjs <claim_id>`; receipt: https://hackathon.ap4m.build/public/evidence/claims/0x35c57918aa1f1c07da331a2f1069f1c96e7e43e55ece1cbc95114cf459097b73/0xbee545e7a3865dd3d36e1b39ba10446534cc5f2414cbf657b8f3659e2a2cc6e2.json |
