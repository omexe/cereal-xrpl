# Cereal React screens

React + TypeScript + Vite implementation of Figma home screen `21:1489` and wallet activity screen `27:2273` in file `V9d93yNMx5PlVTnMN21aQ3`.

## Run

```sh
cd frontend
npm ci
npm run dev
```

To verify:

```sh
npm run build
npx playwright install chromium
npm test
```

## Behavior

- Home displays the total active demo balance and the original home illustration. Its composer opens wallet creation with the entered task description.
- Select a wallet in the sidebar to open its activity view: merchant spending bar, editable spending rules, and transaction history beside the original wallet illustration.
- The spending bar and its legend are calculated from that wallet's demo transactions. The header shows spending against the configured spending limit. Lowering the limit below existing spending displays an over-limit message; the chart remains contained.
- Every initial wallet, including archived wallets, has a task-specific description, mock balance, spending rules, and five or six sample transactions dated October 24, 2026. New wallets receive matching mock data based on their task name. Existing browser wallets are backfilled once: empty activity, missing descriptions, and zero balances receive fixtures; custom rules, nonzero balances, names, folder placement, and existing activity are preserved. A per-wallet marker prevents reseeding after subsequent edits. All activity is explicitly marked as a demo.
- Add funds changes the selected wallet's available demo balance, shown in the funding dialog. It does not create spending transactions. Home funding lets you select the receiving wallet.
- New Wallet creates a named demo wallet with an optional description and folder. Settings can archive, restore, or move the selected wallet. Dragging also moves wallets between folders and Disposable Wallets.
- Archived wallets retain their activity and can be restored; funding and policy edits are disabled while archived.
- Click a blue rule to edit it. The composer supports complete sentences in this explicit format (a deterministic parser, not an AI service):

  `Spend up to $20 over 2 days, only at HubSpot, Clearbit and Apollo. Ask me above $5. Sweep back when done.`

  `Keep funds when done.` is also supported. Unsupported instructions return feedback without changing the policy.
- Public demo state persists in localStorage under `cereal-demo-v1`. Original placeholder labels are refreshed without resetting user edits.
- Sidebar and main content scroll independently. The composer stays at the bottom of the viewport. The transaction list scrolls on desktop and expands in the mobile content flow.

Typography, colors, and layout rules live in [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md), with semantic tokens in `src/tokens.css`. Agentation is development-only.

## Integration boundary

This is a local frontend demo. Wallet creation, funding, rules, and activity do not call XRPL or payment providers. No Ledger device is connected. No seeds, keys, addresses, or credentials belong in browser state. Any future backend payment integration must remain XRPL testnet only.

## Assets

- `public/assets/home-organism.svg`: original 640 × 620 illustration from Figma `45:303`.
- `public/assets/wallet-activity-organism.svg`: original 356 × 406 illustration from Figma `27:2389`.
- Both illustrations are decorative; navigation uses the sidebar. The former procedural `WalletOrganism` component and its geometry remain as unused references from the preceding design.
- `public/assets/cereal.svg`: original Cereal brand mark.
- Interface icons use the official `@untitledui/icons` package.
- Aspekta 400 and 500 are local fonts with their OFL license included.

All runtime assets are local; there are no expiring Figma asset URLs.
