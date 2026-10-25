# Cereal React screens

React + TypeScript + Vite implementation of Figma home screen `21:1489` and wallet activity screen `27:2273` in file `V9d93yNMx5PlVTnMN21aQ3`.

## Run

```sh
cd frontend
npm ci
npm run dev        # live: http://127.0.0.1:5180, data from the cereal service (CEREAL_API, default :8001)
npm run dev:mock   # mock: local wallet data; AI rule edits use the service
```

Live mode is the default. Start the service first (`make service` in the repo root); Vite proxies `/api` to it, so the
browser never holds a credential and no CORS setup is needed. Port 5180 keeps clear of the read-only `web/` dashboard
on 5173. Live mode never seeds balances or activity; a connection failure shows a banner and retries every 5 seconds.

To verify:

```sh
npm run build
npx playwright install chromium
npm test            # the mock suite
npm run test:live   # live specs (tests/live-*.spec.ts) against XRPL testnet; see playwright.live.config.ts
```

## Research chat tool

In the default live app, open **Settings → Developer tools → Open test chat**. `/test-chat` reads active wallets from the backend and submits tasks to Cereal’s existing runner. Name an existing wallet in the prompt, for example “Get the agenda. Use my market sizing wallet.” Names are resolved against a fresh backend list; missing or ambiguous names require selection. Budget, vendor, expiry, approval, and completion rules stay in Cereal. Run state, payment evidence, and balances come from the backend; uncertain request retries reuse the same ID.

The assistant UI is simulated, but submitting can spend **testnet RLUSD**. General browsing is not connected; tasks use the connected vendor catalog. Market-data and XRPL research reports are labeled fictional sample data. Refusals appear in the conversation after the sent message; unsupported requests never get a fabricated success.

**Settings → Developer tools → Offline fixtures** opens `/test-wallets` and `/fixture-chat`. Four wallets from `src/fixtures/deployment.json` initialize this isolated, entirely simulated workspace under `cereal-test-v1`. It does not call payment APIs or modify backend records. `npm run dev:mock` also retains the original simulation at `/demo-chat`; in live mode that route opens the connected chat instead.

Run `npm run test:sandbox` to verify live chat against intercepted backend responses and offline fixture isolation without spending funds. See [the walkthrough](../docs/RESEARCH-CHAT-DEMO.md) for both flows.

## Mock-mode behavior

- Home displays the total active demo balance and the original home illustration. Its composer opens wallet creation with the entered task description.
- Select a wallet in the sidebar to open its activity view: merchant spending bar, editable spending rules, and transaction history beside the original wallet illustration.
- The spending bar and its legend are calculated from that wallet's demo transactions. The header shows spending against the configured spending limit. Lowering the limit below existing spending displays an over-limit message; the chart remains contained.
- Every initial wallet, including archived wallets, has a task-specific description, mock balance, spending rules, and five or six sample transactions dated October 24, 2026. New wallets receive matching mock data based on their task name. All wallets use the same layout and can be named in the research prompt. Existing browser wallets are backfilled once: empty activity, missing descriptions, and zero balances receive fixtures; custom rules, nonzero balances, names, folder placement, and existing activity are preserved. A per-wallet marker prevents reseeding after subsequent edits. Simulation mode is explained in Settings; the wallet list is labelled Activity.
- Add funds changes the selected wallet's available demo balance, shown in the funding dialog. It does not create spending transactions. Home funding lets you select the receiving wallet.
- New Wallet creates a named demo wallet with an optional description and folder. Settings can archive, restore, or move the selected wallet. Dragging also moves wallets between folders and Disposable Wallets.
- Archived wallets retain their activity and can be restored; funding and policy edits are disabled while archived.
- Click a blue rule or use the wallet composer to describe an edit. AI receives the current rules and interprets partial requests such as “Halve my approval threshold and keep the leftovers.” Review the proposal before saving. Untouched rules stay unchanged; ambiguous requests or model failures leave the policy unchanged. “Edit the fields instead” remains available.
- AI editing in both live and mock mode requires the cereal service with `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` configured server-side and `CEREAL_LLM` enabled. There is no parser fallback. Mock proposals use `/demo/rules/preview`; saving still only updates local browser data. Live previews return `resolved_change`, which Apply validates again without another model call. Live ledger, budget, vendor, and company controls still apply.
- Public demo state persists in localStorage under `cereal-demo-v1`. Original placeholder labels are refreshed without resetting user edits.
- Sidebar and main content scroll independently. The composer stays at the bottom of the viewport. The transaction list scrolls on desktop and expands in the mobile content flow.

Typography, colors, and layout rules live in [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md), with semantic tokens in `src/tokens.css`. Agentation is development-only.

## Integration boundary

In live mode (`src/api.ts`, `src/live.ts`, `src/store.ts`) every number comes from the cereal service on XRPL
testnet and amounts are RLUSD decimal strings. The rest of this section describes mock mode.

This is a local frontend demo. Wallet creation, funding, rules, and activity do not call XRPL or payment providers. No Ledger device is connected. No seeds, keys, addresses, or credentials belong in browser state. Any future backend payment integration must remain XRPL testnet only.

## Assets

- `public/assets/home-organism.svg`: original 640 × 620 illustration from Figma `45:303`.
- `public/assets/wallet-activity-organism.svg`: original 356 × 406 illustration from Figma `27:2389`.
- Both illustrations are decorative; navigation uses the sidebar. The former procedural `WalletOrganism` component and its geometry remain as unused references from the preceding design.
- `public/assets/cereal.svg`: original Cereal brand mark.
- Interface icons use the official `@untitledui/icons` package.
- Aspekta 400 and 500 are local fonts with their OFL license included.

All runtime assets are local; there are no expiring Figma asset URLs.
