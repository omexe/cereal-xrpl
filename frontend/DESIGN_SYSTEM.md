# Cereal visual hierarchy

`src/tokens.css` is the only source of typography and color values. These rules apply to application UI; third-party development tools retain their own styling.

## Typography

| Role | Size / line height | Weight | Usage |
| --- | --- | --- | --- |
| Caption | 12px / 18px | 400 | Sidebar navigation, folders, wallet rows, chart legends, helper text, status |
| Label | 12px / 18px | 500 | Section headings and form labels |
| UI | 13px / 19.5px | 400 | Budget and balance caption |
| Control | 13px / 19.5px | 500 | Buttons |
| Body | 14px / 21px | 400 | Question input, dialog descriptions and inputs |
| Brand | 12px / 18px | 500 | Cereal wordmark |
| Title | 20px / 25px | 500 | Dialog titles |
| Policy | 24px / 31.2px | 500 | Wallet constraints and empty-state heading |
| Display | 48px / 50.4px | 500 | Selected wallet balance only |

- Aspekta is the family for all application typography, with local 400 and 500 weights.
- Use `font: var(--font-role)`; do not declare per-component pixel sizes or weights.
- Only Display changes on mobile: 40px / 42px. All other roles retain their scale.
- Only Display and Policy use negative tracking, through their tracking tokens.
- Use weight 400 for reading and 500 for labels, controls, and headings. Do not add 600/700 or synthetic bold.
- Hierarchy comes from role, spacing, and color. Never enlarge navigation or helper text to compete with content.

## Color

| Role | Value | Usage |
| --- | --- | --- |
| Primary text | `#20232b` | Main content, wallet amounts, navigation |
| Secondary text | `#525866` | Descriptions, supporting captions, legends |
| Muted text | `#6b7280` | Section labels, placeholders, archived items, budget limit |
| Accent | `#2b33d8` | Actions, editable links, active wallet markers, selected cluster, focus |
| Accent soft | `#d3d6f7` | Unselected clusters and accent borders |
| Surface | `#ffffff` | Main canvas, composer, dialogs |
| Subtle surface | `#f8f8fa` | Sidebar, question field, unused budget track |
| Hover surface | `#eeeef3` | Navigation and wallet-row hover |
| Border | `#e3e5eb` | Dividers and neutral control borders |
| Error | `#a32626` | Error messages only |

- Components must use semantic color variables. No literal hex, RGB, or named colors in component styles or JSX, except `transparent` and `currentColor`.
- Blue denotes interaction or wallet state. Static headings and monetary values use Primary text.
- Filled accent buttons use the on-accent white token. Muted text must remain readable; do not mute text with opacity.
- Chart colors are categorical data colors, reserved for charts and matching legends. They are not text hierarchy colors.
- The wallet visualization uses `--color-organism-soft` (`#d3d1ff`) and `--color-organism-selected` (`#332bff`) for the lavender and vivid blue dots from Figma frame `45:307`. These illustration roles are separate from UI text and controls. Data-driven spheres use a regular hexagonal lattice with detached silhouettes; reference SVG exports are not used at runtime.

## Layout invariants

- The shell occupies `100dvh`. The page itself never scrolls.
- The sidebar fills its column vertically and scrolls independently when necessary.
- Main content scrolls above the composer. The composer stays at the viewport bottom with a 24px desktop / 12px mobile inset, respecting the safe area.
- Short desktop windows use tighter spacing and a smaller graphic; they do not invent another type scale.
- Overflowing content must remain reachable without covering the question input.

## Motion

- Page changes (sidebar, sphere map, brand, Home, a newly created wallet) are view transitions through `navigate` in `App.tsx`: the old page fades out (`--motion-fade-out`, .2s), then the new page fades in (`--motion-fade-in`, .3s, starting after `--motion-fade-delay`, .14s). Nothing slides. The sidebar and composer crossfade in place. The sphere map is its own layer, so between wallets it holds steady; it fades with the page when coming from or going to Home. Clicks pass through while a transition runs.
- Dialogs and the mobile drawer fade in with `--motion-fade-in`; closing is immediate.
- `prefers-reduced-motion: reduce` removes every animation and transition, and `navigate` skips the view transition. Browsers without view transitions change pages instantly.

## Agentation

Agentation mounts at the React root only when `import.meta.env.DEV` is true. The endpoint is `http://localhost:4747`, matching the existing local MCP server. Open its bottom-right toolbar to annotate the UI, then ask the agent to read your feedback. It is a desktop development tool and is excluded from production.

## Sidebar and icons

- Every sidebar text role is 12px / 18px, including the brand, navigation, folders, section headings, wallet names, and empty-state action. Use Caption for regular text and Label / Brand for medium weight; hierarchy comes from spacing, weight, and color.
- Use only Untitled UI interface icons, at a consistent 1.75 stroke width.
- Inline icons (all sidebar navigation, folders, chevrons, and add-folder) use `--icon-inline`: 16px.
- Standalone controls (dialog close) use `--icon-control`: 18px.
- Prominent controls (composer send and mobile menu) use `--icon-prominent`: 20px. The original brand mark is also 20px.
- Glyph size is independent of hit area: standalone controls are 32px, the compact add-folder target is 28px, and the mobile menu target is 44px. Navigation rows remain at least 36px high.

## Home overview

- Home uses the Overview role (`--font-overview`, Aspekta 500, 72px / 1.05, tracking -2.16px; 40px on mobile) for the total balance and Composer (`--font-composer`, 18px / 1.5, 500; Body on mobile) for wallet creation.
- Active wallet markers on Home use `--color-marker-active` (#4ac900), matching frame `21:1489`; archived markers retain their neutral token.
- Home shows the same interactive sphere map as wallet detail (described below), in a 640 × 620 frame matching `45:303` (`HOME_VIEW`). On Home the core is the selected sphere; every other sphere opens its wallet.
- The home summary sits above the illustration, with no budget chart or selected-wallet constraints. The composer remains at the viewport bottom, without a decorative caret.

## Forming a new wallet

- There is no New Wallet navigation item: a wallet is written in the Home composer. Typing on Home turns the workspace (everything right of the sidebar, composer included) to `--color-forming-surface` and shows the wallet forming (`FormingWallet`); clearing the text, Cancel or Escape returns to Home. Both directions are view transitions: the page fades, and the sphere map glides from Home's position to the left as it recolors.
- Colors come only from the `--color-forming-*` tokens: on-accent text, a muted on-accent for hints and the composer placeholder, a translucent on-accent border, and `--color-forming-sphere` (lavender) for other wallets, with the core in `--color-forming-particle` (white).
- The new wallet's sphere forms where the wallet will land (`placeSphere`): sparse lattice dots that hover and twinkle, drawn larger while forming and denser as the sentence names the wallet, budget, duration and vendors. Reduced motion draws it still.
- The right column reads the sentence back as it is typed (`lib/draftWallet.ts`): Cancel and Create wallet (Control), the budget in Overview, a Caption with the name and funding source, and the rules in Rules type with a blinking caret. The rules update clause by clause exactly as typed, with no defaults or placeholders. Until the sentence states a budget, a time limit and vendors, a muted Caption lists what is still needed and Create is disabled. A wallet that never mentions sweeping sweeps back (cereal's default), and one that never mentions approval is never asked about.
- Mock: Create wallet (or Enter) creates the demo wallet from the draft, funded with its budget, and opens it. Live: it opens the New wallet dialog with the sentence, where cereal reads it and the owner approves on the Ledger; the blue view is a draft.

## Wallet activity

- Frame `27:2273` replaces the earlier balance-and-spheres detail layout. Rules span the content width above a two-column transaction history and illustration. The wallet description and a "Spending rules" heading are not shown; an archived wallet shows an "Archived wallet" label instead.
- Transactions sit left of the illustration and start collapsed to a "Transactions" toggle (Control, with an inline chevron) and its summary caption. Collapsed, the illustration is centered in the content width, above the composer. Opening the list gives it a 320px left column and recenters the illustration in the remaining width, shifting it right; each wallet opens collapsed. Opening and closing animate together (.32s): the list column and gap grow while the illustration glides, the list's height and opacity ease in or out, and the chevron rotates. Reduced-motion users get the end state with no transition.
- The rules sentence omits "Ask me above" when the threshold is at or above the spend limit, since it can never trigger.
- Rules use `--font-rules` (Aspekta 500, 36px / 1.15, tracking -.54px; 24px / 1.3 on mobile). Transaction cards are compact: titles use Control (13px / 500) on every viewport and amounts use UI. `--font-transaction` is no longer used by wallet activity.
- The illustration is the data-driven sphere map (`WalletOrganism`), cropped to the 356 × 406 frame of `27:2389` (`VIEW` in `lib/walletSpheres.ts`; new spheres are placed inside it). The large core is the total wallet; each other sphere is one active wallet, with the open wallet in `--color-organism-selected`.
- It is navigation, an alternative to the sidebar: clicking or pressing Enter on a sphere moves the highlight to it (320ms), then opens that wallet; the core highlights, then goes Home. The graphic stays mounted across wallets so the highlight glides rather than jumps. Only the spheres take pointer events, and the frame uses `overflow: clip` so focusing a sphere never scrolls it.
- Merchant colors reuse the three chart tokens consistently in the bar, legend, and transaction labels. Bar widths derive from each merchant's transaction total divided by the greater of the spending limit or total spending.
- The transaction list has a bounded desktop scroll area and expands on mobile. Its sample records are labeled Demo activity.
- The wallet composer uses the shared Composer role and keeps the previously removed decorative caret absent.
