# cereal — technical spec (backend), by part

Status Sat Oct 24 ~7 PM EDT: Part 1 built and verified on testnet. The build order is `docs/BUILD-ORDER.md`; this file holds the contracts. Build Part 1 completely before wiring anything from later parts into it.

**What it is.** A main agent connected to a company's main wallet deploys subagents. Each subagent gets its own subwallet, created and funded by the main wallet with exactly its budget and locked by the ledger so no single key can spend. Subagents pay from their own subwallet only; when they finish, the main agent reclaims what is left and the subwallet is deleted. Later parts add on-ledger vendor trust, the owner's Ledger device, x402 and Mastercard AP4M payments, and the accounting export.

## Vocabulary

| Term | Meaning | In code (current name) |
|---|---|---|
| main wallet | the company's XRPL account that holds RLUSD and funds every subwallet | role `TREASURY` |
| main agent | the planner agent: takes a goal, deploys and reclaims subagents; holds **no keys** | `cereal/main_agent.py` (to build) |
| cereal service | deterministic service that holds the main-wallet key (Part 1) and the co-signer key, enforces caps and policy | `cereal/service.py` (to build; `cereal/cosign.py` exists) |
| subagent | a worker agent with one task, one budget, one key, one subwallet | `cereal/subagent.py` (to build) |
| subwallet | the subagent's XRPL account: budget-exact, 2-of-2 locked, deleted at the end | "burner" in existing modules |
| deployment | the record linking a subagent, its subwallet, task, budget, payees, expiry, hashes | "job" in `cereal/jobs.py` |
| co-signer | cereal's key on every subwallet's signer list; signs only after policy checks | role `CEREAL_COSIGN` |

---

## Part 1 — main agent → subagents → subwallets (built and verified Oct 24; hashes in BUILD-ORDER)

### 1.1 Trust boundaries
- The **main agent** (an LLM) can only call the service. It cannot sign anything, so a hijacked main agent can at most deploy subagents within the caps.
- The **cereal service** holds the main-wallet key and the co-signer key. It creates and funds subwallets only through `POST /subagents` and only within caps; it co-signs only `Payment`s from its own subwallets that pass policy. In Part 1 it also loads a subagent's key from the local keystore to co-sign that subwallet's reclaim and retire; Part 3 replaces this with the owner's Ledger (weight 2) signing alone.
- Each **subagent** holds one key that is a weight-1 signer on its own subwallet and nothing else. Alone it cannot move a drop (`tefBAD_QUORUM`); it can never reach the main wallet or another subwallet.
- The **subwallet** holds exactly its budget, its trust-line limit equals its budget (it cannot even receive more), and its master key is disabled after the lock.

### 1.2 Ledger objects per deployment (testnet; all live on mainnet)

| Step | Transaction (signed by) | Fields |
|---|---|---|
| Activate | `Payment` XRP main wallet → new address (main-wallet key) | `Amount` = reserve_base + 2 × reserve_inc + 0.5 XRP (1.9 XRP today; read `server_info`) |
| Lock 1 | `TrustSet` (subwallet master) | `LimitAmount` = budget in RLUSD (currency `524C555344000000000000000000000000000000`, issuer `rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV`) |
| Lock 2 | `SignerListSet` (subwallet master) | `SignerQuorum` 2; entries subagent key 1, `CEREAL_COSIGN` 1 |
| Lock 3 | `AccountSet` (subwallet master) | `SetFlag` 4 (asfDisableMaster); after Lock 2. Master seed then discarded. |
| Fund | `Payment` RLUSD main wallet → subwallet (main-wallet key) | `Amount` = budget; memo kind `fund` |
| Pay | `Payment` RLUSD subwallet → payee (subagent + co-signer, multisigned) | memo kind `pay`; optional `InvoiceID`; `Fee` sized for 2 signers; `LastLedgerSequence` ≈ current + 75 |
| Reclaim | `Payment` remainder → main wallet, then `TrustSet` limit 0 + `tfSetNoRipple` (multisigned) | trust line must reach default state or delete fails |
| Retire | `AccountDelete` → main wallet (multisigned, `fail_hard`) | allowed once Sequence + 256 < current ledger (~15 min after activation); returns the reserve |

Every transaction carries `SourceTag` 20260601 and a cereal memo: `MemoType` hex("cereal/job"), `MemoFormat` hex("application/json"), `MemoData` hex(`{"job":"<deployment_id>","tag":"<hmac>","kind":"activate|lock|fund|pay|reclaim|retire"}`).

### 1.3 Deployment record (`deployments.json`, gitignored)
```json
{"d_7f3a": {"id": "d_7f3a", "parent": "main", "task": "pull the Swell agenda from vendor A",
            "budget": "1.5", "currency": "RLUSD", "allowed_payees": ["rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"],
            "expires_at": "2026-10-25T17:00:00+00:00", "subwallet": "r…", "subagent": "r…",
            "status": "deploying|active|reclaimed|retired",
            "hashes": {"activate": "…", "lock": ["…", "…", "…"], "fund": "…", "reclaim": ["…", "…"], "retire": "…"},
            "payments": [{"to": "r…", "amount": "0.5", "result": "tesSUCCESS", "hash": "…", "at": "…"}]}}
```
Subagent keys live in `keys/subagents/<id>.json` (gitignored, mode 600), never in the record.

### 1.4 Service API (`cereal/service.py`, FastAPI, port 8001)

| Method | Path | Body / result |
|---|---|---|
| `GET` | `/main` | `{address, xrp, rlusd, outstanding_budget, active_subagents, caps}` |
| `POST` | `/subagents` | body `{task, budget, allowed_payees[], expires_in_hours=24}` → deployment record + `hashes`; refusal `{ok:false, refused:"cap_exceeded", cap, limit, requested}` or `{refused:"insufficient_main_balance"}` |
| `GET` | `/subagents` | list of deployments with live balances |
| `GET` | `/subagents/{id}` | deployment + `balance` + `payments` |
| `POST` | `/cosign` | body `{deployment_id, tx}` (agent-signed JSON with its `Signers` entry, `SigningPubKey: ""`) → **Result**; refusals: `unknown_or_inactive_deployment`, `not_a_subwallet_payment`, `payee_not_allowed`, `not_rlusd`, `over_budget`, `expired`, `memo_mismatch` |
| `POST` | `/subagents/{id}/reclaim` | sweep + trust-line close → `{steps: [(name, Result)], returned}` |
| `POST` | `/subagents/{id}/retire` | `AccountDelete` → Result; refusal `{refused:"too_young", ready_in_ledgers}` |

**Result** = `{ok, result, hash, explorer, validated, message?}`. `tef/tem/tel/ter` (and `tec` under `fail_hard`) return immediately with `hash: null`; `tes/tec` return after validation with a hash. Refusals are results, never exceptions.

Caps (env, enforced only in the service): `MAX_SUBAGENT_BUDGET` (default 5), `MAX_OUTSTANDING_BUDGET` (10), `MAX_ACTIVE_SUBAGENTS` (5).

### 1.5 Agents

**Main agent** (`python -m cereal.main_agent --goal "…" --envelope 2 --subagents 2 [--prove-lock]`; `--retire-all` later): Anthropic SDK tool loop when `ANTHROPIC_API_KEY` is set, otherwise an even split of the envelope; (model `claude-sonnet-5-5`; Strands/AgentCore is a Part 4 swap for the AWS bounty). Tools, each a call to the service: `main_wallet()`, `deploy_subagent(task, budget, allowed_payees)`, `list_subagents()`, `wait(subagent_id, timeout_s)`, `reclaim_subagent(id)`. It also launches each subagent process (`python -m cereal.subagent <id> "<task>"`). Its system prompt states the envelope and that it must reclaim every subagent before finishing.

**Subagent** (`python -m cereal.subagent <deployment_id> "<task>" [--payments 2] [--amount 0.25] [--prove-lock]`): its own process; tool loop with a key, deterministic plan without; loads only `keys/subagents/<id>.json`. Tools: `budget_left()`, `pay(payee, amount, invoice_id=None)` (builds the Payment, signs with `multisign=True`, POSTs `/cosign`), `done(summary)` (writes the summary to the deployment). In Part 1 a payment to vendor A stands in for a purchase; Part 4 replaces it with an x402 call.

### 1.6 Python modules for Part 1

| Module | New or reused | Surface |
|---|---|---|
| `cereal/subwallets.py` | new | `create(budget, c) -> {address, activation_hash, lock_hashes}` (fresh keypair, activation from the main wallet, `lock.lock_burner`, master seed discarded) |
| `cereal/keystore.py` | new | `new_subagent_key(deployment_id) -> address`, `load(deployment_id) -> Wallet` |
| `cereal/deployments.py` | new (replaces `jobs.py`) | `create`, `get`, `update`, `record_payment`, `active()`, `outstanding_budget()` |
| `cereal/service.py` | new | the API in 1.4; imports the co-sign policy from `cosign.py` |
| `cereal/subagent.py`, `cereal/main_agent.py` | new | the loops in 1.5 |
| `cereal/lock.py`, `fund.py`, `pay.py`, `burn.py`, `ledger.py` | reused | `lock_burner(..., recovery_addr=None)` for Part 1; `burn.burn` splits into reclaim + retire |
| `cereal/preflight.py` | reused | add main wallet outstanding budget and active subagents |

### 1.7 Part 1 acceptance (record hashes in `docs/BUILD-ORDER.md`)
1. `POST /subagents` twice → two subwallets, each with activation, three lock and one fund hash; `is_locked` true; balances equal budgets; two distinct subagent signer addresses.
2. Each subagent pays an allowlisted payee twice (co-signed `tesSUCCESS`); the same subagent alone gets `tefBAD_QUORUM`; a non-allowlisted payee is refused by `/cosign`.
3. A deploy beyond `MAX_OUTSTANDING_BUDGET` is refused with no transaction sent.
4. Both subagents reclaimed; the main wallet's RLUSD after equals before minus the payments.
5. After ~15 minutes, `retire` deletes both subwallets.
6. `python -m cereal.main_agent --goal …` does 1, 2 and 4 by itself and prints the tree with explorer links.

---

## Part 2 — vendor trust and refusal beats (done)
**Credential.** The payee must hold a `cereal:vendor:data` credential (`CredentialType` hex `63657265616c3a76656e646f723a64617461`) issued by `CREDENTIAL_ISSUER` (`rKsUzgmh1iMvYQMtqDnKaF7VV8xE5GR9yW`) and accepted by the vendor (`lsfAccepted`). `vendors.check` reads the ledger, not a database, and returns `{status: valid|pending|expired|revoked|none, revocation?}`.

**Revocation.** `CredentialDelete` by the issuer with memo type `cereal/vendor-revocation` and data `{reason, report}`. It is public, so one transaction blocks the vendor for every cereal customer. The newest `CredentialDelete` for the subject and class is the evidence; a later `CredentialCreate` supersedes it.

**Co-sign policy** (`CEREAL_REQUIRE_VENDOR_CREDENTIAL=1`, the default): deployment active → payment from its subwallet → vendor credential `valid` (else `vendor_not_credentialed` with the `vendor` check, including the revocation hash) → allowlist only if the deployment has one (`payee_not_allowed`) → RLUSD → balance → expiry → memo. Every refusal is recorded on the deployment with its evidence and sends no transaction. With credentials on, `POST /subagents` may omit `allowed_payees`; with them off it refuses `no_payee_policy`.

**Beats.**
| Beat | Who | Expected |
|---|---|---|
| Revoked vendor | subagent → `/cosign` | `vendor_not_credentialed`, evidence = the `CredentialDelete` hash; subagent falls back to a credentialed vendor |
| Hijacked subagent, layer 1 | subagent → `/cosign` for a random address | `vendor_not_credentialed` (status `none`) |
| Hijacked subagent, layer 2 | subagent signs alone and submits | `tefBAD_QUORUM` |
| Stolen keys (subagent + co-signer) | over-balance drain from the subwallet | `tecPATH_PARTIAL` on-ledger, balance unchanged |
| Stolen keys | spend from the main wallet | `tef*` (`tefBAD_SIGNATURE`) |

**Run.** `make beats` (main agent, 2 subagents, `--beats`); `python -m cereal.beats stolen-keys <deployment_id>`; `python -m cereal.vendors check|issue|accept|revoke VENDOR_B`. Hashes are in `docs/BUILD-ORDER.md` Part 2.

## Part 3 — Ledger device (after Part 2; built on Speculos)
- **Owner approves funding:** the device (`rn1FZHRNBPX8g2Y5Xzhx1LonhmSheFYMAq`) is a signer on the main wallet (`C195250E…`); `POST /subagents` funds through `fund.fund_burner_on_device` → `ledger/multisign.ts fund` (clear-signed RLUSD Payment). Verified `9357D8D5…`.
- **Recovery signer:** subwallet signer list becomes {subagent 1, cereal 1, Ledger 2}, quorum 2; the device alone can sweep (`ledger/multisign.ts sweep`, verified `9A10502B…`) and retire.
- Device facts: pass `encode(tx)` with empty `SigningPubKey` and no `Signers`; the XRP app adds the multisign prefix and its AccountID; parallel only; clear-signs Payment/TrustSet/SignerListSet/AccountSet/AccountDelete; Credentials/Batch need blind signing.

## Part 4 — payment rails (after Part 3; not built)
- **x402 (t54):** a subagent's `pay` becomes `buy(resource_url)`: GET → 402 → build Payment from the challenge → co-sign → present. `x402-xrpl`'s client signs with one wallet, so test whether the facilitator (`https://xrpl-facilitator-testnet.t54.ai`) accepts a multisigned blob; else submit directly and send the hash. Verifiable Intent chain via t54 (`docs/INTEGRATIONS.md` §2).
- **Mastercard AP4M (XRPL EVM testnet, chain 1449000, RPC `https://rpc.testnet.xrplevm.org`):** one Channel per subagent, `capRlusd` = subagent budget, to the vendor's Merchant; the subagent answers a 402 with an EIP-712 voucher (`buyResource` in `ap4m-x402.mjs`); the service settles RLUSD to the merchant payout and issues `ap4m.claim-receipt.v1` receipts. Contracts: PaymentLedger `0xcAB42800A5ECF0D253Fa2581Bb3334B4DAEfaE91`, RLUSD `0x27b57a9D0b8d24EB97259c4E2279e45255e016f3` (18 decimals). SDK: `npm install ethers@6.17.0 https://hackathon.ap4m.build/sdk/ap4m-sdk.tgz` + `ap4m-hackathon-sdk.js`, `ap4m-x402.mjs`. Judges check a `VoucherRedeemed` event, RLUSD at the payout wallet, and a 402-driven payment with no human in the loop, live in three minutes. Portal onboarding (Agent wallet, Merchant payout wallet, budget deposit, gas) is done by a human at `https://hackathon.ap4m.build/participant`. Suggested home: `ap4m/` (Node), called from Python like `ledger/`.
- **AWS:** move the main agent and subagents onto Strands + Bedrock AgentCore.

## Part 5 — accounting and visibility (after Part 4; export built)
Tag = first 32 hex of HMAC-SHA256(`CEREAL_TAG_HMAC_KEY`, "team|project|task") in every memo. `cereal/export.py` CSV (date, ledger_index, kind, type, result, from, to, amount, currency, hash, explorer, team, project, task, job_id, sentence) across subwallets plus AP4M receipts. QuickNode: `QUICKNODE_XRPL_HTTP/_WS` for all RPC and one webhook on subwallet payments → `POST /webhooks/quicknode` → live feed. Dashboard: tree main → subagents → payments, refusal cards, reclaim/retire buttons, export.

## Part 6 — submission
`docs/DEMO-SCRIPT.md` rewritten to the main-agent/subagent story, README, `HACKATHON.md`, video, answers.

---

## Reference

### Stack
Python 3.11+ (venv 3.13) · `xrpl-py` 5.2 · FastAPI + uvicorn · `requests`, `python-dotenv` · `x402-xrpl` 0.3.4 · `anthropic` · pytest · Node 22+ for `ledger/` (`@ledgerhq/device-management-kit` ^1.11, `@ledgerhq/device-signer-kit-xrp` ^0.3, `@ledgerhq/device-transport-kit-speculos`, `xrpl` ^5.3, `tsx`) · Speculos in Docker via Colima (`speculos-xrp`, Nano S Plus XRP app) · Part 4: `ethers` 6.17.0 + AP4M SDK · RPC: public testnet or QuickNode.

### Accounts (testnet; seeds only in `.env`)
| Role | Address | Part |
|---|---|---|
| TREASURY (main wallet) | `rGP3CdfnKSSz4BYPNTjKiNGzM98xDxbEfj` | 1 (holds ~17 RLUSD, ~40 XRP; signer list {Ledger 1} from Part 3) |
| CEREAL_COSIGN | `rhwqNLJMGtzxWm3hdUXBMnn2mEZyR6PJxN` | 1 |
| AGENT (legacy single agent key) | `rEfMS8TyAzcAhLZrd1pTERcqSxoE1UmnKy` | replaced by per-subagent keys in Part 1 |
| VENDOR_A | `rGrhEwizViewpp8b91RTdUV2MpdWUdaEay` | 1 (allowlisted payee), 2 (credentialed), 4 (x402 seller) |
| VENDOR_B | `rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3` | 2 (revoked) |
| CREDENTIAL_ISSUER | `rKsUzgmh1iMvYQMtqDnKaF7VV8xE5GR9yW` | 2 |
| LEDGER (Speculos) | `rn1FZHRNBPX8g2Y5Xzhx1LonhmSheFYMAq` | 3 |
| BURNER_1, BURNER_3 | `r983iEDb…`, `rKYJm4q2…` | pre-made pool (BURNER_2 retired); Part 1 creates subwallets on demand instead |

### Environment (`.env`, template `.env.example`)
`XRPL_TESTNET_RPC_URL`, `XRPL_TESTNET_WS_URL`, `QUICKNODE_XRPL_HTTP/_WS` · `<ROLE>_SEED`/`<ROLE>_ADDRESS` · `RLUSD_TESTNET_ISSUER` · `CEREAL_SOURCE_TAG` · `CEREAL_TAG_HMAC_KEY` · `COSIGN_URL` · `MAX_SUBAGENT_BUDGET`, `MAX_OUTSTANDING_BUDGET`, `MAX_ACTIVE_SUBAGENTS` (Part 1) · `ANTHROPIC_API_KEY` · `LEDGER_ADDRESS`, `SPECULOS_URL`, `SPECULOS_MODEL` (Part 3) · x402 and AP4M variables (Part 4).

### Verified on testnet (Oct 24)
Sequential lock `03616E0A…`/`A512CC1D…`/`B22CE98F…` · co-signed pay `7B2FC286…` · alone `tefBAD_QUORUM` · end-to-end job on BURNER_2: lock `13567BA9…`/`56D59A40…`/`123CA438…`, device funding `9357D8D5…`, pay `1CE4AB4C…`, revoked vendor refused, `tecPATH_PARTIAL` `DE340B70…`, sweep `A7CB9A0D…`, trust line closed `AB21A804…`, `AccountDelete` `7EEC6B44…`, export 10 rows · x402 via t54 (single key) `B628848C…` · treasury RLUSD via testnet AMM `4291601F…`.

### Gotchas
- Lock sequentially: a single `Batch` returned outer `tesSUCCESS` with all inner transactions rolled back and no inner results in metadata.
- `xrpl-py` `submit_and_wait` waits until `LastLedgerSequence` on a `tef`; `ledger.submit_capture` submits and polls itself.
- Close a trust line with limit 0 **and `tfSetNoRipple`**, or `AccountDelete` fails with `tecHAS_OBLIGATIONS`.
- `AccountDelete` needs ~15 minutes of account age: reclaim at once, retire later.
- RLUSD faucet (`tryrlusd.com`) needs a GitHub sign-in; testnet AMM self-payment is the fallback.
- `x402-xrpl`'s client signs with one wallet; the 2-of-2 subwallet needs the direct path (Part 4).

### Run
`make setup && make pool && make preflight` · `make cosign` (Part 1: `uvicorn cereal.service:app --port 8001`) · `make demo` (current single-job script) · Speculos: `docker start speculos-xrp`; `cd ledger && npm install && npm run address`.
