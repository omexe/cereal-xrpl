# Cereal research chat tool

The separate ChatGPT-style tool at `/demo-chat` submits simulated payment requests to an **existing Cereal wallet named in the chat prompt**. There is no special wallet type, creation checkbox, or separate wallet layout. Launch and replay controls live under **Settings → Developer tools**.

## Run and present

```sh
cd frontend
npm ci
npm run dev:mock
```

The research tool is available only in mock mode; the default live frontend uses the testnet service and does not load or advance simulated wallets. The Vite URL defaults to `http://127.0.0.1:5180`. To retain browser data from the earlier demo on port 5173, start with `npm run dev:mock -- --port 5173` if that port is free.

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

## Integration boundary

This is a deterministic local UI simulation. It calls no model, fetches no websites, and moves no real or testnet funds. Paid sources use reserved `.example` domains. Content and risk signals are fictional; public URLs are illustrative references. The final result is a coverage brief, not verified founders or fundraising research. The ChatGPT-style screen retains its Demo badge, and Cereal explains simulation mode in Settings.

The browser implementation is not a security boundary against someone controlling browser state. A real integration must use server-side authorization, authenticated approvals, catalog verification, idempotency, and validated XRPL testnet settlement. The existing Python service is not connected by this tool. No secrets are required.

## Verification

```sh
cd frontend
npm run build
npm test -- --workers=3
```

Tests cover exact wallet-name resolution, missing/duplicate names, ordinary-wallet compatibility, legacy migration, Settings-only tooling, preserved history, multi-window approval and denial, refreshed sessions, policy rechecks, reset isolation, storage failures, mobile layout, and existing wallet behavior.
