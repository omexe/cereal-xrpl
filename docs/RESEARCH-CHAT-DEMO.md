# Cereal research chat tool

The ChatGPT-style interface is available from **Settings → Developer tools → Open test chat** at `/test-chat`. It connects to the same live Cereal service as the wallet app. No special wallet type is required.

## Live wallet connection

1. Create a normal wallet in Cereal and set its budget, vendors, expiry, approval threshold, and completion rule.
2. Open test chat in Settings. The wallet list refreshes from `GET /subagents`, including newly created and renamed wallets. Only active, unarchived, unexpired wallets can be selected.
3. Name the wallet in your prompt, for example **“Get the agenda. Use my market sizing wallet.”** Quoted exact names work too. Unknown or duplicate names require explicit selection; the chat never falls back to a fixture or guesses a different wallet.
4. Submit sends the message and conversation history to `POST /research/chat`. The configured AI replies directly or selects a wallet and catalog items. Purchases then send `{task, request_id, keep_open: true}` to `POST /subagents/{id}/run`. The prompt cannot edit budgets or permissions.
5. Run status and wallet activity refresh from the backend. Only validated successful transactions are shown as settled. View the normal wallet screen for rules and full activity. Approvals use the backend’s configured Ledger flow. A chat response keeps the wallet open; finishing the wallet in Cereal applies its completion rule.

**Submitting a purchase request can spend XRPL testnet RLUSD.** AI powers the demo chat; general web browsing and arbitrary XRPL research reports are not connected. The vendor catalog offers agenda, speaker, market-data, and XRPL research resources. The research resources are clearly labeled fictional sample reports. For example: “Research market data from Vendor A. Use my market sizing wallet.” Unsupported requests and policy refusals appear as assistant messages after your sent prompt. The full scripted XRPL research presentation remains available in the offline fixture chat below.

Retrying an unchanged request after a lost response reuses a persisted request ID. Reloads only read existing runs; they do not submit a new task. Wallet data is never copied into browser fixture storage. Backend failures stay visible, with no mock fallback. In live mode `/demo-chat` also opens this connected client.

## Test wallets from JSON

For the scripted simulation, expand **Settings → Developer tools → Offline fixtures**. Open test wallets at `/test-wallets` and fixture chat at `/fixture-chat`. These need neither the backend nor a Ledger emulator.

`frontend/src/fixtures/deployment.json` supplies four ordinary simulation wallets on first use:

| Wallet | Budget | Approval above | Allowed sources |
| --- | ---: | ---: | --- |
| XRP research | $20 | $5 | Ledger Lens, Venture Atlas, Open Ledger Index |
| Review every payment | $20 | $0 | All three trusted research sources |
| Small budget | $3 | $5 | All three trusted research sources |
| Restricted sources | $20 | $5 | Ledger Lens only |

All start with zero spending, keep remaining funds, and have a two-day window starting on first use. They share the regular wallet layout and controls. Token Insider is blocked by the scripted fraud signal regardless of wallet policy. Name any wallet in the prompt to test its rules.

Changes persist in browser localStorage under `cereal-test-v1`; reloads preserve balances, history, and the original start time. The fixture initializes a new sandbox only; editing the JSON does not overwrite an existing browser session. The fixture chat has its own session-history key. The existing mock workspace (`cereal-demo-v1`) and live backend remain separate. No simulated records are written into the backend's `deployments.json`, and sandbox routes never call payment APIs.

To verify the default live frontend's Settings links, JSON initialization, persistence, approvals, and separation without a backend: `cd frontend && npm run test:sandbox`.

## Run and present the offline simulation

```sh
cd frontend
npm ci
npm run dev:mock
```

The original `/demo-chat` simulation is available in mock mode. Explicit `/fixture-chat` and `/test-wallets` routes also provide it in the live frontend. `/test-chat` always connects to the backend. The Vite URL defaults to `http://127.0.0.1:5180`. To retain browser data from the earlier demo on port 5173, start with `npm run dev:mock -- --port 5173` if that port is free.

1. Open Cereal at the Vite URL. Select any normal wallet. Configure its budget, allowed merchants, approval threshold, and completion policy with the existing controls.
2. Open **Settings → Developer tools → Open demo chat**.
3. Enter a prompt such as: **“Research XRPL products, docs, founders, and funding. Use my Apollo Research wallet for payments.”** Chat resolves the exact wallet name without changing its rules. Names are case-insensitive. Quoted names are supported, including `Use wallet named "Apollo Research"`.
4. Chat visits two scripted public sources without accessing the wallet, then sends payment requests for the sources below.
5. In Cereal, watch the existing wallet’s **Activity / Transactions** list. The illustration, budget bar, spending rules, and prior transactions retain their normal layout. Pending requests appear first with **Approve** and **Deny payment** actions. Paid, blocked, and denied outcomes remain in the same activity list.
6. Chat resumes after either decision and produces a coverage brief based on the sources it could access.
7. To replay, open **Settings → Developer tools → Demo scenario & replay**, choose the wallet, and select **Reset research session → Confirm reset**. This stops/removes that wallet’s research sessions, reverses their simulated payment deductions and returned funds, and removes only their transaction records. It preserves existing transactions, unrelated funding, wallet rules, creation time, and other wallets. An expired wallet is not renewed by resetting a session.

Both screens must use the same browser profile and origin (scheme, hostname, port). `localhost` and `127.0.0.1` do not share storage. For a presentation without development tooling, run `VITE_CEREAL_MODE=mock npm run build` then `npm run preview` and use that preview URL for both screens.

## Source sequence and policy

| Source | Cost | Result |
| --- | ---: | --- |
| XRPL documentation | Free | Public-source step; no payment request |
| XRPL overview | Free | Public-source step; no payment request |
| Ledger Lens | $1.20 | Evaluated against the selected wallet’s rules |
| Token Insider | $0.80 | Always blocked by the fictional revoked-credential signal |
| Venture Atlas | $7.50 | Evaluated against the selected wallet’s rules |
| Open Ledger Index | $0.65 | Evaluated against the selected wallet’s rules |

For the allow/block/approval presentation, configure a normal wallet to allow Ledger Lens, Venture Atlas, and Open Ledger Index, with at least $9.35 of remaining budget and available balance, and a $5 approval threshold. This is an owner action in Cereal, never something chat does automatically. Existing spending counts against the limit. A wallet restricted to HubSpot, Clearbit, and Apollo will block the fictional research merchants.

Approving the premium report adds **$9.35** of spending across the run; denying it adds **$1.85**, assuming the other requests pass policy. Existing transactions remain in the spending total. If the wallet’s existing “sweep back when done” rule is enabled, the simulation returns its remaining balance and closes it on completion. Stopping a run cancels pending requests without sweeping or undoing completed payments.

Missing or unknown wallet names produce a clarification before any run or request is created. Duplicate names require an explicit choice, showing folder, balance, and an ID suffix for distinction. Chat never silently falls back to the first wallet. Archived, expired, or closed wallets cannot start new research.

## Persistence and compatibility

- The owner’s merchant restrictions, budget, balance, duration, and archival/closure state apply to every payment, including an approval recheck. Approval cannot bypass a hard constraint.
- The demo catalog supplies prices and risk signals; prompts cannot override them.
- Web Locks serialize updates to the shared `cereal-demo-v1` document. Storage events update both screens. Durable cursors and request IDs prevent duplicate charging across windows, approvals, and reloads.
- Either open screen advances active runs. Closing all screens pauses progress until reopening. Pending decisions persist, and chat history reopens previous sessions.
- Storage failures do not commit partial payments. The UI reports the error for retry.
- Previously created research wallets are retained as ordinary wallets, preserving their balances, rules, history, and sessions. The obsolete type marker is removed. The old `/?setup=research` link opens Settings instead of creating a special wallet.
- Older ordinary wallets had no creation timestamp. Migration assigns one once and persists it to establish their duration; existing timestamps are preserved.

## Offline integration boundary

The offline fixture chat is a deterministic local UI simulation. It calls no model, fetches no websites, and moves no real or testnet funds. Paid sources use reserved `.example` domains. Content and risk signals are fictional; public URLs are illustrative references. The final result is a coverage brief, not verified founders or fundraising research. The ChatGPT-style screen retains its Demo badge, and Cereal explains simulation mode in Settings.

The browser implementation is not a security boundary against someone controlling browser state. A real integration must use server-side authorization, authenticated approvals, catalog verification, idempotency, and validated XRPL testnet settlement. The offline fixture chat does not connect to the Python service; `/test-chat` uses the live connection described above. No secrets are required.

## Verification

```sh
cd frontend
npm run build
npm test -- --workers=3
npm run test:sandbox
```

Tests cover exact wallet-name resolution, missing/duplicate names, ordinary-wallet compatibility, legacy migration, Settings-only tooling, preserved history, multi-window approval and denial, refreshed sessions, policy rechecks, reset isolation, storage failures, mobile layout, and existing wallet behavior.

## Research data and conversational outcomes

A resolved wallet request appears immediately as a sent chat message; the composer clears while Cereal checks the request. Refusals appear as ordinary assistant replies, with distinct explanations for an unavailable resource, disallowed vendor, failed trust checks, or insufficient budget. Sent messages and replies survive a tab reload. Unknown connection outcomes offer an explicit retry that retains the request ID.

`market-data` and `xrpl-research` are sample documents served behind the existing testnet x402 paywall. Successful deliveries are captured as public document fields in the run and displayed under Retrieved data. This content is separate from validated payment status. Sample company counts, founders, and funding figures are fictional; these endpoints do not proxy HubSpot or Crunchbase. Named Vendor A/B/C requests narrow the selected wallet’s existing allowlist; they cannot grant a new permission.

## Continuing a conversation

After a task completes, the composer stays editable. Follow-up requests reuse the selected wallet unless they explicitly name another; an unknown explicit name never falls back to the old wallet. Each new message gets a new request ID, while uncertain retries retain their original ID. Previous results and retrieved documents remain in the conversation after another task or a reload. You can ask questions during a running task. Cereal still permits only one payment run per wallet at a time.

Live chat runs use `keep_open=true`: completing one response does not finish the wallet. The owner finishes the wallet in Cereal, where its existing return-funds rule applies. Expiry remains enforced. Previously reclaimed wallets remain closed; the chat can explain their status or summarize existing results, but cannot fund or reopen them.

## AI conversation

`POST /research/chat` interprets every live chat message using the configured server-side model. It receives bounded conversation history plus whitelisted wallet and catalog metadata and retrieved sample documents. It returns either a conversational reply or a validated wallet/item selection. No secrets or signing tools are given to the model. General questions, unavailable sources, and summaries need no active wallet and start no payment. Model failures produce a conversational failure with no grammar fallback.

Research selections become canonical catalog requests through the existing run endpoint. The frontend preserves the original prompt and saves the interpreted purchase and request ID before dispatch, so uncertain retries do not reinterpret or duplicate payments. Catalog prices, credentials, budgets, allowlists, expiry and device approvals remain enforced by Cereal. This adds AI understanding, not live web browsing; sample reports are still labeled.

New chat requests can purchase a previously settled resource again, with a fresh request ID and a fresh budget check. An unresolved earlier payment blocks repeat payment until its outcome is known. A zero balance returns a normal out-of-funds assistant reply; discussion and later messages remain available.
