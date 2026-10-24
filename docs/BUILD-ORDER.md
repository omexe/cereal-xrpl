# cereal — build order, in parts

Build one part at a time. A part is done when its acceptance checks pass on testnet with hashes recorded here; only then start the next. Commit every 15–20 minutes with the part and step in the message (`p1.3: …`); never squash. `docs/SPEC.md` has the contracts for each part.

| Part | Scope | Status |
|---|---|---|
| **1** | **Main agent on the main wallet deploys subagents into subwallets** | **done**: verified on testnet Oct 24 (hashes below), including retire |
| **2** | **Vendor trust: on-ledger vendor credentials and revocation replace the Part 1 allowlist; refusal beats** | **done**: wired into the co-sign policy and the main agent flow; beats verified on testnet Oct 24 (hashes below) |
| **3** | **Ledger device: owner approves deployments on the device; device is a recovery signer on every subwallet** | **done**: wired into deploy, the main agent and recovery; acceptance passed on testnet with Speculos Oct 24 (hashes below) |
| **4** | **Payment rails: x402 via t54 and Mastercard AP4M on XRPL EVM** | **x402 done** (testnet Oct 24); **AP4M built and verified live, then sidelined** (off by default, `CEREAL_AP4M=1`); Verifiable Intent not started |
| **5** | **Pricing, wallets and visibility: quote-based budgets, plain-English wallets, Ledger approval above a threshold, security log, vendor list, export** | **done**: acceptance passed on testnet Oct 24 (hashes below); the UI team builds from the published dashboard brief |
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

## Part 3 — Ledger device: the owner approves budgets and can take the money back alone
**What it proves.** The main agent can ask for money, but only the owner's Ledger can give it: each subagent's budget payment is shown on the device and signed there before anything touches the ledger, and a rejection sends nothing. Every subwallet carries the owner's device at weight 2, so if cereal disappears the owner sweeps the money home with the device alone. Normal payments still need subagent + cereal; neither alone can spend.

### p3.1 Device signer — `cereal/device.py`, `ledger/multisign.ts sign`  ✅
Python prepares the transaction (fee for one multisig signer, ~150-ledger window for a human to press), the device signs it as a multisig signer (empty `SigningPubKey`, no `Signers`; the XRP app adds the prefix and its AccountID), Python submits. Output is one JSON line with the `Signer` entry and every screen the device showed. Speculos button driver: `CEREAL_DEVICE_DECISION=approve|reject|manual` (manual = a human in the Speculos UI at http://127.0.0.1:5000 or a real device).

### p3.2 Approval before anything touches the ledger — `POST /subagents`  ✅
On by default when `LEDGER_ADDRESS` is set (`CEREAL_DEVICE_FUNDING=0` turns it off). Order: caps → balances → device reachable (else `device_unavailable`) → record + subagent key → subwallet keypair generated locally → the funding `Payment` to that address (main wallet Sequence + 1) is shown and signed on the device → rejected: `owner_rejected`, `sent_transactions: 0`, status `rejected` → approved: activate (Sequence + 0), lock, submit the pre-signed funding. The record keeps `approval {by, result, screens}`.

### p3.3 Recovery signer and owner recovery — `cereal/lock.py`, `cereal/recover.py`  ✅
Signer list {subagent 1, cereal 1, Ledger 2}, quorum 2 (on by default with a device; `CEREAL_LEDGER_RECOVERY=0` turns it off). `python -m cereal.recover <deployment|subwallet> [--retire]`: sweep RLUSD home and close the trust line (and `AccountDelete` once old enough), each signed by the device alone; no cereal key and no service. Status `recovered`; `make retire` also retires recovered subwallets.

### p3.4 Device beats through the main agent — `make device`  ✅
The main agent asks for an extra subagent and the owner rejects it on the device (nothing sent); two subagents are approved, funded and pay; the owner recovers the second with the device alone ("cereal went dark"); the first is reclaimed normally; the main wallet reconciles. The tree prints what the device displayed for every approval.

### p3.5 Part 3 tests and record
`tests/test_part3.py` (offline, 9): device unavailable or rejected = nothing on-ledger; approval precedes activation and the device saw exactly the subwallet that was created; manual mode ignores API button choices; software funding when device funding is off; recovery weight meets quorum alone; recovery sweeps then closes the line, stops if the sweep fails. `tests/test_part3_testnet.py` (live, opt-in, skips without Speculos).

**Part 3, verified on testnet Sat Oct 24 (Speculos nanosp, device `rn1FZHRNBPX8g2Y5Xzhx1LonhmSheFYMAq`):**
| Check | Evidence |
|---|---|
| Device clear-signs the budget payment | screens: Transaction Type Payment · Account (main wallet) · Source Tag 20260601 · Amount 1 · Currency RLUSD · Issuer · Fee · Destination (the new subwallet) · Memo `cereal/job` `{tag, job, kind: fund}` · Sign transaction? |
| Owner rejects (d_43321e) | `owner_rejected`, `sent_transactions: 0`, main wallet Sequence unchanged |
| Owner approves (d_a72682) | funding `3E17BA6B…` with `SigningPubKey ""` and `Signers` = [device] only; activate `2FEB7291…` |
| Signer list | {subagent 1, cereal 1, Ledger 2}, quorum 2, master disabled |
| Normal path | subagent + cereal paid vendor A `F786BA41…` |
| Neither alone | cereal alone `tefBAD_QUORUM`; subagent alone `tefBAD_QUORUM` |
| Owner recovery, device alone | sweep 0.75 RLUSD `3A6F33B5…`, close line `41021605…` (both `Signers` = [device] only); also d_e541a3: sweep `22C962D4…`, close line `266D96A1…` |
| `make acceptance` Part 3 | passed Oct 24 in 2 min 1 s; main wallet down exactly the one 0.25 payment. Evidence JSON in `exports/` |
| `make device` (main agent, 2 subagents, Speculos auto-pressing) | owner rejected an extra 1 RLUSD subagent on the device: 0 transactions. d_0bc9fc: approved on device, activate `FBF725DB…`, device-only funding `30C934C3…`, paid `2C624CD6…` `0445FF5D…`, reclaim `02E6F926…` `B62BD2AD…`. d_0c2dc8: approved, activate `699E5770…`, device-only funding `BEB0DE2C…`, paid `539CC844…` `043F2FFC…`, recovered by the device alone `87070A55…` (sweep) `6BEDF93D…` (close line). Main wallet 16.9977 → 15.9977 RLUSD = the four 0.25 payments, reconciled |

**Boundary, said plainly.** On testnet the main wallet keeps its software key so teammates without the device can run the service; the device is a signer on it (quorum 1). In production the main wallet's master key is disabled and its signer list is {Ledger}, so no budget moves without the device. The activation XRP (refundable reserve, ~1.9 XRP) is software-signed; the device approves the RLUSD budget.

## Part 4 — payment rails: subagents pay paywalls
**What it proves.** A subagent meets an HTTP 402, decides to pay, and pays it from its 2-of-2 subwallet with no human in the loop: cereal runs the same policy as for any payment (credentialed vendor, RLUSD only, within balance, unexpired), co-signs, and the vendor's x402 facilitator settles it on-ledger. A revoked vendor's paywall is refused before anything is signed for it.

### p4.1 Present mode in the co-signer — `POST /cosign {present: true}`  ✅
Same policy, then cereal adds its signature and returns `{hash, blob}` instead of submitting; the payment is recorded `rail: x402, result: presented` and resolved from the ledger when the deployment is read. Policy now also refuses anything but a plain exact RLUSD payment: `partial_payment_not_allowed`, `paths_not_allowed`, `send_max_not_allowed` (x402 sets SendMax; it may not exceed the Amount).

### p4.2 `Subagent.buy(url)` — `cereal/subagent.py`, `cereal/pay.py`  ✅
GET → 402 → pick the `exact` / `xrpl:1` / RLUSD (40-hex, real issuer) option, else `no_rlusd_option` → price over the limit: `price_above_limit` → build the Payment the x402-xrpl payer would (SendMax = Amount, InvoiceID, invoice memo, SourceTag) with cereal's memo first → sign as the subagent → cereal co-signs (present) → `PAYMENT-SIGNATURE` header → 200 + `PAYMENT-RESPONSE` (t54 attestation). On the vendor's `409 settlement_status_unknown`, confirm on-ledger and re-present once; still unserved: `paid_not_served` with the validated hash. CLI: `python -m cereal.subagent <id> "<task>" --buy <url> …`.

### p4.3 Vendors' paywalls and the main agent — `x402/server.py`, `make x402`  ✅
Vendor A charges 0.25 RLUSD per request on `/swell/agenda` and `/swell/speakers` (`make vendor`, :8000); vendor B, revoked, runs the same paywall on :8002 (`make vendor-b`). `make x402`: subagent 1 meets B's paywall first (refused with the revocation), then buys both resources from A; subagent 2 buys both; reclaim; reconcile.

### p4.4 Mastercard AP4M — `ap4m/` (Gemini, from `docs/briefs/GEMINI-AP4M.md`)
Built: merchant (`merchant.mjs`), agent CLI (`pay.mjs --resource --amount --cap --job --tag` → one JSON line), receipt verifier, `ap4m/EVIDENCE.md` with the registered on-chain state. Blocked on two human steps (`ap4m/BLOCKERS.md`): the agent wallet's private key in `ap4m/.env`, and XRPL EVM testnet XRP for gas (https://faucet.xrplevm.org; the portal's faucet host does not resolve). Then: call `pay.mjs` from `Subagent` as a second rail.

### p4.5 Part 4 tests and record
`tests/test_part4.py` (offline, 11): RLUSD option picking (no symbol, no look-alike issuer, no mainnet), memo order and invoice binding, present mode never submits, payment-shape refusals, ledger resolution, buy's price limit, refusals pass through without presenting, the 409 retry. `tests/test_part4_testnet.py` (live, opt-in).

**Part 4 x402, verified on testnet Sat Oct 24 (facilitator https://xrpl-facilitator-testnet.t54.ai):**
| Check | Evidence |
|---|---|
| t54 accepts a 2-of-2 subwallet payment | `6AB99AF9…` (probe): settled, resource served, `t54Attestation` returned |
| `make x402` | d_e94725: approved on Ledger, device-only funding `9CC32A3B…`; vendor B's paywall refused (revocation `3FF46EE4…`); bought agenda `3E9FDF0D…` and speakers `A2E6DE13…`. d_e51b8c: funding `CF3AED22…`; agenda `A00477CD…`, speakers `49DB5D5A…`. Main wallet 14.9977 → 13.9977 RLUSD = the four 0.25 payments, reconciled |
| `make acceptance` Part 4 (own service :8014, vendor A paywall :8010, revoked vendor B paywall :8016) | passed Oct 24 in 1 min 52 s: paid A's paywall `5417BD92…` (t54 attestation `ready`); this run hit `409 settlement_status_unknown`, confirmed on-ledger and re-presented, resource served; on-ledger Signers = {subagent, cereal}, `SigningPubKey ""`, InvoiceID bound, cereal memo first; record resolved to `tesSUCCESS`; B's paywall refused with revocation `3FF46EE4…` and the subwallet's Sequence unchanged; `price_above_limit` sent nothing; main wallet −0.25 RLUSD. Evidence JSON in `exports/` |

## Part 5 — pricing, accounting and visibility
**What it proves.** The main agent never guesses a budget. It reads what vendors sell, takes the binding price from each item's 402, checks every vendor's credential on-ledger, buys from the cheapest trusted vendor, and gives each subagent exactly the quote plus a small buffer. Claude, when a key is set, only chooses which items the goal needs; the money is computed by cereal and enforced by cereal and the ledger.

### p5.1 Vendor catalogs — `x402/server.py`  ✅
Per-item prices (`X402_ITEMS`), one paywall per item, free `GET /catalog`. Demo vendors: A trusted (agenda 0.25, speakers 0.25, `make vendor`), B revoked and cheapest (0.05 each, `make vendor-b`), C trusted (agenda 0.15, speakers 0.30, `make vendor-c`; `r3NdoyQh…`, credential `83C0A7F0…`/`BC78C286…`).

### p5.2 Pricing engine and the shopping main agent — `cereal/pricing.py`, `make shop`  ✅
`plan(goal, envelope)`: needs from the goal (Claude picks catalog items, else word matching), offers per need (catalog, 402 quote, on-ledger credential), cheapest trusted wins, fallbacks kept if they fit, skipped vendors recorded with evidence; budget = quote + max(20 %, 0.05) rounded up; refuses `over_envelope` and `no_trusted_vendor`. The main agent deploys one subagent per need with its budget and its plan (`POST /subagents {plan}`), locked to the plan's vendors (`allowed_payees` = the pick and its fallbacks, so cereal refuses any other vendor); the subagent pays at most the quoted price and falls back in order (`--buy url@max|url@max`). `python -m cereal.pricing "<goal>"` prints a plan without spending.

**Verified on testnet Sat Oct 24 (`make shop`, goal "Pull the Swell agenda and speaker list", envelope 2):**
| Check | Evidence |
|---|---|
| Plan | agenda: C 0.15 chosen, A 0.25 over budget, B 0.05 skipped (revoked `3FF46EE4…`), budget 0.20; speakers: A 0.25 chosen, C 0.30 fallback, B skipped, budget 0.30; 0.50 locked, 1.50 stays in the main wallet |
| d_6cc577 (agenda) | owner approved 0.2 on Ledger, device-only funding `D5F50BCB…`, paid C 0.15 `EDE22D06…`, returned 0.05 |
| d_684aaf (speakers) | owner approved 0.3, funding `23469484…`, paid A 0.25 `553FAAA6…`, returned 0.05 |
| Reconcile | main wallet 10.7477 → 10.3477 RLUSD = the two payments |
| Plan lock (`make shop`, second run) | each subagent may pay only its plan's vendors (`allowed_payees` = pick + fallbacks). d_defbdc (agenda, may pay C only) tried trusted vendor A: `payee_not_allowed`, nothing sent; bought from C `8FBEA0CD…`. d_aadcbc (speakers, may pay A or C) bought from A `83F002A4…`. Main wallet 10.3477 → 9.9477 RLUSD, reconciled |

### p5.4 Vendor list — `GET /vendors`  ✅
Every vendor cereal knows (its vendor roles and every reachable catalog): name, address, items and prices, on-ledger credential, payments received and refusals.

### p5.5 Plain-English wallets — `POST /wallets/preview`, `POST /wallets`  ✅
A sentence ("Market Sizing: spend up to 1 RLUSD over 2 days, only at Vendor A and Vendor C. Ask me above 0.2. Sweep back when done.") becomes a limits card: budget, duration, vendors resolved against the directory and checked on-ledger, approval threshold, sweep when done, with problems (unknown or untrusted vendor, over the cap, no budget) and defaults stated. Preview signs nothing; create rebuilds the card from the sentence, refuses `card_problems`, then deploys with the owner's Ledger approval. Claude parses when a key is set, a deterministic parser otherwise. Optional `folder`.

### p5.6 Ledger approval above a threshold  ✅
Per wallet (`approval_threshold`) and company-wide (`CEREAL_APPROVAL_THRESHOLD`); the lower wins. Above it cereal runs its checks but does not co-sign: the owner's Ledger shows the payment and signs instead (weight 2 + the subagent's 1 meets the quorum); a rejection sends nothing (`owner_rejected`). Works for direct and x402 payments.

### p5.7 Security log — `GET /events`, `POST /subagents/{id}/events`  ✅
One feed of every refused or out-of-policy attempt: who stopped it (owner, cereal, the ledger, the main agent), the reason in plain words, the outcome and the proof. Refusals that happen on the ledger itself (a hijacked subagent signing alone, stolen-keys attempts, lock checks) are reported by subagents and beats; with a hash cereal checks the ledger and marks the event verified only if the validated result matches.

### p5.8 Plan preview — `GET /plan?goal=&envelope=`  ✅
The quote-based plan, read-only.

### p5.9 Accounting export — `GET /export.csv`, `GET /export.json`  ✅
One row per payment across wallets and rails: date, folder, wallet, deployment, task, rail, vendor, payee, amount, currency, result, who signed, tx hash, explorer link, private tag, item; totals by wallet, vendor, rail and folder.

**Verified on testnet Sat Oct 24:**
| Check | Evidence |
|---|---|
| Wallet from a sentence (d_a6336c: 1 RLUSD, 2 days, Vendor A and C, threshold 0.2, sweep) | 0.15 to C signed by subagent + cereal `3909FD18…`; 0.25 to A signed by subagent + owner's Ledger, no cereal `1FF73366…`; revoked B refused; done swept 0.6 home |
| Security log after `make beats` | stolen keys on the main wallet `tefBAD_SIGNATURE`; stolen-keys drain `tecPATH_PARTIAL` verified on-ledger `C121777E…`; hijack signing alone `tefBAD_QUORUM`; cereal refusals with revocation evidence; planner skips; the Ledger-approved large payment |
| `make vendor-test` (vendor lists and blacklisting, live) | 10 of 10 passed Oct 24: wallet d_afc96f "only at Vendor C" approved on the Ledger `EE0F08CE…`; paid C `1CCC66DF…`; trusted A refused `payee_not_allowed`; blacklisted B refused with revocation `3FF46EE4…`; a brand-new address refused (no credential); C blacklisted live `28808253…` and the next payment refused citing exactly that transaction; C restored (accept `FFA88004…`) and paid again `EFFB5F34…`; 0.30 swept home; every refusal sent nothing (subwallet Sequence unchanged) |
| `make acceptance` Part 5 (own service :8015 with Speculos, paywalls A :8020, B :8022, C :8023) | passed Oct 24 in 2 min 16 s: vendor list (A and C valid, B revoked with evidence); plan preview C 0.15 / A 0.25, B skipped, 0.50 of 2, nothing deployed; the HubSpot/Clearbit/Apollo sentence refused `card_problems`, nothing deployed; wallet from a sentence approved on the Ledger (threshold 0.2, A and C, folder Market Research); x402 0.15 from C signed subagent + cereal `5304BC47…`; x402 0.25 from A signed subagent + owner's Ledger and accepted by t54 `12A2EEB4…`; a second large payment rejected on the device, Sequence unchanged; hijack signing alone `tefBAD_QUORUM` in the security log; done swept 0.60 home; export rows and signers match; main wallet −0.40. Evidence JSON in `exports/` |

## Part 6 — submission (Sun 09:00 code lock → 12:00 submit)
Update `docs/DEMO-SCRIPT.md` to the main-agent/subagent story; README with the live URL first and the primitives table; `HACKATHON.md` (what was built after Sat 10:00 with commit links, what is mocked); 2–3 minute video; submission answers; opt into the bounties.

## Cut order if time runs short
Part 5 dashboard → AP4M (keep x402) → Verifiable Intent → Part 3 device funding (keep recovery signer). Never cut Part 1.
