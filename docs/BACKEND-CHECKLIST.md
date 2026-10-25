# Backend completion checklist

Created October 24, 2026 · Shared working checklist for the backend and React app integration.

Scope: native XRPL testnet only (`xrpl:1`). The React app in `frontend/` currently uses mock data. The separate `web/` dashboard reads backend data but does not allow writes.

## How we update this file

- Keep task IDs stable so we can refer to them in chat and commits.
- Before starting a task, add `Owner: <name>` and `Status: in progress` to its line. Unclaimed tasks are available.
- Check a task only when its completion criteria pass. Append the relevant test, commit, or evidence reference and completion date.
- If blocked, leave it unchecked and add `Blocked: <specific dependency>`.
- Edit the relevant task rather than rewriting the file; reread it before saving to preserve concurrent changes.
- Keep credentials, wallet seeds, endpoint tokens, and private environment values out of this file.

## Existing baseline — implementation present

These checkmarks reflect implementation and recorded acceptance in [BUILD-ORDER.md](BUILD-ORDER.md), not a fresh test run on this checkout.

- [x] B01 — Subwallet creation, locking, initial funding, reclaim, and retirement.
- [x] B02 — Co-signing policy, vendor credentials and revocation, expiration, and payment refusal records.
- [x] B03 — Speculos funding approval, approval above a payment threshold, and owner-only recovery.
- [x] B04 — Native XRPL x402 purchases through t54, with settlement and delivery handling.
- [x] B05 — CLI main-agent/subagent orchestration, quote-based planning, and optional Claude integration.
- [x] B06 — Wallet preview/create APIs, vendor directory, security events, and CSV/JSON export.
- [x] B07 — Separate read-only dashboard in `web/` connected to backend endpoints.

## 1. Establish a working local backend

- [x] S01 — Install the Python environment and backend dependencies. Owner: Codex · Completed 2026-10-24. Created gitignored `.venv` with Python 3.12.0 and installed `requirements.txt`; dependency/import checks pass and the service OpenAPI schema generates successfully (21 paths). See evidence below.
- [ ] S02 — Verify local testnet configuration without exposing secrets. **Done when:** required roles, testnet RPC, issuer, caps, vendor endpoints, and chosen signing mode are configured and documented by variable name only.
- [x] S03 — Run the offline backend suite and record the result. Owner: Codex · Completed 2026-10-24 during S01 verification. All 84 offline tests pass with `.env` loading disabled. Fixed a test that loaded a real treasury key and excluded live-test modules before import unless explicitly opted in. Live acceptance remains unrun.
- [x] S04 — Document service startup and distinct UI ports. Completed 2026-10-24 (b5bb6ae): React app on :5180 (`npm run dev`, live) proxying `/api` to `CEREAL_API` (default :8001); `web/` keeps :5173; mock suite on :5179; live e2e on 81NN/52NN. See `frontend/README.md`.

## 2. Define and connect the application contract

- [x] I01 — Define the live UI data contract. Completed 2026-10-24 (b5bb6ae): `frontend/src/live.ts` `LiveInfo` (available, budget, spent = validated only, pending, returned, approval) as decimal strings; `formatAmount` labels RLUSD; treasury from `GET /main`.
- [x] I02 — Add a React API client and explicit mock/live mode. Completed 2026-10-24 (b5bb6ae): `src/api.ts`, `VITE_CEREAL_MODE=live|mock` (`src/mode.ts`), Vite `/api` proxy; live never loads the mock workspace; loading/failure banner; refusals throw `ApiError('refused')`. Evidence: `tests/live-smoke.spec.ts` passed against :8001; mock suite 8/8.
- [x] I03 — Wire Home and the wallet list. Completed 2026-10-24 (b5bb6ae): Home shows the main wallet's RLUSD and active count from `GET /main`; the sidebar lists `GET /subagents` with names, folders and lifecycle (finished wallets dimmed). Evidence: `tests/live-smoke.spec.ts`.
- [ ] I04 — Owner: worker unit 1 · Status: in progress. Wire wallet details and transactions. **Done when:** `GET /subagents/{id}` populates rules, payment records, merchant totals, approval/refusal evidence, and explorer links; pending/unknown results are not shown as settled.
- [ ] I05 — Owner: worker unit 2 · Status: in progress. Wire preview and wallet creation. **Done when:** `POST /wallets/preview` produces a reviewable card, confirmation calls `POST /wallets`, and approval, rejection, timeout, and creation progress are handled without duplicate wallets.
- [ ] I06 — Owner: worker unit 6 · Status: in progress. Replace mock vendor assumptions in live mode. **Done when:** merchant choices resolve through `GET /vendors`; unknown or revoked vendors are rejected clearly, and the UI respects backend caps. HubSpot/Clearbit/Apollo remain mock labels unless actually registered.
- [ ] I07 — Owner: worker unit 6 · Status: in progress. Wire security events and exports. **Done when:** `GET /events`, `/export.csv`, and `/export.json` are accessible from the React app and match backend records.

## 3. Complete missing backend operations

- [ ] A01 — Owner: worker unit 7 · Status: in progress. Expose agent execution through the API. **Done when:** a created wallet can start its task without a separate CLI invocation, returns a run ID/status, and records completion or failure. Wallet creation alone must not imply execution has started.
- [ ] A02 — Owner: worker unit 7 · Status: in progress. Track and recover agent runs. **Done when:** duplicate starts are prevented, process failure/timeouts are recorded, and interrupted runs can be reconciled after restart with a defined cleanup policy.
- [ ] A03 — Owner: worker unit 3 · Status: in progress. Define and implement editing existing spending rules. **Done when:** mutable fields, owner approval requirements, and effects on already-signed payments are explicit; the server validates and persists changes. Raising a displayed limit must not falsely imply more on-ledger funds.
- [ ] A04 — Owner: worker unit 4 · Status: in progress. Add owner-approved funding for an existing wallet. **Done when:** an explicit human action produces a bounded approval and validated funding result; budget accounting, caps, and any required trust-line changes remain consistent. No automatic top-ups.
- [ ] A05 — Owner: worker unit 5 · Status: in progress. Add wallet metadata and folder operations. **Done when:** rename, folder creation, and moving wallets persist through the API and survive reloads; metadata changes cannot alter payment policy accidentally.
- [ ] A06 — Owner: worker unit 5 · Status: in progress. Define archive/restore versus reclaim/retire. **Done when:** presentation-only archiving is distinguished from moving funds or deleting an account; a retired account cannot be “restored” by flipping a UI flag.
- [ ] A07 — Owner: worker unit 7 · Status: in progress. Connect completion and cleanup to the UI. **Done when:** done/sweep, reclaim, and retirement progress are visible; too-young accounts remain tracked for later retirement, and failed cleanup can be reconciled safely.

## 4. Close correctness and service-safety gaps

- [ ] R01 — Owner: worker unit 8 · Status: in progress. Enforce the configured issuer in the co-signer. **Done when:** a payment with the correct currency code but a different issuer is refused before signing, with a focused regression test.
- [ ] R02 — Owner: worker unit 8 · Status: in progress. Make cap checks and deployment reservation atomic. **Done when:** concurrent requests cannot both pass stale outstanding-budget or active-wallet limits. The current cap check happens before the main-wallet lock.
- [ ] R03 — Owner: worker unit 2+8 · Status: in progress. Add idempotency to operations that move funds or create wallets. **Done when:** a repeated request returns the original operation/result instead of creating a second payment or deployment.
- [ ] R04 — Owner: worker unit 8 · Status: in progress. Make state persistence resilient. **Done when:** writes are atomic and concurrency-safe for the chosen deployment model, partial operations survive crashes, and payment/event updates cannot overwrite each other. Current storage is local JSON with process-local locks.
- [ ] R05 — Add caller authentication and operation authorization before exposing writes beyond trusted local use. **Done when:** wallet ownership, agent scope, and administrative vendor actions are checked server-side; unauthorized callers cannot deploy, reclaim, co-sign, or revoke credentials.
- [ ] R06 — Align Claude and scripted execution paths. **Done when:** selecting x402 preserves that purchase flow when Claude is enabled; execution flags and approved vendor/price bounds reach the subagent in both paths.
- [ ] R07 — Owner: worker unit 2 · Status: in progress. Bind creation approval to the reviewed wallet card. **Done when:** changes between preview and creation, including a different parser result or vendor state, require renewed confirmation rather than silently creating a different policy.
- [ ] R08 — Verify interruption and ambiguous-payment recovery. **Done when:** submit timeouts, facilitator uncertainty, and restart during payment preserve the original hash and unknown state until reconciled; tests prove no replacement payment is sent prematurely.

## 5. Verify the connected demo

- [ ] V01 — Add frontend/backend integration coverage. **Done when:** create, select, edit supported rules, fund, execute, inspect activity, and cleanup work against the API with explicit refusal/error cases.
- [ ] V02 — Run a controlled native XRPL testnet end-to-end flow. **Done when:** wallet creation → approval → task execution → validated payment → activity → reclaim → export reconcile, with evidence recorded. Live acceptance can spend testnet funds; keep it separate from offline tests.
- [ ] V03 — Verify refusal and approval scenarios through the UI. **Done when:** revoked/off-list vendor, over-budget payment, expired wallet, missing device, and owner rejection produce accurate states without an unintended payment.
- [ ] V04 — Reconcile the UI with exports and ledger evidence. **Done when:** balances, merchant totals, paid-but-undelivered resources, refunds/returns, and failed transactions are represented consistently.
- [ ] V05 — Update demo and submission documentation. **Done when:** the demo script matches the connected app; README, HACKATHON.md, video, and submission answers identify what is live, mocked, optional, or disabled. Part 6 remains open in BUILD-ORDER.md.

## Optional integrations — outside the core completion path

- [ ] O01 — Physical Ledger transport. **Done when:** an actual supported device transport is wired and approval/rejection/recovery are tested. Current signer code configures Speculos transport.
- [ ] O02 — Mastercard Verifiable Intent. **Done when:** the required contracts/access are verified and an intent chain is attached and validated end to end. Currently not implemented.
- [ ] O03 — Re-enable and reverify AP4M only if selected for the demo. **Done when:** its separate XRPL EVM flow and accounting pass acceptance. Implemented previously, disabled by default; do not describe it as native XRPL.
- [ ] O04 — AWS Strands/AgentCore hosting. **Done when:** deployed execution, scoped identity/tools, and the local signing boundary are verified. Currently not wired.
- [ ] O05 — QuickNode event ingestion. **Done when:** webhook/subscription authentication, replay protection, deduplication, recovery, and validated-outcome reconciliation are implemented. Configurable RPC support already exists.

## Evidence log

Append completed verification here, using task IDs. Do not record an old acceptance result as a new run.

| Date | Task IDs | Result / test command | Commit or evidence |
|---|---|---|---|
| 2026-10-24 | Baseline review | Read-only code review; no new backend acceptance run. Local backend dependencies were unavailable. | Existing acceptance: `docs/BUILD-ORDER.md` |
| 2026-10-24 | S01 | `.venv/bin/python -m pip install -r requirements.txt`; `.venv/bin/python -m pip check` → no broken requirements. Imported all eight direct dependencies plus service/main-agent/subagent; generated OpenAPI for 21 paths. | Local `.venv` (gitignored); no backend configuration changes. |
| 2026-10-24 | S01, S03 | `PYTHON_DOTENV_DISABLED=1 CEREAL_RUN_TESTNET=0 make test` → **73 passed in 0.52s**. | `tests/conftest.py`, `tests/test_part3.py`. |
| 2026-10-24 | S03 | Isolated collection smoke checks: default excludes a synthetic live-test module; `--run-testnet` and `CEREAL_RUN_TESTNET=1` both include it. Collection only; no live tests executed. | Temporary test harness; no payment or ledger calls. |
| 2026-10-24 | S03 | After integrating upstream chat, sweeper, and LLM changes: `PYTHON_DOTENV_DISABLED=1 CEREAL_RUN_TESTNET=0 make test` → **84 passed in 0.56s**. | Includes upstream `5bf6216`; no live tests executed. |
| 2026-10-24 | S04, I01–I03 | `npm run build`; `npm test` → 8 passed (mock); `CEREAL_API=http://127.0.0.1:8001 npx playwright test -c playwright.live.config.ts tests/live-smoke.spec.ts` → 1 passed (live, read-only). Treasury topped up 10 RLUSD from Vendor A for live e2e. | b5bb6ae, b34caff; https://testnet.xrpl.org/transactions/024B65BE79AAABCF6D72F106F1C02595396B12ECA06E68263B7522C6BAEE168C |

### Installed environment for S01

Python 3.12.0; xrpl-py 5.2.0; x402-xrpl 0.3.4; FastAPI 0.115.14; Uvicorn 0.30.6; requests 2.34.2; python-dotenv 1.2.4; pytest 9.1.1; anthropic 2.3.0. These are the installed versions, not a new dependency lockfile; `requirements.txt` remains unchanged.

Use `.venv/bin/python` directly or activate with `source .venv/bin/activate`. The offline command above does not require wallet credentials. S02 (live configuration) and S04 (startup/ports) remain open; passing these tests does not establish live service or payment readiness.
