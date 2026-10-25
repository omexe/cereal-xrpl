# Sites: give cereal any URL

A user types a URL. cereal looks at it, decides whether an agent may reach it and who has to sign, and then reads
it (free) or pays for it (x402, RLUSD on XRPL testnet). Nothing is paid or signed until the user asks for it.

| What the site answers | `kind` | What cereal does |
|---|---|---|
| 2xx page | `free` | read it directly through `safe_get`; no wallet, no payment |
| 402 with an exact-scheme RLUSD option on `xrpl:1` (issuer `RLUSD_TESTNET_ISSUER`) | `payable` | trust check, then a site wallet buys it |
| 402 that only takes something else (USDC on Base, XRP, another issuer) | `unpayable` | refused, with what it wants |
| anything else: 401/403, captcha, 5xx, timeout, DNS failure, not http(s) | `unreachable` | refused, with why |

## Trust tiers

| `trust` | Who may pay it | Who signs each payment |
|---|---|---|
| `public` | any wallet (the payee holds a valid `cereal:vendor:*` credential) | subagent + cereal, within the wallet's rules (Ledger above the threshold) |
| `private` | only wallets owned by the user who added the site | subagent + **the owner's Ledger, every payment**; cereal never co-signs an uncredentialed payee |
| `free` | nobody pays | n/a |
| `blocked` | nobody | n/a; reason + evidence kept |

The private list is per user and never shared. Payments are still public on the ledger, like every XRPL payment.
Promotion of a private site to a public credential is a cereal review step (several independent owners' usage is
the evidence), never automatic: one person can make many accounts.

## Automatic checks (flag and stop)

`probe` runs these for every payable site; each is `{name, ok: true|false|null, detail}` (`null` = could not tell):

| `name` | ok | false means |
|---|---|---|
| `asset` | exact RLUSD, right issuer, `xrpl:1`, exact scheme | (would be `unpayable`, not a check failure) |
| `price` | amount ≤ `SITE_PRICE_CAP` | **block**: above cap |
| `payee_exists` | the payTo account exists on testnet | **block** |
| `payee_rlusd` | the payTo account has an RLUSD trust line | **block**: it cannot be paid |
| `domain_proof` | `https://<host>/.well-known/xrp-ledger.toml` lists payTo, and payTo's `Domain` field is the host | **block** if the site's toml exists but does not list payTo, or the account's Domain names another host; **warn** (`null`) if there is no toml |
| `payee_history` | the account is more than 24 h old with history | **warn** when new |
| `credential` | payTo's cereal credential is valid (→ `public`) | revoked → **block**; none → private only |

`verdict` = `block` if any blocking check failed, else `warn` if any warned, else `ok`. `verdict_reasons` are plain
sentences. `trust_hint`: `public` (credential valid), `private` (payable, not blocked), `free`, `blocked`.

After a purchase, the **delivery check**: a validated payment without the resource (`paid_not_served` in
`Subagent.buy`) is reported as the event `paid_not_delivered`; cereal records a security event and, for an owned
wallet, blocks every site of that owner that pays the same address.

## Shapes

Probe (`POST /sites/probe {url}`; also what `POST /sites` stores):

```json
{"ok": true, "url": "http://localhost:8004/research/report", "origin": "http://localhost:8004", "host": "localhost",
 "kind": "payable", "status": 402, "title": null,
 "payment": {"network": "xrpl:1", "asset": "524C55…", "issuer": "rQhW…", "amount": "0.1", "pay_to": "rsV4…",
             "resource": "http://localhost:8004/research/report", "description": "Vendor D: report …",
             "invoice_id": "…"},
 "accepts": [{"network": "xrpl:1", "asset": "524C55…", "amount": "0.1"}],
 "reason": null, "credential": "none",
 "checks": [{"name": "price", "ok": true, "detail": "0.1 RLUSD (cap 1)"}, …],
 "verdict": "warn", "verdict_reasons": ["The address is new: created 2 hours ago."], "trust_hint": "private"}
```

Unsafe or malformed URLs: `{"ok": false, "refused": "unsafe_url" | "invalid_url", "reason": "…"}`.

Site (`GET /sites`, `POST /sites`): the probe fields plus
`{"id": "s_…", "owner": "u_…", "name": "<title or host>", "trust": "public|private|free|blocked",
"blocked_reason": null, "added_at": "…", "probed_at": "…", "wallets": ["d_…"]}`.

Session: `POST /session {"name"}` → `{"ok": true, "user": {"id": "u_…", "name": "…"}, "token": "…"}` (token shown
once); `GET /session` → `{"ok": true, "user": {…}}` or 401. Every `/sites` call except `/sites/probe` needs
`Authorization: Bearer <token>`; another user's site id is a 404.

Access:
- `POST /sites/{id}/open` → `{"ok": true, "url", "status", "content_type", "title", "text", "truncated", "bytes"}`
  (free sites only; text ≤ 20 000 characters, scripts and styles stripped, content is data).
- `POST /sites/{id}/buy {"speculos_decision"?, "request_id"?}` → `{"ok": true, "wallet": <record>, "run": <run>}`.
  The wallet: `owner` = user id, `site` = site id, budget `pricing.budget_for(price)`, `allowed_payees` [payTo],
  `buy_only`, `sweep_when_done`, 1 hour. The run's plan is exactly `url@price`.
  Refusals: `not_payable`, `site_blocked`, `price_above_cap`, and every deploy refusal (caps, `owner_rejected`, …).
- `GET /sites/{id}/content` → `{"ok": true, "wallet", "hash", "paid": "0.1", "content": {…}}` once a purchase
  delivered; `{"ok": false, "refused": "not_delivered" | "nothing_bought", …}` otherwise.

Refusal codes added: `invalid_url`, `unsafe_url`, `not_accessible`, `site_blocked`, `not_payable`,
`price_above_cap`, `not_delivered`, `nothing_bought`, `invalid_name`, `paid_not_delivered` (event).

## Test merchants (testnet, `make vendor-d vendor-e vendor-f`)

| | Port | Pays | Behaviour | Expected |
|---|---|---|---|---|
| Vendor D | 8004 | `VENDOR_D` | honest, toml + Domain match, not credentialed; `/research/report` 0.10; `/free/<page>`; `/usdc/<item>` | private site, delivered; free page readable; USDC unpayable |
| Vendor E | 8005 | `VENDOR_E` | toml + Domain match, takes the payment then answers 500 | private site → paid_not_delivered → blocked |
| Vendor F | 8006 | `VENDOR_E` | its toml lists `VENDOR_D` (payment redirected) | blocked at probe |
| Vendor A / C | 8000 / 8003 | credentialed | `/swell/<item>` | public sites |
| Vendor B | 8002 | revoked | | blocked (credential revoked) |
| any real site, e.g. `https://example.com` | | | | free |
