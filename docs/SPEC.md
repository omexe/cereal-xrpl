# cereal — technical spec (backend)

Status as of Sat Oct 24 ~5 PM EDT. Read with `docs/PROJECT.md` (why), `docs/DEMO-SCRIPT.md` (what we show), `docs/BUILD-ORDER.md` (steps), `docs/INTEGRATIONS.md` (Ledger, Mastercard), `CLAUDE.md` (rules).

**What it is.** Disposable, budget-exact XRPL wallets for AI agents. One plain-English sentence becomes a job; the job gets a burner wallet locked by the ledger (no single key can spend), funded with exactly its budget in RLUSD on a Ledger device, paying only credentialed vendors, and deleted at the end into an accounting export. A second rail pays through Mastercard AP4M on the XRPL EVM sidechain.

## 1. Stack

| Layer | Choice | Notes |
|---|---|---|
| Core | Python 3.11+ (venv: 3.13) | package `cereal/` |
| XRPL SDK | `xrpl-py` 5.2 | Batch, SignerListSet, AccountDelete, Credential*, `multisign`, `autofill(signers_count=)` |
| Services | FastAPI + uvicorn | co-sign service on :8001 (`cereal/cosign.py`) |
| x402 | `x402-xrpl` 0.3.4 (t54) | vendor A's paid endpoint `x402/server.py` on :8000; facilitator `https://xrpl-facilitator-testnet.t54.ai` |
| Compiler | `anthropic` (model `claude-sonnet-5-5`) with a regex fallback | `cereal/compiler.py`; works without a key |
| Device | Node 22+, `@ledgerhq/device-management-kit` ^1.11, `@ledgerhq/device-signer-kit-xrp` ^0.3, `@ledgerhq/device-transport-kit-speculos`, `xrpl` (js) ^5.3, `tsx` | `ledger/`; Speculos in Docker (Colima), container `speculos-xrp`, Nano S Plus XRP app |
| Mastercard rail | XRPL EVM testnet (chain 1449000), `ethers` 6.17.0, AP4M SDK (`https://hackathon.ap4m.build/sdk/ap4m-sdk.tgz`, `ap4m-hackathon-sdk.js`, `ap4m-x402.mjs`) | not in the repo yet; see §9 |
| RPC | public testnet, or QuickNode via `QUICKNODE_XRPL_HTTP/_WS` | `cereal/config.py` prefers QuickNode when set |
| Tests | pytest (`pyproject.toml` sets `pythonpath`) | `make test`, no network |
| Web | open (team's choice) | should call the API in §6; nothing built yet |

## 2. Architecture

```
owner sentence ──► compiler.py ──► conditions card (owner reads + signs)
                                         │
                                  jobs.py (jobs.json: job ↔ burner, budget, expiry, tag ↔ team/project/task)
                                         │
             ┌───────────────── lock.py ─┴─ fund.py / ledger fund ────────────────┐
             │  burner: TrustSet(limit=budget) → SignerListSet{agent 1, cereal 1,  │
             │  Ledger 2} q=2 → AccountSet(asfDisableMaster)                       │
             │  treasury → burner RLUSD Payment, signed on the Ledger              │
             └──────────────────────────────────────────────────────────────────────┘
agent (agent.py tools) ── pay.py: agent signs as multisig signer ──► cosign.py :8001
                                                                      │ checks: job, burner, vendor credential
                                                                      │ (ledger_entry), RLUSD, budget, expiry, tag
                                                                      ▼
                                                               co-sign + submit ──► XRPL testnet
vendor registry: vendors.py (CREDENTIAL_ISSUER issues/revokes `cereal:vendor:data`)
end of job: burn.py (sweep → TrustSet 0 → AccountDelete) ──► export.py (CSV from account_tx + jobs.json)
recovery: ledger/multisign.ts sweep (device alone, weight 2)
```

## 3. Accounts (testnet; seeds only in `.env`)

| Role | Address | Purpose |
|---|---|---|
| TREASURY | `rGP3CdfnKSSz4BYPNTjKiNGzM98xDxbEfj` | holds RLUSD; signer list {Ledger 1} q=1 (master kept as fallback) |
| LEDGER (Speculos) | `rn1FZHRNBPX8g2Y5Xzhx1LonhmSheFYMAq` | owner's device: signs budgets, weight-2 recovery signer on burners |
| AGENT | `rEfMS8TyAzcAhLZrd1pTERcqSxoE1UmnKy` | agent key, weight 1 on burners |
| CEREAL_COSIGN | `rhwqNLJMGtzxWm3hdUXBMnn2mEZyR6PJxN` | co-signer key, weight 1 on burners; never holds funds |
| BURNER_1..3 | `r983iEDb…`, `r4J4evbR…`, `rKYJm4q2…` | pool (BURNER_1 locked; BURNER_2 used by the e2e run) |
| VENDOR_A | `rGrhEwizViewpp8b91RTdUV2MpdWUdaEay` | credentialed vendor; runs `x402/server.py` |
| VENDOR_B | `rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3` | credential revoked (`C0237EDD…`, reason "overcharge") |
| CREDENTIAL_ISSUER | `rKsUzgmh1iMvYQMtqDnKaF7VV8xE5GR9yW` | issues/revokes vendor credentials |

New burners: `python scripts/setup_pool.py` after adding empty `BURNER_n_SEED=` lines. A burner must be ≥256 ledgers old (~15 min) before `AccountDelete`.

## 4. Ledger objects and exact fields

| Step | Transaction (signer) | Fields that matter |
|---|---|---|
| Lock 1 | `TrustSet` (burner master) | `LimitAmount` = budget in RLUSD (`524C555344000000000000000000000000000000`, issuer `rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV`). The limit is also a cap: the burner cannot receive more than its budget. |
| Lock 2 | `SignerListSet` (burner master) | `SignerQuorum` 2; entries AGENT 1, CEREAL_COSIGN 1, LEDGER 2 (if `LEDGER_ADDRESS` set) |
| Lock 3 | `AccountSet` (burner master) | `SetFlag` 4 (asfDisableMaster). Must come after the signer list. Sent sequentially: a single `Batch` returned outer `tesSUCCESS` with all inner txs rolled back on testnet. |
| Fund | `Payment` TREASURY → burner (Ledger signs as multisig signer of TREASURY) | RLUSD amount = budget; `SourceTag` 20260601; `Memos[0]` = cereal memo (kind "fund") |
| Pay | `Payment` burner → vendor (AGENT + CEREAL_COSIGN multisign) | RLUSD; `SourceTag`; `Memos[0]` cereal memo (kind "pay"); optional `InvoiceID`; explicit `Fee` (sized for 2 signers) and `LastLedgerSequence` ≈ current + 75 |
| Revoke vendor | `CredentialDelete` (CREDENTIAL_ISSUER) | `Subject`, `CredentialType` hex(`cereal:vendor:data`) = `63657265616c3a76656e646f723a64617461`; memo type `cereal/vendor-revocation` {reason, report} |
| Recover | `Payment` burner → treasury (LEDGER alone, weight 2) | `ledger/multisign.ts sweep` |
| Burn | `Payment` remainder → TREASURY, `TrustSet` limit 0, `AccountDelete` → TREASURY (multisigned) | `AccountDelete` with `fail_hard`; fee = owner reserve increment |

**cereal memo:** `MemoType` hex("cereal/job"), `MemoFormat` hex("application/json"), `MemoData` hex(`{"tag":"<hmac>","job":"<id>","kind":"lock|fund|pay|burn"}`), compact JSON. `tag` = first 32 hex of HMAC-SHA256(`CEREAL_TAG_HMAC_KEY`, "team|project|task"); plain team/project/task never go on-chain.

## 5. Python modules (public surface)

| Module | Functions | Returns |
|---|---|---|
| `config` | `wallet(role)`, `address(role)`; constants `RPC_URL`, `SOURCE_TAG`, `RLUSD_*`, `LEDGER_ADDRESS`, `COSIGN_URL`, `JOBS_FILE` | |
| `ledger` | `client()`, `prepare(tx, c, signers_count=, window=75)`, `submit_capture(signed, c, fail_hard=)`, `sign_submit(tx, w, c)`, `multisign_submit(tx, [wallets], c, quorum_signers=)`, `cosign_and_submit(agent_signed, cosigner, c)`, `job_tag()`, `job_memo()`, `decode_memos()`, `stamp(tx, memos)`, `rlusd(v)`, `rlusd_balance(c, addr)`, `account_tx(c, addr)` | every submit returns **Result** (below) |
| `jobs` | `create(sentence, card, burner)`, `get(id)`, `by_burner()`, `by_tag()`, `update(id, **f)`, `record_payment(id, entry)`, `all_jobs()` | job dict (§7) |
| `compiler` | `compile_sentence(sentence)` | card: `{budget, currency, vendor_class, expires_at, tag{team,project,task}, signers, compiled_by}` |
| `lock` | `lock_burner(burner_wallet, agent_addr, cosign_addr, budget, c, job_id=, tag=, sequential=True, recovery_addr=LEDGER_ADDRESS)`, `is_locked(c, addr)` | list of Results; `{master_disabled, signer_quorum, signers, locked}` |
| `fund` | `fund_burner(treasury_wallet, burner, budget, job_id, tag, c)` (software), `fund_burner_on_device(burner, budget, job_id, tag)` (runs `ledger` fund) | Result (+ `signed_on: "ledger"`) |
| `vendors` | `issue()`, `accept()`, `revoke(issuer, vendor, c, reason, report_hash)`, `check(c, vendor)`, `revocation(c, vendor)` | `{status: valid|pending|revoked|none, revocation?{hash, explorer, reason, report}}` |
| `pay` | `build_payment()`, `agent_sign(tx, agent, c)`, `request_cosign(job_id, signed)`, `pay(job, vendor, amount, agent, c)`, `refusal_single_signer(...)` | cosign response |
| `burn` | `burnable_in(c, addr)`, `burn(burner, treasury, agent, cosign, c, job_id, tag)` | `[(step, Result)]` |
| `export` | `rows_for_burner(c, addr)`, `export_csv(path, c, burners=None)` | CSV columns: date, ledger_index, kind, from, to, amount, currency, hash, explorer, team, project, task, job_id, sentence |
| `agent` | tool contract: `check_vendor(address)`, `budget_left(job_id)`, `pay_vendor(job_id, address, amount, invoice_id=None)` | wire into Strands or the Anthropic tool loop |
| `demo` | CLI: `python -m cereal.demo --sentence "…" --burner BURNER_n [--fund device|software] [--amount 0.5] [--burn]` | prints every step |
| `preflight` | `python -m cereal.preflight` | roles, balances, lock state, burn eligibility, credential status |

**Result** = `{ok: bool, result: "tesSUCCESS"|"tefBAD_QUORUM"|"tecPATH_PARTIAL"|…, hash: str|null, explorer: url|null, validated: bool, message?: str}`. `tef/tem/tel/ter` return immediately with `hash: null` (never in a ledger); `tec*` and `tes*` return after validation with a hash. Never raise on a ledger refusal; the UI shows it.

## 6. HTTP API

**Exists — co-sign service** (`uvicorn cereal.cosign:app --port 8001`):
- `GET /health` → `{status, cosigner}`
- `POST /cosign` body `{job_id, tx}` where `tx` is the agent-signed transaction JSON (`Signers` with the agent's entry, `SigningPubKey: ""`). Checks in order: job exists and is active · `Payment` from the job's burner · destination credential `valid` · RLUSD · amount ≤ burner balance · not expired · memo tag/job match. Success → Result. Refusal → `{ok: false, refused: unknown_or_closed_job|not_a_burner_payment|vendor_not_credentialed|not_rlusd|over_budget|job_expired|tag_mismatch, …evidence}` (`vendor_not_credentialed` carries `vendor.revocation` with the `CredentialDelete` hash).

**To build — dashboard API** (suggested; same FastAPI app or a sibling): `POST /jobs {sentence}` → card · `POST /jobs/{id}/sign` (lock + fund) · `GET /jobs`, `GET /jobs/{id}` (job + balance + payments) · `POST /jobs/{id}/burn` · `GET /jobs/{id}/export.csv` · `GET /vendors/{address}` · `POST /vendors/{address}/revoke {reason}` · `POST /webhooks/quicknode` (payment feed). Keep the Result shape.

## 7. Data model (`jobs.json`, gitignored)

```json
{"<id>": {"id": "ab12cd34", "sentence": "…", "burner": "r…", "budget": "5", "currency": "RLUSD",
          "vendor_class": "data", "expires_at": "2026-10-25T21:00:00+00:00", "tag": "<32 hex>",
          "team": "growth", "project": "swell-brief", "task": "news", "created_at": "…",
          "status": "created|funded|active|burned", "payments": [{"to": "r…", "amount": "0.5", "ok": true, "result": "tesSUCCESS", "hash": "…", "at": "…"}]}}
```
A JSON file is enough for the hackathon (single co-sign process). If two processes write, move to SQLite.

## 8. Environment (`.env`, template `.env.example`)
`XRPL_TESTNET_RPC_URL`, `XRPL_TESTNET_WS_URL`, `QUICKNODE_XRPL_HTTP/_WS` · `<ROLE>_SEED` / `<ROLE>_ADDRESS` for every role in §3 · `LEDGER_ADDRESS` · `RLUSD_TESTNET_ISSUER` · `CEREAL_SOURCE_TAG` (20260601) · `CEREAL_TAG_HMAC_KEY` · `COSIGN_URL` · `ANTHROPIC_API_KEY` (optional) · x402: `XRPL_BUYER_SEED`, `XRPL_PAY_TO`, `XRPL_FACILITATOR_URL`, `XRPL_PRICE_DROPS`, `RESOURCE_URL` · Speculos: `SPECULOS_URL`, `SPECULOS_MODEL` · AP4M (to add): `AP4M_API_URL`, `AP4M_TEAM_NAME`, `AP4M_AGENT_PRIVATE_KEY`, `AP4M_PAYMENT_LEDGER`, `AP4M_CHANNEL_ID`, `AP4M_MERCHANT_ID`, `AP4M_MERCHANT_PAYOUT`, `AP4M_MERCHANT_SUBMITTER_KEY`.

## 9. Mastercard rail (AP4M, XRPL EVM testnet) — to build
Their judging (integration guide): the agent reads a 402, decides and pays with no human in the loop; a `VoucherRedeemed` event on the PaymentLedger contract; RLUSD reaches the merchant payout wallet; full flow live in 3 minutes; creativity.
- Network: chain 1449000, RPC `https://rpc.testnet.xrplevm.org`, gas in XRP from `https://faucet.testevm.ripple.com`. Contracts (`/public/config`): PaymentLedger `0xcAB42800A5ECF0D253Fa2581Bb3334B4DAEfaE91`, RLUSD `0x27b57a9D0b8d24EB97259c4E2279e45255e016f3` (18 decimals).
- Portal onboarding (humans, `https://hackathon.ap4m.build/participant`): add Agent wallet, Merchant payout wallet, deposit budget from the funding wallet, fund gas. Budget is fixed once the Agent is onboarded.
- Code flow: `signIn(api, team, agentWallet)` → `requestChannel(api, token, agentWallet, {capRlusd, merchantId?})` → pay with `buyResource` (x402, `ap4m-x402.mjs`) or `signVoucher`/`redeemVoucher` (cumulative amounts) → `settle` (receipt_url) → `closeChannel`.
- cereal mapping: a job with `rail: "ap4m"` opens one Channel with `capRlusd` = job budget to the vendor's Merchant (our own merchant: `example-x402-merchant.mjs` as vendor A); the vendor credential check on XRPL stays in front of `requestChannel`/`buyResource`; `closeChannel` is the burn; receipts (`ap4m.claim-receipt.v1`) join the export. Suggested home: `ap4m/` (Node), called from Python like `ledger/`.

## 10. Verified on testnet (Oct 24)
| Fact | Evidence |
|---|---|
| Sequential lock with Ledger recovery signer | `03616E0A…`, `A512CC1D…`, `B22CE98F…`; `is_locked` → quorum 2, master disabled |
| Ledger alone sweeps a locked burner | `9A10502B1D32C812…` tesSUCCESS (Speculos multisign) |
| Agent alone refused | `tefBAD_QUORUM` in ~4 s (no hash) |
| Agent + cereal pay | `7B2FC2867E1B6A42…` tesSUCCESS |
| Vendor credentials | A issued `4A974099…`, accepted `8C8B0DEC…`; B revoked `C0237EDD…` |
| Ledger on treasury signer list | `C195250E…` |
| Treasury RLUSD (testnet AMM) | `4291601F…` → 21.75 RLUSD |
| x402 via t54 (single-key payer) | `B628848C…` |
| End-to-end scripted demo on BURNER_2 | running (results added when it completes) |

## 11. Gotchas
- `Batch` lock: outer `tesSUCCESS`, inner rolled back, no inner results in metadata → sequential is the default.
- `xrpl-py` `submit_and_wait` blocks until `LastLedgerSequence` on a `tef` → we use `submit()` + our own `tx` poll.
- Ledger device multisign: pass `encode(tx)` with empty top-level `SigningPubKey` and no `Signers`; the app adds the multisign prefix and its AccountID; parallel only. Clear-signs Payment/TrustSet/SignerListSet/AccountSet/AccountDelete; Credentials/Batch need blind signing.
- `x402-xrpl`'s client signs with one wallet: a 2-of-2 burner cannot use it as is. Test whether the facilitator accepts a multisigned blob; otherwise submit directly and send the hash.
- RLUSD faucet (`tryrlusd.com/api/mint-xrpl`, 10/claim) needs a GitHub sign-in; testnet AMM self-payment is the fallback.
- Burner trust-line limit = budget: a top-up beyond it needs a multisigned `TrustSet` first (a feature: the ledger caps receipts too).
- `account_tx` on a deleted burner may return nothing on public testnet nodes: export before or right after the burn, and keep `jobs.json` payments as the fallback.

## 12. Open work for the backend (pick by initials in the PR)
1. Dashboard API (§6) on top of the existing modules; the web UI consumes it.
2. Agent loop in `cereal/agent.py` (Strands on AgentCore for AWS, else Anthropic tools) using the three tools; planted instruction in vendor A's response.
3. x402 leg for the burner (multisigned payment through the facilitator, or direct-submit fallback) + Verifiable Intent chain through t54 (`docs/INTEGRATIONS.md` §2).
4. AP4M rail (§9) in `ap4m/`.
5. QuickNode endpoint + one webhook feeding the payment list.
6. `HACKATHON.md`, README run section, tests for lock/pay/burn against testnet (marked, skipped in CI).

Run: `make setup && make pool && make preflight` · `make cosign` (one terminal) · `make demo` · Speculos: `docker start speculos-xrp`, then `cd ledger && npm install && npm run address`.
