# cereal xrpl

hackathon project for the AI & Fintech XRPL Hackathon, NYC, Oct 24–25 2026 (XRPL Commons). 36 hours; only work done during the event counts.

## context for claude
- target track: agentic finance (AI agents that pay and manage funds on XRPL). also eligible for sponsor bounties (Ledger, Mastercard, QuickNode, AWS).
- stack: python, xrpl-py, x402-xrpl (t54 reference impl), fastapi.
- network: XRPL **testnet only** (`xrpl:1`). never use mainnet, never hardcode or commit seeds.
- use the `xrpl-dev` skill in `.claude/skills/` and the XRPL docs MCP servers in `.mcp.json` before guessing any XRPL API.
- the demo must show a real testnet transaction (explorer link: https://testnet.xrpl.org).

## layout
- `scripts/new_wallet.py` — create + fund a testnet wallet
- `scripts/send_payment.py` — plain XRP payment
- `x402/server.py` — pay-per-request API (merchant)
- `x402/client.py` — agent that pays the 402 automatically (payer)
