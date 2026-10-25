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
- Home uses the original `45:303` illustration at its 640 × 620 aspect ratio. It is decorative; wallet detail uses the original activity illustration described below.
- The home summary sits above the illustration, with no budget chart or selected-wallet constraints. The composer remains at the viewport bottom, without a decorative caret.

## Wallet activity

- Frame `27:2273` replaces the earlier balance-and-spheres detail layout. Rules span the content width above a two-column illustration and transaction history.
- Rules use `--font-rules` (Aspekta 500, 36px / 1.15, tracking -.54px; 24px / 1.3 on mobile). Transaction titles use `--font-transaction` (Aspekta 500, 16px / 1.3); mobile uses Body.
- The 356 × 406 illustration from `27:2389` is displayed at its original aspect ratio. It is decorative and is not a count of active wallets.
- Merchant colors reuse the three chart tokens consistently in the bar, legend, and transaction labels. Bar widths derive from each merchant's transaction total divided by the greater of the spending limit or total spending.
- The transaction list has a bounded desktop scroll area and expands on mobile. The transaction section is labelled Activity; simulation details live in Settings.
- The wallet composer uses the shared Composer role and keeps the previously removed decorative caret absent.

## Research chat demo

- `/demo-chat` is a separate dark tool, with a full-height sidebar, a scrolling conversation, and a bottom composer. It uses the existing typography roles and official Untitled UI icons; it has no policy editing controls.
- Dark surfaces and text use the shared `--color-chat-*` palette in `tokens.css`. The success, warning, and danger roles describe payment outcomes. Matching light feedback roles (`--color-success`, `--color-warning`, and their soft surfaces) support Cereal’s approval inbox.
- Every wallet keeps the standard illustration, spending rules, budget bar, and transaction list. Payment requests use the same transaction-card layout, with pending approvals first. Blocked and denied requests explicitly say they were not charged. The list is labelled Activity; launch and reset controls live only in Settings → Developer tools.
- The Demo badge and simulation notes remain visible. Chat source cards mark public URLs as simulated visits and paid vendors as fictional sources. Motion is limited to the normal browser UI; source progress does not rely on animation.
