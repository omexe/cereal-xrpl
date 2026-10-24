# Brief for Gemini: the Mastercard AP4M rail (Part 4b)

**Goal.** A cereal subagent pays a merchant over Mastercard's AP4M kit on the XRPL EVM sidechain, with no human in
the loop: it hits a 402, pays with an EIP-712 voucher inside a channel capped at the subagent's budget, and the
merchant's RLUSD lands on-chain. Claude is building Part 3 (Ledger) in `cereal/` and `ledger/` at the same time,
so this work must stay inside a new `ap4m/` folder.

## Where to work
- Use your own clone, not the folder Claude is working in:
  `git clone https://github.com/omexe/cereal-xrpl ../cereal-xrpl-ap4m`
- Create and touch only `ap4m/`. Do not edit `cereal/`, `ledger/`, `tests/`, `Makefile`, `docs/BUILD-ORDER.md`,
  `docs/SPEC.md` or `CLAUDE.md`.
- Small commits prefixed `p4.ap4m:`. Run `git pull --rebase` before every push to `main`.

## Read first
1. https://hackathon.ap4m.build/llms.txt: network, contract addresses, guides, every kit file. Follow its links.
2. Mastercard's `AGENTS.md` from that site. Save it as `ap4m/AGENTS.md`, never at the repo root.
3. In this repo: `docs/PROJECT.md` (what cereal is) and `docs/INTEGRATIONS.md` section 2 (Mastercard judging).

## Team state, from the participant portal (Oct 24)
- Team "Cereal", registration active. Agent wallet `0xcb362681022f922b3b5090c3cdc3b57ba6b891b7`.
- Merchant payout wallet `0x4a7e1cf40ea929ff5bec4d76b060506f3fe59c44`; merchant registered.
- Budget: 20 RLUSD deposited by the organizer. No channel and no payments yet.
- Network: XRPL EVM testnet, chain id 1449000, RPC https://rpc.testnet.xrplevm.org.
- The agent wallet holds 0 XRP for gas. Andrew funds it from https://faucet.testevm.ripple.com.

## Build
1. `ap4m/package.json` (ESM): `npm install ethers@6.17.0 https://hackathon.ap4m.build/sdk/ap4m-sdk.tgz`, plus the
   kit files the guides name (`ap4m-x402.mjs`, `verify-receipt.mjs`, `ap4m-hackathon-sdk.cjs`). `ap4m/.gitignore`
   with `.env` and `node_modules`. `ap4m/.env.example` lists variable names only.
2. **Merchant:** one cereal data resource (for example "Swell agenda JSON") behind a 402, built with the kit's
   merchant-resource helpers and paid to the team's merchant payout wallet.
3. **Agent CLI**, the contract Claude will call from `cereal/subagent.py` in Part 4. Keep it stable:
   ```bash
   node ap4m/pay.mjs --resource <url> --amount 0.25 --cap 1 --job <deployment_id> --tag <tag>
   ```
   It opens or reuses a channel capped at `--cap` RLUSD (the subagent's budget), pays the 402 with a voucher,
   redeems, and prints exactly one JSON line:
   `{"ok":true,"rail":"ap4m","channel_id":…,"amount":…,"cumulative":…,"redeem_tx":…,"receipt_id":…,"merchant_payout_delta":…,"explorer":…}`.
   A refusal prints `{"ok":false,"refused":"<reason>",…}` and exits non-zero. A payment over the cap must be refused.
   Carry `job` and `tag` wherever the kit allows metadata. If it allows none, say so in the README.
4. `ap4m/verify.mjs`: verifies a receipt independently with `verify-receipt.mjs` against the public RPC.
5. `ap4m/README.md`: how to run it, and how it maps to each judging point (agent pays a 402 with no human,
   `VoucherRedeemed` on PaymentLedger, RLUSD reaching the merchant payout wallet, live 3-minute demo).
   `ap4m/EVIDENCE.md`: the transaction hashes from a real run.

## Done when
On XRPL EVM testnet: one paid call with no human click, a `VoucherRedeemed` event, the merchant payout wallet's RLUSD
up by the amount, an over-cap request refused, a receipt verified, and all hashes in `ap4m/EVIDENCE.md`.

## Rules
- `AGENT_PRIVATE_KEY` lives only in `ap4m/.env`, which Andrew fills in. Never commit, print, log or send a private
  key to any API, including AP4M's.
- Do not sign in to the portal, request faucet funds, deposit or move funds. Andrew does those.
- Do not invent APIs or call a simulated step live. If the kit doesn't do something, write that down.
- If blocked (no gas, missing starter kit, unclear endpoint), stop and write what is needed in `ap4m/BLOCKERS.md`.
