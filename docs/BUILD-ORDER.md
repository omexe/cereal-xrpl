# cereal — build order, in parts

Build one part at a time. A part is done when its acceptance checks pass on testnet with hashes recorded here; only then start the next. Commit every 15–20 minutes with the part and step in the message (`p1.3: …`); never squash. `docs/SPEC.md` has the contracts for each part.

| Part | Scope | Status |
|---|---|---|
| **1** | **Main agent on the main wallet deploys subagents into subwallets** | **done**: verified on testnet Oct 24 (hashes below), including retire |
| **2** | **Vendor trust: on-ledger vendor credentials and revocation replace the Part 1 allowlist; refusal beats** | **done**: wired into the co-sign policy and the main agent flow; beats verified on testnet Oct 24 (hashes below) |
| 3 | Ledger device: owner approves deployments on the device; device is a recovery signer on every subwallet | built and verified on Speculos — wire in after Part 2 |
| 4 | Payment rails: x402 via t54 (+ Verifiable Intent) and Mastercard AP4M on XRPL EVM | not built |
| 5 | Accounting and visibility: tags, export, QuickNode webhook feed, dashboard | export built; webhook and dashboard not built |
| 6 | Submission: demo script, README, HACKATHON.md, video, answers | not built |

---

## Part 1 — main agent, main wallet, subagents, subwallets

**What it proves.** An owner gives the main agent a goal and an envelope. The main agent splits the goal into subtasks and deploys one subagent per subtask, each into its own subwallet that the main wallet creates, locks and funds with exactly that subtask's budget. Subagents pay from their own subwallet only, every payment co-signed by cereal; no subagent can touch the main wallet or another subagent's money. When a subagent is done, the main agent reclaims what is left and the subwallet is retired.

**Out of scope for Part 1:** vendor credentials (Part 2; Part 1 uses a per-subagent payee allowlist), the Ledger device (Part 3; the main wallet key is software), x402 and AP4M (Part 4), export and UI (Part 5).

**Reuse (already verified on testnet):** `cereal/lock.py` (sequential lock), `cereal/fund.py` (software funding), `cereal/pay.py` + `cereal/cosign.py` (agent-signed, co-signed payments; `tefBAD_QUORUM` when alone), `cereal/burn.py` (sweep, trust line close with `tfSetNoRipple`, `AccountDelete`), `cereal/ledger.py` (fees, expiry, memos, instant refusals).

### p1.1 Subwallet factory — `cereal/subwallets.py`
`create(budget) -> Subwallet`: generate a fresh keypair; activate the account with an XRP `Payment` from the main wallet (`reserve_base + 2 × reserve_inc + 0.5` = 1.9 XRP on testnet today; read reserves from `server_info`, never hard-code); lock it with the existing sequential lock (`TrustSet` limit = budget → `SignerListSet` {subagent 1, cereal 1} quorum 2 → `AccountSet` asfDisableMaster); then forget the master seed. No faucet in the path.

Acceptance: activation hash + three lock hashes; `is_locked()` true; the master seed is not on disk.

### p1.2 Subagent keys — `cereal/keystore.py`
One fresh key per subagent (Ed25519), stored at `keys/subagents/<deployment_id>.json` (gitignored, mode 600). The subagent process loads only its own key. The main agent never sees any key.

Acceptance: two deployments have two different signer addresses on their subwallets' signer lists.

### p1.3 Deployments store and caps — `cereal/deployments.py`
Replaces `jobs.py` (keep a thin alias). Record per deployment: id, parent (`main`), task, budget, allowed payees, expiry, subwallet, subagent address, status (`deploying → active → reclaimed → retired`), payments, every hash. Caps enforced in the service, never by the main agent: `MAX_SUBAGENT_BUDGET`, `MAX_OUTSTANDING_BUDGET`, `MAX_ACTIVE_SUBAGENTS`.

Acceptance: a deployment that would exceed a cap is refused with the cap named; no transaction is sent.

### p1.4 Service endpoints — `cereal/service.py` (FastAPI, :8001; mounts the existing `/cosign`)
`POST /subagents` (deploy: create subwallet, fund from main wallet, register, return the deployment without keys) · `GET /subagents` · `GET /subagents/{id}` (live balance, payments) · `POST /subagents/{id}/reclaim` (sweep remainder to main, close trust line) · `POST /subagents/{id}/retire` (`AccountDelete` once ≥256 ledgers old; returns the reserve) · `GET /main` (main wallet balances, outstanding budget, caps) · `POST /cosign` (existing; Part 1 policy: deployment active, payment from its subwallet, payee in its allowlist, amount ≤ balance, not expired, memo matches).

Acceptance: every endpoint returns the Result shape from `docs/SPEC.md`; a deploy shows activation, lock and fund hashes.

### p1.5 Subagent runner — `cereal/subagent.py`
`python -m cereal.subagent <deployment_id> "<task>"`: an agent loop with tools `budget_left()`, `pay(payee, amount, invoice_id=None)`, `done(summary)`. It signs only with its own key and every payment goes through `/cosign`. Runs as its own process so subagents are isolated.

Acceptance: a subagent pays an allowlisted payee (co-signed `tesSUCCESS`); the same subagent submitting alone gets `tefBAD_QUORUM`; paying a non-allowlisted payee is refused by cereal.

### p1.6 Main agent — `cereal/main_agent.py`
`python -m cereal.main_agent --goal "…" --envelope 3`: an agent loop (Anthropic SDK; Strands later for AWS) with tools `main_wallet()`, `deploy_subagent(task, budget, allowed_payees)`, `list_subagents()`, `wait(subagent_id)`, `reclaim_subagent(id)`. It plans subtasks, deploys them through the service, launches each subagent process, waits, and reclaims. It holds no keys.

Acceptance (the Part 1 demo): one goal → two subagents in two subwallets, deployed and funded from the main wallet, each paying twice, both reclaimed; the run prints the tree `main → subagent → subwallet → payments` with explorer links; the main wallet balance before and after reconciles to the payments.

### p1.7 Part 1 tests and record  ✅
`tests/test_part1.py` (offline, `make test`): caps, co-sign refusals before any network call, the even planner; 11 pass. `tests/test_part1_testnet.py` (live, opt-in, `make acceptance`): every acceptance check asserted against the ledger; `test_part1_retire_when_old_enough` retires the test store's subwallets once they are ~15 min old (rerun `make acceptance` later, or `CEREAL_DEPLOYMENTS_FILE=deployments.testnet.json` with `--retire-all`).

**Part 1 acceptance, verified on testnet Sat Oct 24:**
| Check | Evidence |
|---|---|
| Service deploy (d_213c9d) | activate `5E03636C…`, lock `2C878DA1…`/`6850E243…`/`3D1F9ED0…`, fund `1625C4EA…` (43 s) |
| Cap refusal | budget 6 > `MAX_SUBAGENT_BUDGET` 5 → `cap_exceeded`, nothing sent |
| Subagent alone | `tefBAD_QUORUM` |
| Payee not on the allowlist | refused by `/cosign` (`payee_not_allowed`) |
| Reclaim | sweep `8A3ABE18…`, trust line closed `591DF5C5…`; retire too early → `too_young` (225 ledgers) |
| `make main-agent` (goal → 2 subagents) | d_31496c: activate `7D3FC29E…`, fund `AA045F5D…`, pays `7719802A…` `DDAE7F5E…`, reclaim `2B003D75…` `2BE5DC58…`; d_379fdc: activate `7FB20117…`, fund `337F945F…`, pays `2387359B…` `C60F96AF…`, reclaim `44647F80…` `642C46A6…`; both proved `tefBAD_QUORUM` alone; main wallet 20.7477 → 19.7477 RLUSD = the four 0.25 payments, reconciled |
| Retire | d_31496c `580BF24E…`, d_379fdc `1B096C08…` (`AccountDelete`, reserve back to the main wallet) |
| `make acceptance` (opt-in pytest, live testnet, own service on :8011 with outstanding cap 2.5) | passed Oct 24 in 2 min 49 s: per-subagent and outstanding cap refusals with the main wallet's Sequence unchanged; deploys d_6dd34f (activate `16A4B410…`, fund `BF42DFCD…`), d_409220 (activate `D793648A…`, fund `1B3835CF…`); on-ledger: master disabled, quorum 2, signers = {subagent, cereal}, trust-line limit = budget; each subagent alone `tefBAD_QUORUM`; 4 payments verified multi-signed with SourceTag and memo; payee/over-budget refusals with the subwallet's Sequence unchanged; reclaims with trust lines deleted; main −1.0 RLUSD = vendor A +1.0 RLUSD; retire refused too early. Evidence JSON in `exports/` |


---

## Part 2 — vendor trust and refusal beats
**What it proves.** A subagent may pay any vendor that holds a cereal vendor credential on-ledger, and nobody else. Blocking a vendor is one public `CredentialDelete` that every cereal customer's co-signer reads, and each refusal carries that transaction as evidence. A hijacked subagent is stopped twice (cereal refuses, then the ledger refuses the agent alone), and an attacker holding both keys is capped by the subwallet's balance and cannot touch the main wallet.

### p2.1 Credential check in the co-sign policy — `cereal/service.py`  ✅
`CEREAL_REQUIRE_VENDOR_CREDENTIAL=1` (default). Policy order: deployment active → payment from its subwallet → vendor credential (`vendor_not_credentialed` with `vendor` evidence) → allowlist only if non-empty (`payee_not_allowed`) → RLUSD → balance → expiry → memo. `POST /subagents` accepts an empty allowlist when credentials are on; `GET /main` reports the policy.

### p2.2 Vendor lifecycle — `cereal/vendors.py`  ✅
`issue` / `accept` / `revoke` (memo `cereal/vendor-revocation` `{reason, report}`) / `check` → `valid | pending | expired | revoked | none`. A re-issue after a revocation supersedes it. CLI: `python -m cereal.vendors check|issue|accept|revoke VENDOR_B`.

### p2.3 Hijack beat — `cereal/subagent.py --hijack`  ✅
An injected instruction tells the subagent to move everything to a random address. Layer 1: cereal refuses (`vendor_not_credentialed`, status `none`). Layer 2: the agent signs alone and the ledger refuses (`tefBAD_QUORUM`).

### p2.4 Stolen-keys beat — `cereal/beats.py stolen-keys`  ✅
With the subagent key and the co-signer key together: an over-balance drain is `tecPATH_PARTIAL` on-ledger (nothing moves) and a spend from the main wallet is `tefBAD_SIGNATURE`.

### p2.5 Beats through the main agent — `make beats`  ✅
`python -m cereal.main_agent --beats`: subagent 1 tries revoked vendor B first, is refused with the revocation hash, falls back to vendor A; subagent 2 is hijacked; then the stolen-keys beat runs on subagent 2; both are reclaimed and the main wallet reconciles.

### p2.6 Part 2 tests and record
`tests/test_part2.py` (offline): credential states, revocation evidence before the allowlist, empty allowlist = any credentialed vendor, allowlist narrows, `no_payee_policy` when credentials are off. `tests/test_part2_testnet.py` (live, opt-in, `make acceptance`): vendor B's whole lifecycle on-ledger plus both beats.

**Part 2, verified on testnet Sat Oct 24:**
| Check | Evidence |
|---|---|
| Vendor A credentialed | `4A974099…` / `8C8B0DEC…` |
| Vendor B revoked (memo `overcharge`) | first `C0237EDD…` (used by `make beats`); current `3FF46EE4…` after the acceptance run. The co-signer always cites the newest `CredentialDelete`. |
| `make beats` (goal → 2 subagents, credentials on, no allowlist) | d_61e7f7: activate `A47F4B16…`, fund `98A734FF…`; refused vendor B with evidence `C0237EDD…`; paid vendor A `17DAFA31…` `8A4CF016…`; reclaim `0F9324E8…` `25F94D52…`. d_6efe83: activate `016F290B…`, fund `1322AC9B…`; hijack layer 1 `vendor_not_credentialed`, layer 2 `tefBAD_QUORUM`; stolen keys `tecPATH_PARTIAL` `27054551…` and `tefBAD_SIGNATURE` on the main wallet; paid vendor A `B677EFDD…` `739C29CB…`; reclaim `A5B46469…` `0CD7289A…`. Main wallet 18.7477 → 17.7477 RLUSD = the four 0.25 payments, reconciled |
| `make acceptance` Part 2 (opt-in pytest, own service on :8012, credentials on, no allowlist) | passed Oct 24 in 2 min 14 s: paid credentialed vendor A `884E421F…`; vendor B issued `B30752D2…` → refused while `pending` → accepted `7C18D746…` → paid `7DA79839…` → revoked `A1C5C110…` → refused with exactly that hash as evidence and the subwallet's Sequence unchanged; hijack layer 1 `vendor_not_credentialed`, layer 2 `tefBAD_QUORUM`; stolen keys `tecPATH_PARTIAL` `79C42C10…` with the balance unchanged and `tefBAD_SIGNATURE` on the main wallet; reclaim; main wallet −0.50 RLUSD = the two payments. Evidence JSON in `exports/` |

## Part 3 — Ledger device (after Part 2)
The main wallet's subwallet funding is signed on the owner's Ledger (the device is a signer on the main wallet: `C195250E…`; `cereal/fund.py fund_burner_on_device`, `ledger/multisign.ts fund`). Every subwallet's signer list adds the owner's Ledger at weight 2 so the device alone can recover funds (`LEDGER_ADDRESS`). Verified already: device-signed funding `9357D8D5…`, device-only sweep `9A10502B…`. DX feedback for Ledger in `docs/DX-FEEDBACK.md`.

## Part 4 — payment rails (after Part 3)
- **x402 via t54:** subagents buy from vendor A's paid endpoint (`x402/server.py`); test whether the facilitator accepts the subwallet's multisigned payment, else submit directly and send the hash; attach a Verifiable Intent chain (`docs/INTEGRATIONS.md` §2).
- **Mastercard AP4M:** one AP4M Channel per subagent (`capRlusd` = subagent budget) to the vendor's Merchant on XRPL EVM testnet; the subagent pays a 402 with signed vouchers; settlement and receipts recorded (`docs/SPEC.md` Part 4). Portal onboarding first.

## Part 5 — accounting and visibility (after Part 4)
Tags (hmac of team/project/task) on every memo, `cereal/export.py` CSV across subwallets and AP4M receipts (built), QuickNode endpoint and one webhook feeding the payment list, and a dashboard showing the tree main → subagents → payments.

## Part 6 — submission (Sun 09:00 code lock → 12:00 submit)
Update `docs/DEMO-SCRIPT.md` to the main-agent/subagent story; README with the live URL first and the primitives table; `HACKATHON.md` (what was built after Sat 10:00 with commit links, what is mocked); 2–3 minute video; submission answers; opt into the bounties.

## Cut order if time runs short
Part 5 dashboard → AP4M (keep x402) → Verifiable Intent → Part 3 device funding (keep recovery signer). Never cut Part 1.
