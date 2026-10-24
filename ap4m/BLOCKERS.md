# Blockers for Live Testnet Execution (`ap4m/`) — RESOLVED

All blockers are resolved as of Oct 24, 2026:
1. `AGENT_PRIVATE_KEY` configured in `ap4m/.env` (gitignored, mode `600`).
2. Agent wallet `0xcb362681022f922b3b5090c3cdc3b57ba6b891b7` funded with `5.0 XRP` gas on XRPL EVM Testnet (`chainId: 1449000`).
3. Live run completed (`merchant.mjs`, `pay.mjs`, `verify.mjs`) and recorded in `ap4m/EVIDENCE.md`.
