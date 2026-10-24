# Brief for Gemini: the cereal dashboard (Part 5)

**Goal.** A read-only web dashboard that makes cereal's story visible on a projector during the 3-minute demo: the
main wallet, the subagents it deployed, each subwallet's budget and spending across both payment rails, every refusal
with its evidence, and every approval the owner gave on the Ledger. It updates live while `make rails` runs.

## First
Push your pending commit (`66f45e2`, BLOCKERS/EVIDENCE): `git pull --rebase origin main && git push origin main`.

## Where to work
- Your clone (`/Users/andrewpaik/XRP HACKS/cereal-xrpl-ap4m`). Create and touch only a new `web/` folder.
- Do not edit `cereal/`, `ledger/`, `ap4m/`, `x402/`, `tests/`, `Makefile`, `CLAUDE.md`, `docs/BUILD-ORDER.md` or `docs/SPEC.md`.
- Small commits prefixed `p5.web:`; `git pull --rebase origin main` before every push.

## Data: cereal's service, read-only
The service runs at `http://localhost:8001` (Claude and Andrew keep it running). Serve the dashboard from a dev server
that proxies `/api/*` to `http://localhost:8001/*`, so the service needs no CORS change. Call GET endpoints only, never
a POST: the dashboard must not be able to deploy, pay, reclaim or revoke anything.

| Endpoint | Use |
|---|---|
| `GET /main` | main wallet `address`, `rlusd`, `xrp`, `outstanding_budget`, `active_subagents`, `caps`, `policy` (`vendor_credentials`, `issuer`, `device_funding`, `ledger_recovery`, `device`, `ap4m`) |
| `GET /subagents` | every deployment (same record as below, newest last) |
| `GET /subagents/{id}` | one deployment, with live `balance` |
| `GET /vendors/{address}` | a vendor's credential: `status` valid, pending, expired, revoked or none; `revocation {hash, explorer, reason, report}` |

A deployment record (real fields, from `d_4038f3`):
- `id`, `task`, `budget`, `status` (deploying, active, reclaimed, recovered, retired, rejected, failed), `expires_at`,
  `subwallet`, `subagent`, `tag`, `balance`, `returned`.
- `hashes`: `activate`, `lock` (list), `fund`, `reclaim` (list), `recover` (list), `retire`.
- `approval`: `{by, result, screens}`. `screens` are the lines the Ledger displayed, e.g. "Amount: 1", "Destination: r…".
- `payments`: `{rail, to, amount, result, ok, hash, explorer, resource, at}`. `rail` is `x402` or `direct` (XRPL)
  or `ap4m` (Mastercard on XRPL EVM; it also has `channel_id` and `receipt`, and `explorer` points to the EVM explorer).
- `refusals`: `{refused, payee, amount, at, …}`. `vendor_not_credentialed` carries `vendor.revocation`;
  `owner_rejected` deployments have `sent_transactions: 0`.

Vendors to show in a small registry panel: A `rGrhEwizViewpp8b91RTdUV2MpdWUdaEay` (credentialed),
B `rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3` (revoked).

## Views
1. **Header.** Main wallet address, RLUSD and XRP balances, outstanding budget and caps. Policy badges: vendor
   credentials on, owner approval on Ledger, Ledger recovery signer, AP4M rail ready.
2. **Owner's Ledger panel.** Device address. One line: signer on the main wallet, weight 2 on every subwallet (alone it
   meets the quorum). For each deployment's `approval`, render `screens` as a small device screen with the result.
3. **Subagent cards**, newest first. Task, status chip, subwallet and subagent addresses linked to
   `https://testnet.xrpl.org/accounts/<address>`. A budget bar: spent on XRPL rails, spent on AP4M, remaining, returned.
4. **Timeline per card.** activate, lock, fund (note "signed by the Ledger" when `approval` exists), payments with a
   rail badge and explorer link, refusals in red with the reason and evidence link, reclaim, recover ("owner's Ledger
   alone"), retire. XRPL links: `https://testnet.xrpl.org/transactions/<hash>`; AP4M links: the payment's `explorer`.
5. **Rejected deployments** show "rejected on the owner's Ledger", what the device showed, and "0 transactions sent".

## Behaviour
- Poll every 2 seconds. Handle missing fields and an empty list.
- Show exactly what the API returns. Never invent numbers, hashes or vendors; any placeholder must say "sample".
- Legible on a projector: at least 14 px text, high contrast, no horizontal scroll at 1280 px.
- One command to run it, for example `npm --prefix web run dev` on :5173; write it in `web/README.md`.

## Done when
With the service running and `make rails` executing, the dashboard updates live and shows: the approvals with device
screens, both subagents' x402 and AP4M payments, vendor B's refusal with its revocation link, the reclaims, and the main
wallet's balance change. Add a screenshot to `web/README.md`.
