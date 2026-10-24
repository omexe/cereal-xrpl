# cereal xrpl

built at the AI & Fintech XRPL Hackathon, New York, Oct 24–25 2026.

> one-line pitch goes here.

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
