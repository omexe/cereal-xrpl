"""Part 3: the owner's Ledger as a multisig signer.

Python builds and prepares the transaction, the device signs it clear-signed (ledger/multisign.ts over DMK; Speculos
today), Python submits. The device is a signer in two places:
  * the main wallet (signer list {Ledger}): it approves each subagent's budget before anything touches the ledger;
  * every subwallet (signer list {subagent 1, cereal 1, Ledger 2}, quorum 2): it alone can take the money back.
Device facts: pass encode(tx) with an empty SigningPubKey and no Signers; the XRP app adds the multisign prefix and
its own AccountID. Clear-signs Payment, TrustSet, SignerListSet, AccountSet, AccountDelete.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request

from xrpl.clients import JsonRpcClient
from xrpl.core.binarycodec import decode
from xrpl.models.transactions.transaction import Transaction

from . import config
from .ledger import prepare, submit_capture

NOISE = re.compile(r"app is ready|transaction signed|^back$|^cancel$|^reject transaction$", re.I)


def screens_summary(screens: list[str]) -> list[str]:
    """What the owner saw on the device, in order: "Label: value" per field, long values re-joined, no noise."""
    out: list[str] = []
    for s in screens:
        parts = [x.strip() for x in s.split("|") if x.strip()]
        if not parts or NOISE.search(" ".join(parts)):
            continue
        line = parts[0] if len(parts) == 1 else f"{parts[0]}: {''.join(parts[1:])}"
        if line not in out:
            out.append(line)
    return out


def available(timeout: float = 2.0) -> bool:
    """Is the device (Speculos) reachable? Checked before any deploy that needs an approval."""
    try:
        urllib.request.urlopen(f"{config.SPECULOS_URL}/events?currentscreenonly=true", timeout=timeout).read()
        return True
    except Exception:
        return False


def sign(filled: Transaction, decision: str | None = None, timeout: int = 600) -> dict:
    """Ask the device to sign an already-prepared transaction as a multisig signer.

    decision: approve | reject | manual (Speculos button driver; manual waits for a human). Returns
    {ok, entry, signedBlob, address, screens} or {ok: False, result: owner_rejected | device_error, screens}.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(filled.to_xrpl(), f)
    env = {**os.environ, "DEVICE_DECISION": decision or config.DEVICE_DECISION, "SPECULOS_URL": config.SPECULOS_URL}
    try:
        p = subprocess.run(["npm", "--prefix", str(config.ROOT / "ledger"), "run", "--silent", "sign", "--", f.name],
                           capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": "device_timeout", "screens": []}
    finally:
        os.unlink(f.name)
    for line in reversed(p.stdout.strip().splitlines()):
        if line.startswith("{"):
            out = json.loads(line)
            out["screens"] = screens_summary(out.get("screens", []))
            return out
    return {"ok": False, "result": "device_error", "error": (p.stdout + p.stderr)[-400:], "screens": []}


def submit_signed(signed: dict, c: JsonRpcClient, **kw) -> dict:
    """Submit a blob that carries the device's signature (and, for quorum, enough weight on its own)."""
    r = submit_capture(Transaction.from_xrpl(decode(signed["signedBlob"])), c, **kw)
    return {**r, "signed_on": "ledger", "signer": signed["address"], "screens": signed.get("screens", [])}


def sign_submit(tx: Transaction, c: JsonRpcClient, *, decision: str | None = None,
                window: int = config.DEVICE_WINDOW_LEDGERS, **kw) -> dict:
    """Prepare (fee for one multisig signer), sign on the device, submit. The device's weight must meet the quorum."""
    filled = prepare(tx, c, signers_count=1, window=window)
    signed = sign(filled, decision)
    if not signed.get("ok"):
        return {"ok": False, "result": signed.get("result"), "hash": None, "screens": signed.get("screens", []),
                "error": signed.get("error")}
    return submit_signed(signed, c, **kw)
