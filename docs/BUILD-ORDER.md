# cereal — build order (Sat Oct 24 ~1:30 PM → Sun Oct 25 12:00 PM submit)

Hard part first: the ledger facts the demo rests on must exist as testnet hashes before any UI. Each step has an acceptance check. Commit every 15–20 minutes with the step number in the message; never squash. Everything targets `docs/DEMO-SCRIPT.md`; if it is not in the script, it is cut. Stack: Python 3.10+, `xrpl-py` 5.x (has Batch, SignerListSet, AccountSet, AccountDelete, Credential*, `multisign`), `x402-xrpl`, FastAPI; one small Node folder (`ledger/`) for the Ledger device, because Ledger's SDK is TypeScript-only.

## Layout to build toward

```
cereal/              python package
  ledger.py          client (QuickNode if set), fee + LastLedgerSequence helpers, memo/tag encoding, submit + result capture
  lock.py            Batch: TrustSet → SignerListSet (2-of-2) → AccountSet(asfDisableMaster)
  fund.py            treasury RLUSD Payment to a burner (software signer; the device path lives in ledger/)
  pay.py             agent-signed Payment → POST /cosign → submitted hash, or the raw refusal
  vendors.py         CredentialCreate / CredentialAccept / CredentialDelete + check_vendor(address)
  cosign.py          FastAPI: POST /cosign {job_id, tx_blob} → verify → co-sign → submit
  burn.py            Payment remainder → TrustSet 0 → AccountDelete (fail_hard)
  export.py          account_tx over burners → CSV
  compiler.py        sentence → conditions card JSON (LLM); the owner signs the card; the agent never calls this
  agent.py           the agent loop (Strands if AWS creds exist, else Anthropic SDK) with tools check_vendor / pay_vendor / budget_left
x402/                existing merchant + client (VENDOR_A's paid endpoint; add the planted instruction to its response)
ledger/              Node + @ledgerhq DMK + Speculos: signs the treasury funding Payment (clear-signed)
scripts/             new_wallet.py, send_payment.py, setup_pool.py (creates co-signer + burners, writes .env)
web/                 dashboard: job card, payment feed, decline card, burn, export (team's choice of stack)
docs/                DEMO-SCRIPT.md, BUILD-ORDER.md
HACKATHON.md         created at code lock
```

## 0. Accounts and env (first 30 minutes; also ages the burner pool)

Roles (seeds in `.env`, never committed): `TREASURY` company treasury (funds burners; the device signs) · `AGENT` per-job agent key · `CEREAL_COSIGN` co-signer (software, never holds funds) · `BURNER_1..3` pool (master keys destroyed after the lock Batch) · `VENDOR_A` approved vendor running `x402/server.py` · `VENDOR_B` approved then revoked · `CREDENTIAL_ISSUER` cereal's vendor-credential issuer. `.env.example` lists them.

Do now: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`; `python scripts/setup_pool.py` (faucet-funds any missing role and writes `.env`); get testnet RLUSD into `TREASURY` (tryrlusd.com; needs the issuer's destination tag) or, if that stalls, issue 1,000 `USD` from `CREDENTIAL_ISSUER`'s sibling account and say "RLUSD-equivalent IOU" in the demo. **Create the burners now:** `AccountDelete` requires the account's Sequence + 256 < current ledger (about 15 minutes), and the burn is the last beat.

Acceptance: every role resolves on `account_info` with a balance.

## 1. The lock (h0–h1) — hashes #1a–c  ✅ verified on testnet

`cereal/lock.py` sends, in order: `TrustSet` RLUSD (limit = budget) → `SignerListSet` (quorum 2; AGENT weight 1, CEREAL_COSIGN weight 1, and the owner's Ledger weight 2 when `LEDGER_ADDRESS` is set) → `AccountSet` (asfDisableMaster). The master can only be disabled once a signer list exists, hence the order. The burner's master key signs these three transactions and is then dropped.

Verified Oct 24 on BURNER_1: `03616E0A99…`, `A512CC1D7B…`, `B22CE98F11…` → `is_locked()` = master disabled, quorum 2, signers {cereal 1, Ledger 2, agent 1}. The single-`Batch` form (`lock_burner(..., sequential=False)`) returned `tesSUCCESS` for the outer transaction with all three inner transactions rolled back (`887475D2…`), so sequential is the default and the Batch is only an attempt that falls back on the state check (logged in `docs/DX-FEEDBACK.md`).

Acceptance: `python -m cereal.preflight` shows `locked=True` for the burner.

## 2b. The recovery key (h1–h2) — the Ledger alone sweeps and burns  ✅ verified on testnet

`ledger/multisign.ts`: the device signs a transaction as ONE multisig signer (empty `SigningPubKey`, no `Signers`; the XRP app applies the multisign prefix and appends its own AccountID). `npm run address` prints the device account (put it in `.env` as `LEDGER_ADDRESS` before locking burners); `npm run sweep -- <burner> <treasury> <xrp>` has the device alone move funds out of a locked burner (weight 2 meets the quorum). Clear-signed: Payment, TrustSet, AccountDelete. This is the "if cereal disappears, your Ledger takes your money back" beat and Ledger's "multisig treasuries" gap.

Verified Oct 24 on the locked BURNER_1: device-only sweep `9A10502B1D…` (`tesSUCCESS`, Speculos), agent alone → `tefBAD_QUORUM` (instant with `submit_capture`), agent + cereal → `7B2FC2867E…` (`tesSUCCESS`).

Acceptance: the same three results on a fresh burner for the job.

## 2. The funding, on the device (h1–h2) — hash #2  ✅ verified on testnet

`ledger/fund.ts`: treasury `Payment` of exactly the budget in RLUSD to the burner, `Memos` = hex JSON `{"tag":"<hmac(team,project,task)>","job":"<id>"}`, `SourceTag` = cereal's tag, `DestinationTag` if the issuer needs it, signed through DMK `device-signer-kit-xrp` on Speculos (the XRP app clear-signs IOU Payments). `cereal/fund.py` is the software fallback with the same fields. Set `fee` and `last_ledger_sequence` explicitly.

Acceptance: burner RLUSD balance == budget; explorer shows the memo. Keep the Speculos screenshot.

## 3. The payment and the two refusals (h2–h4) — hash #3 plus two captured results  ✅ verified on testnet

`cereal/pay.py`: agent builds a `Payment` (RLUSD, `memos` tag, `invoice_id`) from the burner, `autofill`, `sign(tx, AGENT, multisign=True)`, POST the signed blob to `/cosign`; the service rebuilds the tx, signs with CEREAL_COSIGN (`multisign=True`), combines with `xrpl.transaction.multisign`, submits with `submit_and_wait`.

Acceptance (all three in the trace): (a) VENDOR_A payment `tesSUCCESS` (hash #3); (b) the same payment submitted with the agent's signature only → `tefBAD_QUORUM` (store the raw `engine_result`; `submit_and_wait` raises on tef, so catch and keep the code); (c) a payment above the balance → `tecPATH_PARTIAL` on-ledger (hash).

## 4. Vendor credentials (h4–h5) — hash #4  ✅ verified on testnet

`cereal/vendors.py`: `CredentialCreate` from CREDENTIAL_ISSUER (`subject`=vendor, `credential_type`=hex of `cereal:vendor:data`), `CredentialAccept` by the vendor, then `CredentialDelete` for VENDOR_B with a memo `{"reason":"overcharge","report":"<hash>"}`. `check_vendor(address)` reads `ledger_entry` (credential: subject, issuer, credential_type) and returns valid / revoked / none.

Acceptance: VENDOR_A co-signed; VENDOR_B declined with the `CredentialDelete` hash as the reason (hash #4).

## 5. The co-sign service (h4–h6)  ✅ verified on testnet

`cereal/cosign.py` (FastAPI, port 8001): `POST /cosign {job_id, tx_blob}` → decode → checks in order: Account is a burner cereal locked for this job; Destination has a valid credential; amount ≤ remaining budget; now < expiry; memo tag matches the job → co-sign → submit → `{hash}`; refusals return `{refused: reason, evidence: <hash or code>}`. Never holds a budget; signs only `Payment`s from its burners and the burn transactions in step 8.

Acceptance: steps 3 and 4 run through the service, not through scripts.

## 6. The x402 leg (h6–h7; first thing to cut)

`x402/server.py` already gates `/hello` through the t54 testnet facilitator. `x402_requests` signs with one wallet, so the 2-of-2 burner cannot use it as is. Try: build the Payment from the 402 challenge yourself (`x402_xrpl` exposes the requirements decoding), co-sign it, and present the multi-signed blob; if the facilitator's `/verify` rejects it, submit the payment directly, retry the request with the hash, and let the vendor verify on-chain. Say which one you shipped.

Acceptance: a 402 → paid → 200 cycle with a hash in the trace.

## 7. The sentence, the agent, the dashboard (h7–h12)

- `cereal/compiler.py`: the LLM turns the sentence into `{budget, currency, vendor_class, expiry, tag:{team,project,task}, signers}`; `web/` renders it as the conditions card; the owner clicks Sign; that JSON drives steps 1–2. The agent never calls the compiler.
- `cereal/agent.py`: tools `check_vendor(address)`, `pay_vendor(address, amount, invoice)`, `budget_left()`; the planted instruction lives in VENDOR_A's response payload. Strands + AgentCore if AWS credentials exist (AWS $2k), otherwise the Anthropic SDK loop.
- `web/`: job card (sentence, conditions, balance, expiry), payment feed, decline card with the explorer link, burn button, export button. Nothing else.
- QuickNode: set `QUICKNODE_XRPL_HTTP`/`_WS` in `.env` so every call goes through it; one Webhook on burner payments → `web/api/webhook` → feed (fallback: poll `account_tx`).

Acceptance: the 90 seconds runs end to end once, sentence to export, by Sat 22:00.

## Sat 22:00 gate

"If we stopped now, is it demoable?" If not, cut in this order: x402 facilitator leg (direct Payment + memo) → QuickNode webhook (poll) → AgentCore deploy (run the loop locally) → Speculos (software treasury key, say so). Never cut: the lock Batch, the two-key payment, `tefBAD_QUORUM`, the credential revoke, the burn, the export.

## 8. The burn and the export (Sun 06:00–09:00) — hashes #5–#7  ✅ verified on testnet

`cereal/burn.py`, multi-signed by AGENT + CEREAL_COSIGN (or by the owner's Ledger alone, weight 2, for the recovery story). Verified Oct 24 on BURNER_2: sweep `A7CB9A0D…`, TrustSet 0 with tfSetNoRipple `AB21A804…`, AccountDelete `7EEC6B44…`. The steps: `Payment` remaining RLUSD → TREASURY (hash #5) → `TrustSet` limit 0 (hash #6; the line deletes at zero balance, zero limit, no flags) → `AccountDelete(destination=TREASURY)` with `fail_hard=True` (hash #7; fee = owner reserve increment). Use a burner from step 0 so it is old enough. `cereal/export.py`: `account_tx` for every burner with cereal's SourceTag, decode memo tags via cereal's mapping, write CSV (date, vendor, amount, hash, team, project, task, sentence).

Acceptance: the burner no longer resolves on the explorer; TREASURY balance rose; the CSV opens.

## 9. Code lock (Sun 09:00) → submit (Sun 12:00)

README: live URL in line one, the primitives table with XLS numbers, explorer hashes #1–#7, run instructions; `HACKATHON.md`: one-liner, what was built after Sat 10:00 with commit links, what is mocked (facilitator fallback; vendor class and expiry enforced by the co-signer); pytest for lock/pay/burn; the 2–3 minute video; the five submission answers from `docs/DEMO-SCRIPT.md` into the platform (`technicalDescription` opens with primitives); opt into the four bounties; submit at 12:00, edit text until 12:30.

## Risks and the honest line

- *Co-signer in the loop:* 2-of-2, non-custodial; the lock is on-ledger; a dead cereal freezes the agent, a compromised cereal cannot spend, and the owner's Ledger (weight 2) can always sweep without cereal. Say it unprompted.
- *Vendor class and expiry are co-signer rules, not ledger rules:* true; the budget and the two-key lock are ledger rules. Payment channels from a burner are the v2 answer for high-frequency vendors.
- *RLUSD testnet friction* (destination tag, faucet): fall back to an own IOU and say so.
- *Batch inner transactions:* on testnet the Batch applied only its outer transaction (inner three rolled back, no inner results in metadata); sequential is the default. Say "three transactions, twelve seconds" and claim Batch only if you demo it working.
- *Facilitator and multi-signed blobs:* unverified; direct submit fallback.
- *AccountDelete age:* burners created in step 0; keep two spares.
- Claim Batch, multi-sign, Credentials, AccountDelete, Memos/SourceTag, RLUSD, x402, device signing. Do not claim delegation or channels.
