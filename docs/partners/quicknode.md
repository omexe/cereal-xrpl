# Quicknode: native XRPL, EVM, Streams, Webhooks, and MCP

**Verified October 24, 2026.** The project uses native XRPL testnet. EVM and mainnet information below is reference context, not a change to that constraint.

## Four distinct interfaces

| Interface | Purpose | Authentication | Does it sign? |
|---|---|---|---|
| Dedicated XRPL endpoint | Ledger/account queries and signed transaction submission | Endpoint token in URL or `x-token`; optional configured controls | Keep signing local; send signed blobs |
| XRPL EVM endpoint | Ethereum-compatible queries, contracts, raw transactions | Endpoint credentials | Use an EVM signer externally |
| Streams/Webhooks REST | Provision and manage data delivery | Account API key in `x-api-key` | No |
| Quicknode MCP | Account management and read-only chain RPC | OAuth, or API-key Bearer for noninteractive clients | `call-rpc` refuses transaction-write methods |

Sources: [XRPL overview](https://www.quicknode.com/docs/xrpl), [security](https://www.quicknode.com/docs/xrpl/endpoint-security), [Streams API](https://www.quicknode.com/docs/streams/rest-api), [MCP](https://www.quicknode.com/docs/build-with-ai/quicknode-mcp).

## Native XRPL endpoint behavior

Quicknode lists native XRPL mainnet and testnet, HTTP and WSS, with archive access. Mainnet history is described as starting at ledger 32570, while testnet history follows the latest network reset. Do not infer that ledger 1 is retrievable or that testnet IDs survive resets. The XRPL API overview lists Streams and Webhooks support. [Network/API coverage](https://www.quicknode.com/docs/xrpl/api-overview)

HTTP requests use a method and an array containing the parameter object. This illustrative request is read-only; replace the account and use the project's testnet endpoint:

```json
{
  "jsonrpc": "2.0",
  "id": "account-state",
  "method": "account_info",
  "params": [{"account": "<XRPL_CLASSIC_ADDRESS>", "ledger_index": "validated"}]
}
```

WebSocket XRPL messages use `command` with parameters at the top level, for example `{"id":"watch","command":"subscribe","accounts":["<XRPL_CLASSIC_ADDRESS>"]}`. XRPL subscription methods are WebSocket-only; the admin callback `url` option is not a public hosted-webhook API. Native XRPL does not use Ethereum's `eth_subscribe`. [Quickstart](https://www.quicknode.com/docs/xrpl/quickstart), [XRPL method reference](https://xrpl.org/docs/references/http-websocket-apis/public-api-methods)

### Core operation contracts

| Method | Inputs to prepare | Outputs to use | Integration note |
|---|---|---|---|
| `account_info` | `account`; ledger selection; optional strict/queue settings | `account_data.Balance`, `Sequence`, flags, `validated` | Queue data applies to the current open ledger; validated balance is a snapshot |
| `fee` | Empty parameter object | Fee amounts in `drops`, queue/load data | Values are strings; apply a project fee ceiling, not a hardcoded fee |
| `submit` | `tx_blob` containing the signed transaction | `engine_result`, hash/transaction data, queued/applied/broadcast indicators | Provisional outcome, even if transport/request status is success |
| `tx` | Hash in `transaction`, or supported `ctid`; optional binary/range/API version | `validated`, `meta.TransactionResult`, `tx_json` in v2, ledger index/hash | `txnNotFound` alone does not prove failure |
| `subscribe` | Account list, streams, or books | Subscription acknowledgement followed by events | Separate proposed from validated events; recover after reconnect |
| `unsubscribe` | Corresponding subscription selectors | Acknowledgement | Close subscriptions when consumers end |

Read: [account_info](https://www.quicknode.com/docs/xrpl/account_info), [submit](https://www.quicknode.com/docs/xrpl/submit), [subscribe](https://www.quicknode.com/docs/xrpl/subscribe), [canonical tx](https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/transaction-methods/tx).

### Complete method inventory exposed in the reviewed Quicknode XRPL sidebar

This is a discovery inventory, not a promise that every method is enabled identically on every hosted endpoint. Follow the individual reference and validate supported parameters against the chosen server/API version.

| Family | Methods | Use |
|---|---|---|
| Account | `account_channels`, `account_currencies`, `account_info`, `account_lines`, `account_nfts`, `account_objects`, `account_offers`, `account_tx` | Account state, balances/trustlines, owned objects, history |
| Issuer/settings | `gateway_balances`, `noripple_check` | Issued obligations and rippling checks |
| Ledger | `ledger`, `ledger_closed`, `ledger_current`, `ledger_data`, `ledger_entry` | Ledger snapshots, headers and objects |
| Transactions | `submit`, `submit_multisigned`, `transaction_entry`, `tx`, `tx_history` | Broadcast and lookup; see deprecation note below |
| DEX/paths | `book_offers`, `deposit_authorized`, `path_find`, `ripple_path_find` | Orderbooks, recipient authorization and payment routing |
| NFT/Clio | `nft_buy_offers`, `nft_sell_offers`, `nft_info`, `nft_history`, `nfts_by_issuer` | Offers, ownership and indexed NFT history |
| Channels | `channel_authorize`, `channel_verify` | Payment-channel claims; authorization has signing implications |
| Subscriptions | `subscribe`, `unsubscribe` | WSS notifications |
| Server/utilities | `fee`, `manifest`, `ping`, `random`, `server_info` (Clio and rippled entries), `server_state` | Fees, health and diagnostic data |

Important coverage differences: the [canonical XRPL inventory](https://xrpl.org/docs/references/http-websocket-apis/public-api-methods) also lists `amm_info`, `feature`, `server_definitions`, MPT query methods, and `vault_info`, which were not in the reviewed Quicknode sidebar. Verify availability before using them. It marks `tx_history` deprecated in favor of `account_tx` or ledger transaction retrieval. It also describes `channel_authorize` as admin-only by default unless public signing is enabled. Never send a wallet seed to a hosted signing method merely because it appears in a catalog.

### Correctness, pagination, and recovery

**Design recommendations:** pin `api_version` where supported; normalize result envelopes in one adapter; use typed SDK models; record the ledger/version used for a view. For paginated lists, carry the opaque marker with the same query and ledger snapshot, and enforce a page limit. Do not infer a complete balance/history from a single page. Reconnect WSS with bounded backoff, then backfill from the last durable ledger checkpoint before relying on live updates again.

XRPL finality is stricter than RPC success. `tesSUCCESS` and `tec*` are final only when included in a validated ledger. `tec*` means the intended operation failed even though cost was charged. `ter*` may later succeed. `tem*` represents malformed transactions. `tefPAST_SEQ` requires resolving the validated transaction occupying that sequence. Expiry is final only after a validated ledger passes `LastLedgerSequence` and the transaction is absent from the relevant validated history. [Result codes](https://xrpl.org/docs/references/protocol/transactions/transaction-results), [finality](https://xrpl.org/docs/concepts/transactions/finality-of-results)

For `tx`, the canonical reference supports `min_ledger`/`max_ledger` search ranges of up to 1000 ledgers. A not-found result's `searched_all` distinguishes complete from incomplete history coverage. Preserve an **unknown** state on missing coverage; don't generate a new payment merely because a request timed out.

### Provider example discrepancies

The reviewed Quicknode `tx` example uses `metadata`, a nested placeholder result, and describes `date` as Unix time. The canonical XRPL v2 reference uses `meta`, `tx_json`, and a `date` measured from the **Ripple Epoch**; it also supplies `close_time_iso`. Prefer the protocol contract and an observed fixture. Quicknode's `subscribe` example shows an opaque hex result resembling an EVM example; it is not sufficient to implement native XRPL subscription parsing. [Quicknode tx page](https://www.quicknode.com/docs/xrpl/tx), [canonical tx](https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/transaction-methods/tx)

## Endpoint security and operations

The endpoint token can be embedded in the provider URL, or passed through HTTP `x-token`. Treat either as a secret. The security page describes additional tokens, JWT, referrer restrictions, method rate limits, and domain masking, with plan-dependent access. Referrer/Origin allowlisting is not strong authentication because nonbrowser clients can spoof these headers. Rotation by regenerating a token invalidates the old token; overlapping additional tokens offer a different rotation path. [Endpoint security](https://www.quicknode.com/docs/xrpl/endpoint-security)

**Design recommendation:** keep provider credentials on the FastAPI/backend side. A public client can send an authorized, already signed blob to a constrained backend submit operation; the backend should verify it matches the approved request. Redact URL paths and authorization headers in logs. Retry read requests on transient errors with backoff; distinguish 401/403 configuration failures from 429 throttling and 5xx outages. For broadcasts, reconcile by hash before any new signing attempt.

## XRPL EVM

Quicknode exposes Ethereum-compatible JSON-RPC on the sidechain, including contract interactions and archive queries. Its overview lists **1440000 mainnet** and **1449000 testnet**, and labels the offering beta. Use EVM libraries and the Ledger Ethereum signer, verify `eth_chainId`, estimate gas, and track nonce and receipt status separately from native XRPL sequence/finality logic. Do not reuse a classic `r...` address or native XRP blob. The cited overview is not a reviewed inventory of every `eth_*`, tracing, and debug method. [XRPL EVM RPC](https://www.quicknode.com/docs/xrplevm)

## Streams: programmable ingestion

Streams supports historical backfill and continuous ingestion, server-side filtering, batching/compression, and destinations including HTTP webhooks, S3, PostgreSQL, Azure Blob and Kafka. [Overview](https://www.quicknode.com/docs/streams)

The chain matrix lists native XRP Ledger mainnet/testnet with a **Ledger/block dataset only**; do not apply EVM log-topic filters to it. XRPL EVM mainnet/testnet has block, block-with-receipts, transactions, logs and receipts, while the listed trace variants are unavailable. Obtain a sample dataset before writing filters. [Supported chains](https://www.quicknode.com/docs/streams/supported-chains)

Management base: `https://api.quicknode.com/streams/rest/v1`. Authentication: `x-api-key` plus JSON content type for bodies.

| HTTP | Path | Function |
|---|---|---|
| POST / GET | `/streams` | Create / list |
| GET / PATCH / DELETE | `/streams/{id}` | Read / update / delete one |
| DELETE | `/streams` | Delete all; catalog reference only |
| POST | `/streams/{id}/pause`, `/streams/{id}/activate` | Change lifecycle |
| GET | `/streams/enabled_count` | Active count |
| POST | `/streams/test_filter` | Test transformation |

Create/update fields include `name`, `network`, `dataset`, `region`, `dataset_batch_size`, `elastic_batch_enabled`, `destination`, `destination_attributes`, and optionally `filter_function` and historical ranges. Exact required combinations are destination-specific. A JavaScript filter is encoded as base64 for the REST request, exposes `main(stream)`, reads `.data` and `.metadata`, and returns transformed data or `null` to skip delivery. Use the provider's test-filter operation on a known ledger fixture before activation. [REST reference and OpenAPI link](https://www.quicknode.com/docs/streams/rest-api)

`dataset_batch_size` groups work; elastic batching allows a smaller batch at the chain tip. The current reference has minimum-batch rules for subsecond networks and 422 errors when violated; do not carry those rules over to another network without checking its current configuration. The API overview advertises exactly-once delivery, but the application should still implement idempotent processing for replay, backfill and downstream retry boundaries.

## Webhooks: template-based delivery

Webhooks provides near-real-time HTTP POST notifications, templates, gzip and retries for non-200 responses. Streams is the documented option for historical backfill, batching, custom transformations, and alternate destinations. [Webhooks overview](https://www.quicknode.com/docs/webhooks)

The REST guide explicitly lists XRP Ledger testnet/mainnet and the `xrplWalletFilter` template. Creation uses:

`POST https://api.quicknode.com/webhooks/rest/v1/webhooks/template/xrplWalletFilter`

Documented fields include `name`, a supported `network` enum, `destination_attributes` (`url`, optional/generated `security_token`, `compression`), and `templateArgs`. The overview shows inline `wallets` or `walletsListName` references. The generated template reference defaults to EVM and presents list-based requirements differently; confirm the selected XRPL template and current OpenAPI before forming the production request. A list reference does not populate the key-value list; that is a separate API operation. Do not copy the overview's malformed sample XRP address. [REST overview](https://www.quicknode.com/docs/webhooks/rest-api/getting-started), [template endpoint](https://www.quicknode.com/docs/webhooks/rest-api/webhooks/webhooks-rest-create-from-template)

### Incoming message verification

Verified headers: `X-QN-Nonce`, `X-QN-Timestamp`, `X-QN-Signature`. The documented digest is HMAC-SHA256 with the stream/webhook security token as key over the concatenation `nonce + timestamp + payload`, where payload is the **original uncompressed UTF-8 JSON string**. Verify the decoded body without parsing and reserializing it. For gzip, decompress exactly once; Express raw/body-parser middleware may already inflate it while preserving the header. [Signature guide](https://www.quicknode.com/guides/quicknode-products/streams/validating-incoming-streams-webhook-messages)

**Design recommendation:** validate header formats, compare equal-length digest bytes in constant time, bound compressed and decompressed sizes, enforce a timestamp window consistent with documented retry behavior, and persist replay/deduplication state. A correctly authenticated duplicate that is already processed can be acknowledged without executing the business effect again. Persist or enqueue durably before returning 200. Confirm the on-chain transaction and expected amount/recipient before crediting a payment. A valid webhook HMAC authenticates the delivery, not the business authorization.

## MCP and coding-agent use

Endpoint: `https://mcp.quicknode.com/mcp`. Viewer permits read-only RPC and account inspection; Admin permits infrastructure changes. Tooling Access must be enabled at account level for `call-rpc`; it is shared with CLI/SDK tooling. Disabling it affects the account, not just one chat. `call-rpc` is read-only even with an Admin connection; broadcast through a dedicated endpoint from application code. [MCP documentation](https://www.quicknode.com/docs/build-with-ai/quicknode-mcp)

Read-only tools include `call-rpc`, `list-chains`, endpoint list/detail/metrics/logs, security/rate-limit reads, usage and billing. Admin tools cover create/delete endpoints, security rules, rate limits and Tooling Access toggles. These are account operations, distinct from a documentation-only MCP. The [hooks guide](agent-hooks.md) keeps this connector optional and records its access implications.
