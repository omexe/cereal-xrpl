# Ledger: hardware signing, DMK, and agent tooling

**Verified October 24, 2026.** Read this for wallet connection, native XRP signing, device approval UX, or Ledger-specific coding-agent support.

## Product and trust model

Ledger's device retains private keys and signs through its installed blockchain app. The host application prepares transaction data and communicates over a transport. The **Device Management Kit (DMK)** manages discovery, device sessions, state, and APDU-based operations; a **Device Signer Kit** supplies chain-specific operations. The node/provider remains responsible for ledger reads and broadcasting. [DMK reference](https://developers.ledger.com/docs/device-interaction/dmk-ts/integration/how_to/dmk)

The [hackathon page](https://developers.ledger.com/xrplnyc) describes native XRP support as early and incomplete: basic address/config/signing in the XRP signer, limited Ledger Wallet flows, and no native XRPL transaction Clear Signing. It invites integrations for trustlines, DEX/AMM, escrow, NFTs, and multisig, but that invitation is not a type-by-type compatibility guarantee. Test the intended transaction with the selected device/app/SDK combination. A human-readable web preview is useful but is not equivalent to a securely rendered on-device Clear Signing implementation.

## Stack and package roles

| Package | Purpose |
|---|---|
| `@ledgerhq/device-management-kit` | DMK builder, sessions, action states, utility functions |
| `@ledgerhq/device-signer-kit-xrp` | XRP address, app configuration, signing |
| `@ledgerhq/device-transport-kit-web-hid` | Browser USB transport via WebHID |
| `@ledgerhq/device-transport-kit-web-ble` | Browser Bluetooth transport |
| `@ledgerhq/device-transport-kit-node-hid` | Node.js USB transport |
| `@ledgerhq/device-transport-kit-speculos` | Device emulator transport |
| `rxjs` | Observable lifecycle handling |
| `xrpl` | Transaction construction, encoding, node connection, submission |

The inspected [workshop package.json](https://github.com/LedgerHQ/device-management-kit-ts-workshop/blob/main/xrpl-hackathon/app/package.json) declares DMK `^1.11.0`, XRP signer `^0.2.0`, Speculos transport `^1.3.0`, WebBLE `^1.3.2`, WebHID `^1.2.4`, RxJS `^7.8.2`, and xrpl.js `^5.3.0`. These are **declared ranges, not exact resolved versions** and not a recommendation to mix whatever versions are latest. The hackathon landing page still calls the signer prerelease; reconcile that label with the package release selected for implementation. No dependencies were installed during this research.

## Session lifecycle

The [official solution](https://github.com/LedgerHQ/device-management-kit-ts-workshop/blob/main/xrpl-hackathon/app/src/ledger/solution.ts) shows:

1. Build one DMK with the supported transport factories.
2. Start discovery with a transport identifier, select a discovered device, and call `dmk.connect({device})` to get a session ID.
3. Build `new SignerXrpBuilder({dmk, sessionId}).build()` for that session.
4. Retrieve an address with the intended derivation path and optional on-device verification.
5. Run signing as a cancellable observable action.

WebHID requires Chromium, HTTPS or localhost, and a user gesture to open discovery. Bluetooth requires a compatible device; the workshop specifically excludes Nano S Plus from Bluetooth. The DMK documents `connected`, `locked`, `busy`, and `disconnected` device states. It also notes limitations distinguishing two devices of the same model over WebHID. [Agent skill guide](https://developers.ledger.com/docs/ai-tools/ledger-dmk-skills), [DMK](https://developers.ledger.com/docs/device-interaction/dmk-ts/integration/how_to/dmk)

**Design recommendation:** keep device discovery in the browser/local application. An AWS-hosted agent should request approval through an application channel; it cannot directly use a USB signer attached to the user's computer. Bind each pending request to the user, device address, network, and immutable transaction digest. Serialize device operations and invalidate session-bound state on disconnection.

## XRP signer API

All three methods return `{observable, cancel}`. They are not promises of the final result. [XRP signer reference](https://developers.ledger.com/docs/device-interaction/dmk-ts/references/signers/xrp)

| Call | Inputs | Documented result / caveat |
|---|---|---|
| `getAppConfig(options?)` | `skipOpenApp?: boolean`, default false | Completed output has `version: string` |
| `getAddress(path, options?)` | XRP path; `checkOnDevice`, `returnChainCode`, `skipOpenApp`, default false | `address`, hex `publicKey`, optional `chainCode` |
| `signTransaction(path, transaction, options?)` | `Uint8Array` serialized transaction; optional `skipOpenApp` | **Conflicting documentation:** see below |

Use the workshop's XRP path `44'/144'/0'/0/0`; the hardened account index changes for additional accounts. The reference says address paths may have at most ten elements. Its signing section also contains a Bitcoin-style path example; that is not the path to use for native XRP.

Observable states are `NotStarted`, `Pending`, `Stopped`, `Completed`, and `Error`. `Pending` includes `intermediateValue.requiredUserInteraction` for actions such as unlocking, opening the XRP app, verifying an address, and signing. Treat `Stopped` as cancellation. Use the `Completed` output only; a stream completion event by itself is not a signature. Cancel/unsubscribe when the owning UI flow ends. Generic interaction enums may mention personal-message signing; this does not add a personal-message method to the XRP signer.

### Signature output conflict

The developer reference declares `{r: string, s: string, v?: number}`. The hackathon [README](https://github.com/LedgerHQ/device-management-kit-ts-workshop/tree/main/xrpl-hackathon), [solution.ts](https://github.com/LedgerHQ/device-management-kit-ts-workshop/blob/main/xrpl-hackathon/app/src/ledger/solution.ts), and [xrpl.ts](https://github.com/LedgerHQ/device-management-kit-ts-workshop/blob/main/xrpl-hackathon/app/src/xrpl.ts) use a **DER-encoded `Uint8Array`**. For this project, the workshop is the concrete integration starting point, but resolve the type using the installed signer version before writing a converter. Do not concatenate `r`, `s`, and `v` as if this were an Ethereum signature. Record a fixture and verify the final transaction signature locally before broadcasting.

## Native XRP transaction pipeline

The workshop establishes the following sequence:

1. Obtain the signer address and public key; verify the address on device during account selection.
2. Build a Payment with `Account`, `Destination`, and an amount converted with `xrpToDrops` from a decimal string. The workshop uses the `Amount` spelling; newer protocol JSON uses `DeliverMax` in API v2. Do not specify both.
3. Use `client.autofill` to populate ledger-dependent fields. Set `SigningPubKey` to the device public key in uppercase hex. Set a deliberate `LastLedgerSequence` before encoding.
4. Freeze the unsigned transaction and display recipient, destination tag if applicable, asset/issuer, amount, fee, network, and expiry.
5. Pass bytes from **`encode(tx)`**, not `encodeForSigning`, to `signTransaction`. The XRP device app adds the signing prefix.
6. Wait for the completed device action. For the workshop's DER contract, uppercase-hex the signature into `TxnSignature` and `encode` again.
7. Submit that exact signed blob through Quicknode or another XRPL server and wait for a validated result. Inspect `meta.TransactionResult`, not only the RPC request status.

The workshop uses `getLedgerIndex() + 150` to allow more time for human signing. That is a ledger-count expiry, not a guaranteed ten-minute timer. For the product, choose an explicit validity window and reprepare/reapprove expired requests. Never change fee, sequence, destination, amount, or expiry after signing. [Workshop XRPL implementation](https://github.com/LedgerHQ/device-management-kit-ts-workshop/blob/main/xrpl-hackathon/app/src/xrpl.ts), [Payment protocol reference](https://xrpl.org/docs/references/protocol/transactions/types/payment)

## XRP versus XRPL EVM

Native XRPL uses the XRP app, XRP signer, classic addresses, XRPL fields, and the XRPL binary codec. The EVM sidechain uses an Ethereum-compatible signer and transaction format, EVM addresses, gas and nonce, and chain-ID binding. The hackathon highlights EVM Clear Signing as a separate path. Native XRP Clear Signing limitations cannot be fixed merely by presenting an EVM metadata file. [Ledger hackathon tracks](https://developers.ledger.com/xrplnyc)

## Agent tools are different products

| Capability | Use | What to avoid assuming |
|---|---|---|
| DMK skills | Build-time guidance for integrating DMK | Does not execute device operations by loading Markdown |
| Ledger Wallet CLI | Runtime account queries, sends, swaps, staking, and other supported wallet operations | Do not assume every command supports native XRPL |
| Ledger Agent Intent (beta) | Agent proposes an intent; user reviews/approves later | Exact XRPL intent schema and support were not verified |
| Key Ring | Secret encryption/decryption workflows | The overview says device needed for initialization; later decryptions use network/password, not a device confirmation every time |
| Hardware security features | OpenPGP/FIDO2/WebAuthn use cases | Separate from transaction signing and product authorization |

[Ledger AI overview](https://developers.ledger.com/docs/ai-tools/overview). The official build-time skills are `dmk-intent-vocabulary`, `ledger-dmk-implementation`, and `dmk-business-logic`; the [hooks guide](agent-hooks.md) records their installation source without installing them.

## Earn integration

Ledger Wallet Earn requires three delivered components: a LiveApp, secure on-device Clear Signing, and dashboard data APIs for positions/rewards. This is a distribution/integration program, not just another signer call. The combination of mandatory Clear Signing for Earn and absent native XRP Clear Signing creates a concrete gap for an XRPL-native Earn proposal. Confirm feasibility with Ledger before promising Wallet Earn placement. Dashboard endpoint schemas were not reviewed. [Earn overview](https://developers.ledger.com/docs/ledger-live/exchange/earn)

## Development and failure checklist

- The workshop supplies Speculos with XRP app builds and a React demo; its documented environment is Docker, Node.js 22+, and Chromium. An emulator demo is not evidence of physical-device security.
- Cover rejection, cancellation, locked device, wrong app, busy transport, disconnect during signing, stale session, invalid path, expired ledger sequence, and signature-format mismatch.
- A declined signature should not trigger automatic repeated approval prompts. A disconnected signer must not silently fall back to a software seed.
- Test byte-for-byte transaction immutability between preview, signing, and submission. Test the chosen advanced transaction type separately; basic Payment success does not prove AMM or multisig support.
- Capture the exact dependency lockfile, device model, firmware, XRP app version, network, and final transaction hash in integration evidence. No such integration execution has been performed for this documentation pack.
