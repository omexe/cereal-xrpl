# cereal xrpl

built at the AI & Fintech XRPL Hackathon, New York, Oct 24–25 2026.

> disposable, budget-exact wallets for AI agents: one plain-English sentence, locked by the ledger (2-of-2, no master key), vendors checked against on-chain credentials, burned at the end into an accounting export. See `docs/PROJECT.md`.

## quickstart (5 minutes)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 1. make two testnet wallets (buyer + merchant), paste into .env
python scripts/new_wallet.py
python scripts/new_wallet.py

# 2. sanity check: send 1 XRP buyer -> merchant
python scripts/send_payment.py <merchant_address> 1

# 3. x402: run the paid API, then let the agent pay for it
python x402/server.py          # terminal 1
python x402/client.py          # terminal 2
```

every transaction prints a link to https://testnet.xrpl.org.

## claude code setup
- `.mcp.json` registers the XRPL docs MCP servers; claude code will ask to enable them on first run.
- `.claude/skills/xrpl-dev/` is the XRPL Commons dev skill (MIT), vendored from [XRPL-Commons/xrpl-dev-skills](https://github.com/XRPL-Commons/xrpl-dev-skills).

## references
- [agentic payments with x402 on XRPL](https://xrpl.org/docs/agents/agentic-payments-x402)
- [XRPL AI tools](https://xrpl.org/resources/dev-tools/ai-tools)
- [testnet faucet](https://xrpl.org/resources/dev-tools/xrp-faucets)

## partner documentation and coding-agent context

The [partner documentation pack](docs/partners/README.md) covers Ledger, Quicknode, Mastercard and AWS, researched through official documentation on October 24, 2026. It includes API contracts, authentication, integration architecture, source provenance, and explicit access/schema gaps.

```bash
python3 scripts/partner_context.py --list
python3 scripts/partner_context.py ledger architecture
```

[Agent hooks](docs/partners/agent-hooks.md) explain the offline loader, project-local skill and optional documentation MCP connections. Existing MCP configuration and payment code are unchanged. Partner integrations are documented proposals unless explicitly marked otherwise.
