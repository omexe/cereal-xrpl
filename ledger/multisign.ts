// Device multisign: the Ledger (or Speculos) signs a transaction as ONE signer of a multisig account.
// Usage:
//   npx tsx multisign.ts address                       → prints the device address + pubkey (put LEDGER_ADDRESS in .env)
//   npx tsx multisign.ts sign  <unsigned-tx.json>      → prints a Signer entry JSON (and the signed blob with only this signer)
//   npx tsx multisign.ts sweep <burner> <dest> <xrp>   → device-alone recovery: Payment from the burner, signed on device, submitted
// How it works (verified in LedgerHQ/app-xrp source): the signer kit is a byte signer; pass encode(tx) with an EMPTY
// top-level SigningPubKey and NO Signers. The device app then uses the multisign prefix and appends its own AccountID,
// so the returned DER signature is a valid multisig Signer. Parallel multisign only: never include other Signers in the bytes.
import { DeviceManagementKitBuilder, DeviceActionStatus, bufferToHexaString, hexaStringToBuffer } from "@ledgerhq/device-management-kit";
import { SignerXrpBuilder } from "@ledgerhq/device-signer-kit-xrp";
import { speculosIdentifier, speculosTransportFactory } from "@ledgerhq/device-transport-kit-speculos";
import { firstValueFrom, filter, type Observable } from "rxjs";
import { Client, encode, multisign, xrpToDrops, type Payment, type Transaction } from "xrpl";
import dotenv from "dotenv";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
dotenv.config({ path: fileURLToPath(new URL("../.env", import.meta.url)), quiet: true });

const SPECULOS = process.env.SPECULOS_URL ?? "http://127.0.0.1:5000";
const MODEL = process.env.SPECULOS_MODEL ?? "nanosp";
const PATH = process.env.LEDGER_PATH ?? "44'/144'/0'/0/0";
const WS = process.env.QUICKNODE_XRPL_WS || process.env.XRPL_TESTNET_WS_URL || "wss://s.altnet.rippletest.net:51233";
const SOURCE_TAG = Number(process.env.CEREAL_SOURCE_TAG ?? "20260601");
const RLUSD_CURRENCY = "524C555344000000000000000000000000000000";
const RLUSD_ISSUER = process.env.RLUSD_TESTNET_ISSUER ?? "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV";

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
async function button(b: "left" | "right" | "both") {
  await fetch(`${SPECULOS}/button/${b}`, { method: "POST", body: JSON.stringify({ action: "press-and-release" }), headers: { "content-type": "application/json" } });
}
async function screen(): Promise<string> {
  const r = await fetch(`${SPECULOS}/events?currentscreenonly=true`);
  const j = await r.json() as { events: { text: string }[] };
  return j.events.map(e => e.text).join(" | ");
}
async function autoApprove(stop: { done: boolean }) { // Speculos only; a real device needs a human press
  for (let i = 0; i < 80 && !stop.done; i++) {
    const s = await screen();
    if (/sign transaction|accept|approve/i.test(s) && !/reject/i.test(s)) { await button("both"); await sleep(400); continue; }
    await button("right"); await sleep(250);
  }
}
async function completed<T>(obs: Observable<any>): Promise<T> {
  const s = await firstValueFrom(obs.pipe(filter((st: any) => [DeviceActionStatus.Completed, DeviceActionStatus.Error, DeviceActionStatus.Stopped].includes(st.status))));
  if (s.status !== DeviceActionStatus.Completed) throw new Error(`device action ${s.status}: ${JSON.stringify(s.error ?? s)}`);
  return s.output as T;
}

async function connect() {
  const dmk = new DeviceManagementKitBuilder().addTransport(speculosTransportFactory(SPECULOS)).build();
  const devices = await firstValueFrom(dmk.listenToAvailableDevices({ transport: speculosIdentifier }).pipe(filter(d => d.length > 0)));
  const sessionId = await dmk.connect({ device: devices[0] });
  const signer = new SignerXrpBuilder({ dmk, sessionId }).build();
  return { dmk, signer, sessionId };
}

export async function deviceAddress() {
  const { signer, dmk } = await connect();
  const out = await completed<{ address: string; publicKey: string }>(signer.getAddress(PATH, { checkOnDevice: false }).observable);
  await dmk.close?.();
  return { address: out.address, publicKey: out.publicKey.toUpperCase() };
}

/** Sign `tx` (unsigned, fully autofilled) on the device as a multisig signer. Returns the Signer entry and a blob carrying only it. */
export async function deviceSigner(tx: Transaction) {
  const { signer, dmk } = await connect();
  const me = await completed<{ address: string; publicKey: string }>(signer.getAddress(PATH, { checkOnDevice: false }).observable);
  const pub = me.publicKey.toUpperCase();
  const unsigned: any = { ...tx, SigningPubKey: "" };
  delete unsigned.Signers; delete unsigned.TxnSignature;
  const blob = encode(unsigned);
  const stop = { done: false };
  const approve = autoApprove(stop);
  let sig: any;
  try { sig = await completed<any>(signer.signTransaction(PATH, hexaStringToBuffer(blob)!).observable); }
  finally { stop.done = true; await approve; }
  const sigHex = (sig instanceof Uint8Array ? bufferToHexaString(sig) : (sig.r ? sig.r + sig.s : String(sig))).replace(/^0x/, "").toUpperCase();
  const entry = { Signer: { Account: me.address, SigningPubKey: pub, TxnSignature: sigHex } };
  const signedBlob = encode({ ...unsigned, Signers: [entry] });
  await dmk.close?.();
  return { entry, signedBlob, address: me.address };
}

async function main() {
  const [cmd, a, b, c] = process.argv.slice(2);
  if (cmd === "address") { console.log(JSON.stringify(await deviceAddress())); return; }
  const client = new Client(WS); await client.connect();
  try {
    if (cmd === "sign") {
      const tx = JSON.parse(readFileSync(a, "utf8")) as Transaction;
      const out = await deviceSigner(tx);
      console.log(JSON.stringify(out, null, 2));
    } else if (cmd === "sweep") {
      const [burner, dest, xrp] = [a, b, c];
      const tx = await client.autofill({ TransactionType: "Payment", Account: burner, Destination: dest, Amount: xrpToDrops(xrp), SourceTag: SOURCE_TAG } as Payment, 1);
      const li = (await client.request({ command: "ledger", ledger_index: "validated" })).result.ledger_index;
      (tx as any).LastLedgerSequence = li + 75;
      const { entry, signedBlob, address } = await deviceSigner(tx);
      console.log(`device ${address} signed as multisig signer; submitting (device weight must meet quorum alone)`);
      const combined = multisign([signedBlob]);
      const res = await client.submitAndWait(combined);
      const r: any = res.result;
      console.log(`result ${r.meta?.TransactionResult}  hash ${r.hash}\nexplorer https://testnet.xrpl.org/transactions/${r.hash}`);
      void entry;
    } else if (cmd === "fund") {
      // fund <burner> <amount> <jobId> <tag>: the treasury's RLUSD budget payment, signed on the device
      // (the device is a signer on TREASURY; quorum 1). Memo identical to cereal/ledger.py job_memo(kind="fund").
      const [burner, amount, jobId, tag] = [a, b, c, process.argv[6]];
      const treasury = process.env.TREASURY_ADDRESS!;
      const hex = (s: string) => Buffer.from(s, "utf8").toString("hex").toUpperCase();
      const memo = { Memo: { MemoData: hex(JSON.stringify({ tag, job: jobId, kind: "fund" })),
                             MemoType: hex("cereal/job"), MemoFormat: hex("application/json") } };
      const tx = await client.autofill({
        TransactionType: "Payment", Account: treasury, Destination: burner, SourceTag: SOURCE_TAG,
        Amount: { currency: RLUSD_CURRENCY, issuer: RLUSD_ISSUER, value: amount }, Memos: [memo],
      } as Payment, 1);
      const li = (await client.request({ command: "ledger", ledger_index: "validated" })).result.ledger_index;
      (tx as any).LastLedgerSequence = li + 75;
      const { signedBlob, address } = await deviceSigner(tx);
      const res = await client.submitAndWait(multisign([signedBlob]));
      const r: any = res.result;
      console.log(JSON.stringify({ ok: r.meta?.TransactionResult === "tesSUCCESS", result: r.meta?.TransactionResult,
        hash: r.hash, explorer: `https://testnet.xrpl.org/transactions/${r.hash}`, signer: address, validated: true }));
    } else {
      console.log("usage: multisign.ts address | sign <tx.json> | sweep <burner> <dest> <xrp> | fund <burner> <amount> <job> <tag>");
    }
  } catch (e: any) {
    console.log(`refused/failed: ${e?.data?.engine_result ?? e?.message ?? e}`);
    process.exitCode = 1;
  } finally { await client.disconnect(); }
}
main();
