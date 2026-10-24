# Partner APIs and implementation context

**Research date:** October 24, 2026, America/New_York. **Method:** computer use in Chrome; direct reading of the hackathon resources and official partner documentation, including Ledger's workshop source.

## Scope and evidence

This pack covers the products linked by the [AI & Fintech XRP Ledger Hackathon](https://hackathons.xrpl-commons.org/hackathons/ai-fintech-xrp-ledger-hackathon-f78ed817?tab=resources): Ledger DMK/XRP signing and agent tooling; Quicknode native XRPL, XRPL EVM, Streams and Webhooks; Mastercard Developers MCP, Agent Pay and AP4M; AWS AgentCore, Strands and agent payments. AWS was explicitly added to the requested scope.

It is an implementation-oriented synthesis with API inventories, critical contracts, examples, failure modes, and live-source discovery paths. It is **not a mirror of every API sold by all four companies**, nor a claim that private partner APIs have been accessed. Product-specific endpoint schemas that were not exposed in the reviewed sources remain explicit gaps. [Open questions](open-questions.md) records those gaps and conflicting examples.

Labels used throughout:

- **Verified:** read in the linked official documentation or source during this research.
- **Design recommendation:** proposed project behavior, not a vendor feature or an implemented integration.
- **Unverified:** requires entitlement, a live endpoint, installed package types, or an integration test.

No partner account was created, no MCP was installed or authorized, no cloud resource was provisioned, no registration form was submitted, and no transaction was signed or broadcast. The Mastercard slides returned **You need access**. The source registry is [sources.json](sources.json); it distinguishes read pages from inaccessible or discovery-only links.

## How the services fit

| Service | Role | Main interfaces | Boundary |
|---|---|---|---|
| Ledger | Local key custody and human-approved signing | DMK sessions/transports; XRP/EVM signer kits | Does not replace the node, transaction builder, or settlement observer |
| Quicknode | Managed blockchain access and event ingestion | XRPL RPC/WSS, EVM RPC, Streams/Webhooks REST, MCP | Endpoint authentication is not ownership of an XRPL account |
| Mastercard | Payment ecosystem plus integration documentation | Documentation MCP; product-specific APIs; Agent Pay/AP4M programs | Documentation access does not confer payment access |
| AWS | Agent execution, identity, tools, memory, policy and observability | AgentCore SDK/control plane/data plane; Gateway MCP; Strands | AgentCore Payments' listed wallets are not Ledger hardware signers |

## Read by task

| Task | Reference |
|---|---|
| Connect Ledger, derive address, sign native XRPL | [ledger.md](ledger.md) |
| Read or submit XRPL data, monitor transactions | [quicknode.md](quicknode.md) |
| Find Mastercard API operations and authentication | [mastercard.md](mastercard.md) |
| Host an agent, connect tools, scope credentials or budgets | [aws.md](aws.md) |
| Combine services into a reliable transaction flow | [architecture.md](architecture.md) |
| Load context into a coding agent; add live doc discovery | [agent-hooks.md](agent-hooks.md) |
| Resolve prerequisites or conflicting docs | [open-questions.md](open-questions.md) |

## Critical facts to carry into implementation

1. Native XRPL transactions use XRPL serialization and the Ledger XRP app. XRPL EVM uses Ethereum-compatible transactions and the Ethereum signer. Quicknode lists EVM mainnet chain ID **1440000** and testnet **1449000**; read the endpoint's chain ID before signing.
2. Ledger's workshop passes ordinary `encode(tx)` bytes to its XRP signer, **not** `encodeForSigning(tx)`: the device adds the prefix. The workshop uses DER bytes; the reference page documents a conflicting signature shape.
3. `submit` success, a signature, a webhook, and final successful settlement are different events. Require `validated: true` and the final metadata result. For Payment accounting, use `delivered_amount`.
4. Mastercard OAuth is product-specific. The platform documents both one-legged OAuth 1.0a with RSA-SHA256 and OAuth 2.0/FAPI with DPoP. Do not substitute a generic Bearer token implementation.
5. Quicknode Streams/Webhooks management uses `x-api-key`; blockchain endpoints use their endpoint token or configured authentication. Incoming webhook verification uses a separate security token.
6. AgentCore Runtime sessions, Identity workload identities, payment sessions, and Ledger device sessions are distinct scopes. Never use one ID as proof of authorization in another scope.

## Refresh policy

Before a dependency upgrade or first live integration, reread the relevant source, record the exact SDK version/API version/network, and update the source registry date for that source. Resolve conflicts with versioned SDK types and official protocol references, then verify against a sandbox or testnet fixture. Pricing, quotas, IP allowlists, plan entitlements, and available networks must be checked again at setup time.
