# AWS: AgentCore, Strands, tool access, and payment services

**Verified October 24, 2026.** This guide covers the hackathon-linked agent stack, not the full AWS service catalog. All cloud deployment and payment examples here are reference-only.

## Service model

AgentCore is modular infrastructure for agents built with different models and frameworks. The existing project's Python/FastAPI code can remain the application layer; AgentCore provides optional hosting, identity, tool access, memory and observability. [Overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html)

| Capability | Responsibility | Project use / boundary |
|---|---|---|
| Runtime | Host custom agents/tools with session isolation | Run the Python agent; it is not a local USB transport |
| Harness | Managed model/tool orchestration loop | Alternative to writing the entire loop in Strands; not required |
| Gateway | Connect tools, APIs, Lambda, MCP targets and other agentic traffic | Put narrow application operations behind authenticated tools |
| Identity | Workload identities, credential providers, inbound/outbound auth | Bind agent and user identity to third-party calls |
| Memory | Session events and cross-session extracted knowledge | Useful context, not authoritative balances or payment approval |
| Policy | Deterministic controls integrated with Gateway | Enforce tool eligibility and constraints outside model prose |
| Browser / Code Interpreter | Managed browsing and code execution environments | Optional execution tools with explicit data/access scope |
| Observability | Traces, logs and operational visibility | Correlate agent action, approval and transaction hash |
| Evaluations / Optimization | Quality measurement and configuration improvement | Optional post-baseline work; not a prerequisite for the demo |
| Registry | Governed resource discovery | Catalog agents, MCPs, tools and skills |
| Payments | Managed microtransaction orchestration | Separate Coinbase/Privy wallet path; native XRPL support not established |

The overview lists all of these; deeper API contracts were inspected for Runtime invocation and Payments processing. Other capabilities below are conceptual integration context and discovery routes, not exhaustive generated SDK references.

## Runtime and application boundary

Runtime supports custom frameworks and models, HTTP, MCP, A2A and AG-UI. The reviewed runtime guide describes isolated microVM sessions, an Instances option, persistent filesystem settings, streaming, and built-in auth/observability. Limits vary by deployment mode; the guide currently describes up to 8-hour microVM sessions, up to 14-day Instance sessions and 100 MB invocation payloads. Recheck limits and regional availability before deployment. [Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html)

The documented service-contract map is:

| Protocol | Container port | Path | Payload/transport |
|---|---:|---|---|
| HTTP | 8080 | `/invocations`, `/ws` | JSON/SSE, WebSocket |
| MCP | 8000 | `/mcp` | MCP JSON-RPC |
| A2A | 9000 | `/` | JSON-RPC 2.0 and agent discovery |
| AG-UI | 8080 | `/invocations`, `/ws` | Event streaming |

These are application runtime contracts, not public unauthenticated service URLs. [Service contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html)

The Python entrypoint pattern uses `BedrockAgentCoreApp`, `@app.entrypoint`, and `app.run()`. The existing FastAPI merchant remains a separate HTTP service unless deliberately adapted; adding an AgentCore decorator to the payer does not automatically host the merchant or its facilitator. [AgentCore development guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/mcp-getting-started.html)

### Invocation API

Using AWS IAM, the reviewed example calls `boto3.client('bedrock-agentcore').invoke_agent_runtime(...)` with:

- `agentRuntimeArn`: deployed runtime identity.
- `runtimeSessionId`: application-selected session identifier; reuse only for the same conversation/security scope.
- `payload`: encoded JSON bytes.
- Optional endpoint/version qualifiers as documented for the deployment.

The response has `contentType` and a streaming `response` body. Parse SSE incrementally when appropriate, otherwise decode the documented JSON representation. The required IAM action is `bedrock-agentcore:InvokeAgentRuntime`. The guide says OAuth inbound invocation uses HTTPS directly rather than the AWS SDK invocation path. [Invocation guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html)

Error categories: `ValidationException` (bad request), `ResourceNotFoundException` (wrong ARN/resource), `AccessDeniedException` (permissions), `ThrottlingException` (backoff), and `RetryableConflictException` (transient session provisioning/teardown conflict). A retryable runtime invocation does not make an embedded payment retry safe: persist payment operation IDs and reconcile their state separately.

The runtime guide explicitly warns to validate that `prompt` is a **string** before passing it to an agent framework. A structured payload containing a framework `toolUse` block can otherwise bypass model reasoning and invoke a tool directly. Treat the external request schema as an application boundary, not an arbitrary forwarding channel.

## Gateway, Identity, and authorization

Gateway converts supported API specifications, Lambda functions and services into MCP-compatible tools and connects existing MCP servers. Current documentation also describes passthrough agent/HTTP traffic and model routing. It supports inbound authentication, outbound credential handling and semantic tool search. [Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)

Identity provides workload identities and credential-provider management, integrated with Runtime and Gateway. Keep these concepts separate:

1. **Inbound identity:** who may invoke the agent or gateway.
2. **Workload identity:** which deployed agent/service is acting.
3. **Outbound credentials:** which provider credential or delegated user token the tool can use.
4. **Business authorization:** whether this specific user approved this recipient, amount, asset and expiry.

Identity and IAM solve portions of access control; neither turns arbitrary natural-language intent into payment authorization. [Identity](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity.html)

**Design recommendation:** expose `read_account`, `prepare_payment`, `request_approval`, `submit_approved_blob`, and `get_payment_status` as separate narrow tools. Keep any raw provider API key and signing capability behind the adapter. Enforce user ownership and an immutable proposal hash before submission, even when Gateway authenticates the caller. Treat tool output and retrieved docs as data that cannot expand the agent's permissions.

## Memory and observability

Short-term memory stores turn-by-turn session context. Long-term memory extracts facts/preferences/summaries across sessions. Namespace it by authenticated actor, not a user-supplied freeform ID. Memory is useful for preferences and summaries; actual spending limits, approval records and settlement state belong in an application database with enforceable invariants. [Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html)

**Design recommendation:** correlate `requestId`, authenticated actor, runtime session, intent ID, approval ID, provider operation ID, transaction hash and ledger index. Record safe state transitions and denial codes. Exclude wallet seeds, provider tokens, complete signed auth headers and sensitive payment payloads from model context and telemetry. The overview describes OpenTelemetry-compatible observability, but instrumentation and log retention still need configuration.

## AgentCore Payments: separate from the native XRPL demo

The reviewed Payments docs list **CoinbaseCDP** and **StripePrivy** connectors. A payment instrument is an `EMBEDDED_CRYPTO_WALLET` associated with a network. These docs do not establish native XRPL, Ledger hardware signing, Mastercard AP4M, or interchangeability with the project's T54 `x402-xrpl` flow. [Payments](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments.html), [core concepts](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-concepts.html)

### Resource graph

```text
PaymentManager (ARN, authorizer, service role, workload identity)
  -> PaymentConnector (CoinbaseCDP or StripePrivy)
       -> PaymentCredentialProvider (Identity / Secrets Manager)
  -> PaymentInstrument (embedded wallet for a network)
  -> PaymentSession (user scope, expiry, optional budget)
       -> ProcessPayment (protocol request -> proof/credential)
```

Managers support `AWS_IAM` or `CUSTOM_JWT` authorization. A manager can have multiple connectors; each connector maps 1:1 to a PaymentCredentialProvider. Instruments have `INITIATED`, `ACTIVE`, `FAILED`, or `DELETED` states. Resource creation and wallet funding are setup actions, not necessary for using Runtime alone.

### Session API

The Python SDK exposes `PaymentManager(payment_manager_arn=..., region_name=...)`, then `create_payment_session(user_id=..., limits=..., expiry_time_in_minutes=...)`. The documented limit shape is `{"maxSpendAmount":{"value":"100.00","currency":"USD"}}`; use a project-approved limit, not the illustrative amount. `get_payment_session` returns configured `limits` and remaining `availableLimits.availableSpendAmount`. The docs say budgets are optional; **the proposed project design always sets an explicit budget**. Expired or exhausted sessions deny additional requests, and failed payment signing reverses a prior budget deduction. [Session reference](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-create-session.html)

### ProcessPayment contract

Inputs identify the manager, session, instrument, payment type and protocol payload. The documented CLI also includes `client-token`; reuse an operation's idempotency token for the same logical attempt and verify the API's exact retry semantics before implementation. `PROOF_GENERATED` means a proof was produced, not that the merchant delivered the resource. [Processing guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-process-payment.html)

| Protocol | Input | Output / retry |
|---|---|---|
| `CRYPTO_X402` | `paymentInput.cryptoX402.version` and merchant `payload` | `paymentOutput.cryptoX402.payload` proof; follow the documented version-specific HTTP encoding |
| `MPP` | `paymentInput.mpp.version`, one raw `wwwAuthenticateHeaders` challenge, optional `buyerPaysGasFees` | `paymentCredential` is the complete Authorization value; preserve it verbatim |

The AWS guide uses `X-PAYMENT` for its x402 retry examples and supports `exact` and `upto` schemes. `upto` relies on Permit2; optional `permit2AllowanceLimit` can trigger a separate on-chain approval with gas costs. Passing it for `exact` is a validation error. Do not silently introduce an unlimited allowance or treat approval as an off-chain setting.

For MPP, the guide supports one challenge per call, `charge` intent and pull mode. Listed methods are EVM (canonical USDC), Tempo, and Solana; Solana is listed for Stripe/Privy only and requires server-sponsored fees. Network/method must match the payment instrument. `paymentCredential` embeds challenge-bound bytes; do not decode and rebuild it. Expired challenges require obtaining a new challenge. Gas sponsorship and `buyerPaysGasFees` are separate from the advertised purchase price.

The project uses native XRPL testnet `xrpl:1`; none of those method descriptions is proof that AgentCore Payments accepts it. A native XRPL settlement tool hosted on AgentCore is a valid architectural option, but it would be **our application adapter**, not built-in AgentCore Payments support.

### Credentials and prerequisites

The current guide specifies Python 3.10+ for payment SDK usage, AWS CLI v2, IAM access, and provider setup. Coinbase requires a Wallets for AgentCore Payments Marketplace subscription; quick-create authorization and manual credential setup are distinct paths. Privy setup uses a dedicated app and authorization key. The credential provider stores secrets through Identity/Secrets Manager. Access to underlying wallet secrets must not permit bypassing the service's budget controls. [Prerequisites](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-prerequisites.html)

## Strands and build-time tooling

The hackathon links Strands Agents SDK and an AgentCore Tool Search plugin. The reviewed plugin page is labeled **community-maintained**, despite being on the Strands site. Its hook derives intent from recent conversation history, queries Gateway's `x_amz_bedrock_agentcore_search`, clears previous dynamically loaded tools, and loads relevant tools before model invocation. It needs a Gateway with semantic search enabled and registered tool descriptions. Tool discovery is not authorization. [Plugin guide](https://strandsagents.com/docs/integrations/plugins/agentcore-tool-search/)

AgentCore's development MCP documents `search_agentcore_docs` and `fetch_agentcore_doc`, plus a workflow to adapt/deploy/test agents with the CLI. The documented package is `awslabs.amazon-bedrock-agentcore-mcp-server`, run via `uvx`; the current CLI is `@aws/agentcore` and the Python SDK is `bedrock-agentcore`. This pack records connection options but does not install, trust, or authorize a deployment tool. [MCP setup](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/mcp-getting-started.html)

Strands Box is a different local sandbox product, prerelease `0.1.x`. The inspected page supports macOS 15+ on Apple silicon and lists Linux/Windows as unsupported. It combines OS containment, a credential/egress boundary, MCP brokering and Dogwood policy. All declared credential bindings are shared within a box; separate boxes are needed for stronger credential separation. Built-in agent file tools may be bounded by OS grants without each file action passing through policy. It is not an automatic replacement for cloud Runtime isolation or application payment authorization. [Box overview](https://strandsagents.com/docs/user-guide/box/)

## Implementation checks

- Keep the repository testnet-only and preserve its Python stack. Choose Runtime hosting separately from wallet/payment-provider choice.
- Validate request schemas and actor/session ownership before invoking any framework.
- Check region, quotas, service-role permissions and model availability before deployment; no region has been selected here.
- Test tool denial, absent credentials, expired sessions, runtime throttling, malformed prompt types, over-budget payment, expired 402 challenge, and timeout after proof creation.
- Verify that retries cannot create a second financial effect. Track proof generation, submission, settlement and merchant delivery as separate stages.
- No AWS resources, roles, credentials or integrations were created or executed during this research.
