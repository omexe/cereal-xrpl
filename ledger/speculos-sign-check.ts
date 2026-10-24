// Preflight: Node drives the Ledger DMK against Speculos (nanosp, XRP app):
// discover → connect → getAddress → fund from faucet → build Payment → sign on device → submit to testnet.
// Approval is automated through Speculos' HTTP button API (right = scroll, both = approve).
// Environment validation only. Not product code.
import { DeviceManagementKitBuilder, DeviceActionStatus, hexaStringToBuffer, bufferToHexaString } from "@ledgerhq/device-management-kit";
import { SignerXrpBuilder } from "@ledgerhq/device-signer-kit-xrp";
import { speculosIdentifier, speculosTransportFactory } from "@ledgerhq/device-transport-kit-speculos";
import { firstValueFrom, filter, type Observable } from "rxjs";
import { Client, encode, xrpToDrops, type Payment } from "xrpl";
import dotenv from "dotenv";
import { fileURLToPath } from "node:url";
dotenv.config({ path: fileURLToPath(new URL("../.env", import.meta.url)), quiet: true });

const SPECULOS = process.env.SPECULOS_URL ?? "http://127.0.0.1:5000";
const MODEL = process.env.SPECULOS_MODEL ?? "nanosp";
const PATH = "44'/144'/0'/0/0";
const WS = process.env.XRPL_TESTNET_WS_URL ?? "wss://s.altnet.rippletest.net:51233";
const DEST = process.env.TREASURY_ADDRESS!;

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
async function button(b: "left" | "right" | "both") {
  await fetch(`${SPECULOS}/button/${b}`, { method: "POST", body: JSON.stringify({ action: "press-and-release" }), headers: { "content-type": "application/json" } });
}
async function screen(): Promise<string> {
  const r = await fetch(`${SPECULOS}/events?currentscreenonly=true`);
  const j = await r.json() as { events: { text: string }[] };
  return j.events.map(e => e.text).join(" | ");
}
// Scroll right until the approve screen shows, then press both. Runs while the sign action is pending.
async function autoApprove(stop: { done: boolean }) {
  for (let i = 0; i < 60 && !stop.done; i++) {
    const s = await screen();
    if (/sign transaction|accept|approve/i.test(s) && !/reject/i.test(s)) { await button("both"); await sleep(400); continue; }
    await button("right"); await sleep(250);
  }
}
async function completed<T>(obs: Observable<any>): Promise<T> {
  const s = await firstValueFrom(obs.pipe(filter((st: any) => st.status === DeviceActionStatus.Completed || st.status === DeviceActionStatus.Error || st.status === DeviceActionStatus.Stopped)));
  if (s.status !== DeviceActionStatus.Completed) throw new Error(`device action ${s.status}: ${JSON.stringify(s.error ?? s)}`);
  return s.output as T;
}

const dmk = new DeviceManagementKitBuilder().addTransport(speculosTransportFactory(SPECULOS, false, MODEL as any)).build();
const device = await firstValueFrom(dmk.startDiscovering({ transport: speculosIdentifier }));
const sessionId = await dmk.connect({ device });
console.log(`connected to Speculos ${MODEL} (session ${sessionId.slice(0, 8)}…)`);
const signer = new SignerXrpBuilder({ dmk, sessionId }).build();

const addr = await completed<{ address: string; publicKey: string }>(signer.getAddress(PATH, { checkOnDevice: false }).observable);
console.log(`device address ${addr.address}  pubkey ${addr.publicKey.slice(0, 12)}…`);

const client = new Client(WS); await client.connect();
let bal: number | null = null;
try { bal = await client.getXrpBalance(addr.address); } catch { bal = null; }
if (bal === null || bal < 5) {
  const res = await fetch("https://faucet.altnet.rippletest.net/accounts", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ destination: addr.address }) });
  console.log(`faucet → ${res.status}`); await sleep(6000);
  bal = await client.getXrpBalance(addr.address);
}
console.log(`device account balance ${bal} XRP`);

const tx = await client.autofill<Payment>({
  TransactionType: "Payment", Account: addr.address, Destination: DEST, Amount: xrpToDrops("1"),
  SigningPubKey: addr.publicKey.toUpperCase(), LastLedgerSequence: (await client.getLedgerIndex()) + 150,
  Memos: [{ Memo: { MemoData: Buffer.from(JSON.stringify({ agent_id: "preflight", action: "speculos-sign-check" })).toString("hex").toUpperCase() } }],
});
const unsigned = encode(tx);
const stop = { done: false };
const approving = autoApprove(stop);
const sig = await completed<Uint8Array>(signer.signTransaction(PATH, hexaStringToBuffer(unsigned)!).observable);
stop.done = true; await approving;
const signed = encode({ ...tx, TxnSignature: bufferToHexaString(sig, false).toUpperCase() });
const sub = await client.submitAndWait(signed);
const meta = sub.result.meta as any;
console.log(`submitted: ${meta?.TransactionResult}  hash ${sub.result.hash}`);
console.log(`explorer: https://testnet.xrpl.org/transactions/${sub.result.hash}`);
await client.disconnect(); dmk.close();
process.exit(meta?.TransactionResult === "tesSUCCESS" ? 0 : 1);
