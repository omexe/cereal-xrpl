// Device multisign: the Ledger (or Speculos) signs a transaction as ONE signer of a multisig account.
// Usage:
//   npx tsx multisign.ts address                       → prints the device address + pubkey (put LEDGER_ADDRESS in .env)
//   npx tsx multisign.ts sign  <unsigned-tx.json>      → one JSON line: Signer entry, blob with only this signer, device screens
//   DEVICE_DECISION=approve|reject|manual (Speculos): who presses the buttons; manual = a human in the Speculos UI or a real device
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
const SOURCE_TAG = Number(process.env.CEREAL_SOURCE_TAG ?? "2610250032");  // the hackathon's XRPL source tag
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
type Decision = "approve" | "reject" | "manual";
const DECISION = (process.env.DEVICE_DECISION ?? "approve") as Decision;
// Speculos only: press the buttons for the owner and record every screen the device showed (clear-signing evidence).
// "manual" presses nothing: a human approves in the Speculos UI (http://127.0.0.1:5000) or on a real device.
async function drive(stop: { done: boolean }, screens: string[]) {
  for (let i = 0; i < 120 && !stop.done; i++) {
    const s = await screen().catch(() => "");
    if (s && screens[screens.length - 1] !== s) screens.push(s);
    if (DECISION === "manual") { await sleep(500); continue; }
    const target = DECISION === "reject" ? /reject/i : /sign transaction|accept|approve/i;
    if (target.test(s) && (DECISION === "reject" || !/reject/i.test(s))) { await button("both"); await sleep(400); continue; }
    await button("right"); await sleep(250);
  }
}
// Speculos: a dropped connection can leave the XRP app halfway through a review, and every later request then fails
// with 0x6901 (busy). Before each signature and after any error, reject whatever is on screen until the app is idle.
async function ensureIdle(): Promise<boolean> {
  for (let i = 0; i < 40; i++) {
    const s = await screen().catch(() => "");
    if (/app is ready/i.test(s)) return true;
    if (/reject/i.test(s)) { await button("both"); await sleep(500); continue; }
    await button("right"); await sleep(250);
  }
  return /app is ready/i.test(await screen().catch(() => ""));
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
  if (DECISION !== "manual") await ensureIdle();
  const { signer, dmk } = await connect();
  const me = await completed<{ address: string; publicKey: string }>(signer.getAddress(PATH, { checkOnDevice: false }).observable);
  const pub = me.publicKey.toUpperCase();
  const unsigned: any = { ...tx, SigningPubKey: "" };
  delete unsigned.Signers; delete unsigned.TxnSignature;
  const blob = encode(unsigned);
  const stop = { done: false };
  const screens: string[] = [];
  const driver = drive(stop, screens);
  let sig: any;
  try { sig = await completed<any>(signer.signTransaction(PATH, hexaStringToBuffer(blob)!).observable); }
  catch (e: any) {
    const msg = String(e?.message ?? e);
    stop.done = true; await driver;
    if (DECISION !== "manual") await ensureIdle();  // never leave the app mid-review for the next request
    const rejected = DECISION === "reject" || /6985|refus|reject|denied|deny/i.test(msg);
    throw Object.assign(new Error(rejected ? "owner_rejected" : msg), { screens, rejected });
  }
  finally { stop.done = true; await driver; await dmk.close?.(); }
  const sigHex = (sig instanceof Uint8Array ? bufferToHexaString(sig) : (sig.r ? sig.r + sig.s : String(sig))).replace(/^0x/, "").toUpperCase();
  const entry = { Signer: { Account: me.address, SigningPubKey: pub, TxnSignature: sigHex } };
  const signedBlob = encode({ ...unsigned, Signers: [entry] });
  return { entry, signedBlob, address: me.address, screens };
}

async function main() {
  const [cmd, a, b, c] = process.argv.slice(2);
  if (cmd === "address") { console.log(JSON.stringify(await deviceAddress())); return; }
  const client = new Client(WS); await client.connect();
  try {
    if (cmd === "sign") {
      // sign <unsigned-tx.json>: one JSON line {ok, entry, signedBlob, address, screens} (or ok:false, result owner_rejected)
      const tx = JSON.parse(readFileSync(a, "utf8")) as Transaction;
      try { console.log(JSON.stringify({ ok: true, ...(await deviceSigner(tx)) })); }
      catch (e: any) {
        console.log(JSON.stringify({ ok: false, result: e?.rejected ? "owner_rejected" : "device_error",
                                     error: String(e?.message ?? e), screens: e?.screens ?? [] }));
        process.exitCode = 1;
      }
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
