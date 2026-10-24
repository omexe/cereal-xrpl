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

## Live Run Evidence (Pending XRP Gas + `ap4m/.env` Private Key)

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
| **Channel ID (`--cap 1`)** | _pending live run_ |
| **`VoucherRedeemed` tx (`redeem_tx`)** | _pending live run_ |
| **Claim ID (`claim_id`)** | _pending live run_ |
| **Vault Payout tx (`payout_tx`)** | _pending live run_ |
| **Settlement Recorded tx (`settlement_tx`)** | _pending live run_ |
| **Merchant Payout RLUSD Delta** | _pending live run_ |
| **Verified Receipt (`ap4m.claim-receipt.v1`)** | _pending live run_ |
