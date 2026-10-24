# cereal — what we are building and why (read this first)

## One sentence
Disposable, budget-exact wallets for AI agents, written in one plain-English sentence, locked by the XRP Ledger so no single key can spend, checked against public vendor credentials, and burned at the end into a corporate-card report.

## The problem, in the words we use on stage
AI agents already make about 500,000 payments a day on the XRP Ledger, from wallets built for humans: one seed, one balance, every vendor reachable. They cannot spot a scam, they repeat mistakes at machine speed, and one hijacked agent drains everything it can see. Every "agent wallet" on the market answers this with a policy file or a server that co-signs. A prompt injection talks around a policy file; a server is a custodian in the hot path.

## The mechanism (every rule is a ledger object)
| Rule | Ledger object | What it stops |
|---|---|---|
| How much | the burner's RLUSD balance, funded with exactly the budget | overspending (`tecPATH_PARTIAL`) |
| Who can sign | `SignerListSet` {agent 1, cereal 1, quorum 2} + `AccountSet` asfDisableMaster, created atomically in one `Batch` | the agent alone (`tefBAD_QUORUM`), cereal alone, the old master key (`tefMASTER_DISABLED`) |
| Whom it may pay | a `cereal:vendor:*` Credential (XLS-70) on the vendor, read by the co-signer before signing; `CredentialDelete` revokes for everyone | paying a vendor one customer already caught |
| Attribution | `SourceTag` + `Memos` {hmac(team,project,task), job} on every payment | untraceable spend |
| Until when | expiry in the job (co-signer rule); `LastLedgerSequence` on every transaction | stale transactions |
| Disposable | `AccountDelete` with the remainder to the treasury after the RLUSD line is zeroed | leftover attack surface |
| Human in the loop | the treasury's funding `Payment` is clear-signed on a Ledger device | budgets nobody approved |

The invariant we say to engineers: no single key can move a drop; cereal cannot spend; a compromised cereal cannot drain; the maximum loss is one job's budget; the ledger enforces all four.

## Vocabulary (use these words in code, cards and the pitch)
- **job** — one unit of agent work with a budget, an expiry and a tag; owns exactly one burner.
- **sentence** — the owner's plain-English instruction; compiled once into a **conditions card** the owner signs. The agent never touches the compiler.
- **burner** — the job's wallet: trust line, 2-of-2 signer list, master disabled, funded with the budget, deleted at the end.
- **co-signer** — cereal's key and service: verifies vendor credential, budget, expiry, tag; co-signs; never holds funds.
- **vendor credential** — `CredentialCreate/Accept` from cereal's issuer; **revocation** is `CredentialDelete` with a reason memo.
- **tag** — hmac of team/project/task carried in Memos; decoded only in the **export**.
- **burn** — Payment remainder → TrustSet 0 → AccountDelete.
- **refusal** — a ledger result we display, never an exception we hide: `tefBAD_QUORUM`, `tecPATH_PARTIAL`, `tefMASTER_DISABLED`.

## What the judges score and what has won before (from all 157 past Commons projects)
- Four criteria, 25% each, each judge scores 1–5 alone: Idea, Implementation, Demo Quality, Potential. A non-technical judge is on the panel; the story must work without jargon.
- No winner ever described a server-side policy engine; the five projects that pitched "owner sets limits, agent spends within them" all lost. We win by showing the ledger refuse a signed transaction.
- Winners open the technical answer with "XRPL primitives:" and XLS numbers (we have Batch XLS-56, Credentials XLS-70, multi-sign, AccountDelete, Memos, RLUSD, x402).
- Every on-site winner had a live URL and a demo link; decks don't separate; commit cadence does (podium repos: 40–80 small commits).
- One mechanism, not a feature tour. Nothing outside `docs/DEMO-SCRIPT.md` gets built.
- A quantified first sentence; a volume estimate nobody else gives; an afterlife (Aquarium).

## Bounties we are stacking and the one sentence for each
- **Agentic Finance track ($6k):** "agents that pay, get paid and close deals, on native multi-signing and credentials."
- **Mastercard ($6k):** "a corporate card for agents: credential, permission, transact, settle, and the report." Form submitted with an XRPL EVM testnet address.
- **Ledger ($3k):** "every budget is approved on the device; the agent's key is disposable and cannot leak funds."
- **AWS ($2k):** "a Strands agent on AgentCore spending from a burner whose cap is enforced by the ledger."
- **QuickNode ($3k):** "every burner payment hits a QuickNode webhook that feeds the live report."

## Where things are
`docs/DEMO-SCRIPT.md` (the 90 seconds and the pitch) · `docs/BUILD-ORDER.md` (steps with acceptance hashes) · `CLAUDE.md` (rules for anyone coding here) · `cereal/` (the package) · `ledger/` (device signing, Node) · `x402/` (vendor A's paid endpoint) · `scripts/setup_pool.py` (roles → `.env`). Deeper research lives outside the repo in `../research/` (11 = what wins, 12 = alternatives, 03 = judges).
