# Mastercard: documentation MCP, authentication, Agent Pay, and AP4M

**Verified October 24, 2026.** Scope is the hackathon-linked Mastercard ecosystem. A private payment API contract has not been obtained.

## Separate the products

| Surface | What it provides | What it does not establish |
|---|---|---|
| Mastercard Developers Agent Toolkit | Live discovery of services, docs and API specifications via MCP | Payment execution or production entitlement |
| Mastercard product APIs | Product-specific operations under a configured Developers project | One universal payment schema or authentication scheme |
| Mastercard Agent Pay | Registered-agent participation in commerce, network tokens, intent and consent | A public endpoint named `agent-pay` with an assumed request body |
| Agent Pay for Machines (AP4M) | Credentialed, permissioned, high-frequency machine commerce with multi-rail settlement | Direct native XRPL/RLUSD API availability for this project |

Sources: [Agent Toolkit](https://developer.mastercard.com/platform/documentation/agent-toolkit/), [Agent Pay](https://www.mastercard.com/us/en/business/artificial-intelligence/mastercard-agent-pay.html), [AP4M](https://www.mastercard.com/us/en/business/artificial-intelligence/mastercard-agent-pay/agent-pay-for-machines.html).

## Documentation MCP: verified interface inventory

The recommended remote server is **`https://developer.mcp.mastercard.com`**. The local alternative is the npm package `@mastercard/developers-mcp`. These were documented, not installed or connected during this research.

| Tool | Output/context |
|---|---|
| `get-services-list` | Service names, descriptions and unique service IDs |
| `get-api-operation-list` | Operations for a selected API specification, with methods and paths |
| `get-api-operations-details` | Per-operation request parameters, response models and technical detail |
| `get-documentation` | Sections available for a service |
| `get-documentation-section-content` | One section's text and examples |
| `get-documentation-page` | Full documentation page |
| `get-oauth10a-integration-guide` | OAuth 1.0a setup and examples |
| `get-oauth20-integration-guide` | OAuth 2.0 setup and examples |
| `get-openfinance-integration-guide` | Open Finance integration guidance |

These are documented tool names, not locally verified MCP schemas. Discover their current argument schemas from the connected server before calling them. [Tool catalog](https://developer.mastercard.com/platform/documentation/agent-toolkit/mcp-overview/)

For the **local server only**, `--service` scopes to a service documentation URL, and `--api-specification` points to a raw OpenAPI/Swagger URL. The latter takes precedence if both are supplied. These options narrow documentation context, not account permissions. A useful agent workflow is: discover service → obtain operations → select operation → retrieve schema and authentication → generate an adapter with validated request/response types → test in the matching sandbox.

The portal also exposes `llms.txt` and documentation Markdown facilities. Use targeted discovery rather than dumping the entire catalog into every coding-agent prompt. [AI entry point](https://developer.mastercard.com/ai/)

## Getting API access

The platform workflow is account → project → selected APIs → generated credentials → sandbox integration → production prerequisites and approval. APIs in the same project must use compatible authentication. Some services are private or documentation-only, and some sandbox access requests require approval. Production credentials may be downloadable before they are activated. [Quick Start](https://developer.mastercard.com/platform/documentation/quick-start-guide/)

For each actual service, record:

- Service ID, API specification URL/version, exact operation ID and HTTP method/path.
- Sandbox and production base URLs from that service's contract.
- Authentication scheme, required scopes, certificates and any payload encryption requirements.
- Request fields, response status/model, rate limits, idempotency support, retry semantics and asynchronous callbacks.
- Project entitlement status and whether the test response is simulated or a real sandbox operation.

The hackathon resources link a Mastercard registration form and workshop slides. The form was not submitted. The slides were inaccessible in the current browser session. Those links are evidence of an onboarding route, not a grant of API access. [Hackathon resources](https://hackathons.xrpl-commons.org/hackathons/ai-fintech-xrp-ledger-hackathon-f78ed817?tab=resources)

## Authentication family 1: one-legged OAuth 1.0a

The verified platform guide uses **server-to-server request signing**, not an interactive user authorization dance. Each request is signed using the application's RSA private key and `RSA-SHA256`. The OAuth Authorization header includes consumer key, nonce, timestamp, signature method/version and signature; the body-hash extension uses a base64 SHA-256 digest of the request body. [OAuth 1.0a guide](https://developer.mastercard.com/platform/documentation/authentication/using-oauth-1a-to-access-mastercard-apis/)

Implementation implications:

1. Use the official client authentication library for the chosen language; do not invent signing/canonicalization rules.
2. Sign the final URL/method/body. A proxy or serializer changing the body afterward breaks verification. If the service requires encryption, the guide says encrypt before signing.
3. Use a fresh nonce/timestamp for each request and keep the server clock accurate.
4. Keep the private signing key server-side. A consumer key is an identifier; it is not interchangeable with the private key.
5. Keep sandbox credentials and base URLs paired. A syntactically valid key without access to the product still fails.

The guide's diagnostic codes include `INVALID_OAUTH_SBS`, `INVALID_OAUTH_CONSUMER_KEY`, `INVALID_CLIENT_ID`, `INVALID_KEY_ID`, `INVALID_OAUTH_SIGNATURE_METHOD`, `INVALID_OAUTH_TIMESTAMP`, `OAUTH_NONCE_USED`, `INVALID_BODY_HASH`, `AUTHENTICATION_FAILED` and `INVALID_KEY`. Group them by missing parameters, key/entitlement mismatch, clock/replay, payload mutation or expired key. Log a safe correlation ID and code, not the signed Authorization header or private key.

## Authentication family 2: OAuth 2.0 / FAPI / DPoP

The current platform guide describes client credentials using a signed `private_key_jwt`, plus **DPoP-bound access tokens**. It is not a generic `Authorization: Bearer` flow. The application has an authentication key for assertions and a **separate DPoP key pair** for proof of token possession. [OAuth 2.0 guide](https://developer.mastercard.com/platform/documentation/authentication/using-oauth-2-to-access-mastercard-apis/)

The documented flow:

1. Obtain client ID, key ID, scopes and authentication-key material from the project.
2. Generate a DPoP key using a supported algorithm (`ES256` or `PS256` in this guide).
3. Build a token-request DPoP proof, and separately sign the client assertion with the authentication key.
4. POST a form-encoded token request to the service's documented authorization endpoint.
5. On an initial `use_dpop_nonce` response, capture `DPoP-Nonce` and create a fresh proof containing it; use a bounded retry.
6. Receive `access_token`, `token_type: DPoP`, `expires_in`, and granted `scope`.
7. For each API request, generate a new proof matching its HTTP method and URL, with the access-token hash in `ath` and the appropriate nonce. Use the documented DPoP authorization scheme.

The assertion uses project identity (`kid`, `iss`, `sub`), a unique ID, time bounds and the documented issuer audience. DPoP proofs bind HTTP method/URL and time; URL normalization excludes query parameters per the guide. Do not reuse a token with a different DPoP key or substitute the OAuth1 RSA-SHA256 scheme for FAPI's required algorithms. Use the exact service's guide for endpoints, claim constraints and libraries.

Other portal authentication categories include mTLS and product-specific Open Finance flows. Their detailed contracts were not inspected. Do not apply either platform guide universally to every product.

## Agent Pay and AP4M behavior

Agent Pay's public page emphasizes registered agents, network tokenization, authenticated user intent and consent. AP4M extends the machine-payment use case with credentialing, upfront spending/authorization rules, high-frequency execution and settlement across multiple rails. The AP4M product page separates **Discover → Authorize → Execute → Settle**, describing off-chain cryptographic verification for execution and network-backed settlement. [Agent Pay](https://www.mastercard.com/us/en/business/artificial-intelligence/mastercard-agent-pay.html), [AP4M product description](https://www.mastercard.com/us/en/business/artificial-intelligence/mastercard-agent-pay/agent-pay-for-machines.html)

The June 10, 2026 [announcement](https://www.mastercard.com/global/en/news-and-trends/press/2026/june/mastercard-launches-agent-pay-for-machines.html) names Ripple among ecosystem participants and discusses cards, accounts and stablecoins. This supports ecosystem context, not a callable XRPL adapter, an RLUSD issuer address, a Mastercard wallet SDK, or guaranteed settlement for arbitrary transactions built by this project.

**Unverified and required before real integration:** sandbox base URL, operation schemas, enrollment credentials, Verifiable Intent format and verification keys, supported settlement rails, callback authentication, idempotency, finality/settlement states, reversal/refund behavior, quotas and entitlement. The public AP4M page directs readers to a representative. Record these as open requirements; do not manufacture endpoints to fill the gap.

## Suggested project adapter

This is a **local design**, not a Mastercard SDK:

```text
PaymentProvider
  capabilities() -> supported rails and modes
  prepare(intent) -> immutable proposal and quote expiry
  authorize(proposal, approvalReference) -> provider authorization reference
  execute(authorization, idempotencyKey) -> provider operation reference
  getStatus(operationReference) -> pending | succeeded | failed | unknown
```

Keep original provider states and raw schema versions alongside the normalized state; avoid reducing all providers to a boolean success. The existing native XRPL testnet path can implement a separate adapter now. A Mastercard adapter can remain explicitly simulated until the actual contract is available. Label that difference in the demo UI and logs.

## Integration acceptance checks

- A documentation MCP query returning an API spec must not count as a successful payment demo.
- Verify the project can call one entitled sandbox operation with the chosen authentication library before adding a broad product flow.
- Test expired key/token, incorrect scope/environment, DPoP nonce challenge, changed body after signing, replayed nonce, timeout after a state-changing request, and provider denial.
- Use a documented idempotency mechanism if available. If not documented, reconcile provider status before retrying a mutation; do not assume any header named `Idempotency-Key` is supported.
- Keep network settlement, merchant delivery and refund/reversal as different records. The project has no verified Mastercard settlement execution at this stage.
