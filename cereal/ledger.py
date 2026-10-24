"""Shared ledger plumbing: client, explicit fee + expiry, tagged memos, multisign submit with refusal capture.

Every module goes through here so that every transaction carries SourceTag + Memos, an explicit fee and
LastLedgerSequence, and every refusal (tef*/tec*/ter*) is returned as a result, never swallowed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from decimal import Decimal
from typing import Any, Iterable

from xrpl.clients import JsonRpcClient
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountInfo, AccountLines, AccountObjects, AccountTx, Ledger
from xrpl.models.transactions import Memo
from xrpl.models.transactions.transaction import Transaction
from xrpl.transaction import XRPLReliableSubmissionException, autofill, multisign, sign, submit_and_wait
from xrpl.utils import hex_to_str, str_to_hex
from xrpl.wallet import Wallet

from . import config

MEMO_TYPE = "cereal/job"
RESULT_RE = re.compile(r"\b(te[cfmlr][A-Z_]+)")


def client() -> JsonRpcClient:
    return JsonRpcClient(config.RPC_URL)


def ledger_index(c: JsonRpcClient) -> int:
    return int(c.request(Ledger(ledger_index="validated")).result["ledger_index"])


def explorer(tx_hash: str) -> str:
    return f"{config.EXPLORER}/transactions/{tx_hash}"


def rlusd(value: str | int | float | Decimal) -> IssuedCurrencyAmount:
    return IssuedCurrencyAmount(currency=config.RLUSD_CURRENCY, issuer=config.RLUSD_ISSUER, value=str(value))


# ---- tags and memos -------------------------------------------------------------------------

def job_tag(team: str, project: str, task: str) -> str:
    """Private, deterministic tag for a team/project/task triple. Only cereal can map it back."""
    msg = f"{team}|{project}|{task}".encode()
    return hmac.new(config.TAG_HMAC_KEY, msg, hashlib.sha256).hexdigest()[:32]


def job_memo(job_id: str, tag: str, **extra: Any) -> Memo:
    data = json.dumps({"tag": tag, "job": job_id, **extra}, separators=(",", ":"))
    return Memo(memo_data=str_to_hex(data), memo_type=str_to_hex(MEMO_TYPE), memo_format=str_to_hex("application/json"))


def decode_memos(tx_json: dict) -> list[dict]:
    """Return every cereal memo on a transaction as a dict (others are ignored)."""
    out = []
    for m in tx_json.get("Memos", []) or []:
        memo = m.get("Memo", {})
        try:
            if hex_to_str(memo.get("MemoType", "")) != MEMO_TYPE:
                continue
            out.append(json.loads(hex_to_str(memo["MemoData"])))
        except (ValueError, KeyError):
            continue
    return out


def stamp(tx: Transaction, memos: Iterable[Memo]) -> Transaction:
    """Attach cereal's SourceTag and memos to any transaction."""
    d = tx.to_dict()
    d["source_tag"] = config.SOURCE_TAG
    d["memos"] = [m.to_dict() for m in memos]
    return Transaction.from_dict(d)


# ---- preparation and submission -------------------------------------------------------------

def prepare(tx: Transaction, c: JsonRpcClient, *, signers_count: int | None = None,
            window: int = config.APPROVAL_WINDOW_LEDGERS) -> Transaction:
    """Autofill (sequence, explicit fee sized for signers_count) and set a ~5-minute LastLedgerSequence."""
    filled = autofill(tx, c, signers_count=signers_count)
    d = filled.to_dict()
    d["last_ledger_sequence"] = ledger_index(c) + window
    return Transaction.from_dict(d)


def submit_capture(signed: Transaction, c: JsonRpcClient, *, fail_hard: bool = False) -> dict:
    """Submit and wait. Returns {'ok', 'result', 'hash', 'explorer'}; refusals come back as results."""
    try:
        r = submit_and_wait(signed, c, autofill=False, check_fee=False, fail_hard=fail_hard).result
        result = r.get("meta", {}).get("TransactionResult", r.get("engine_result", "?"))
        return {"ok": result == "tesSUCCESS", "result": result, "hash": r.get("hash"),
                "explorer": explorer(r["hash"]) if r.get("hash") else None, "validated": r.get("validated", False)}
    except XRPLReliableSubmissionException as e:
        m = RESULT_RE.search(str(e))
        return {"ok": False, "result": m.group(1) if m else "failed", "hash": None, "explorer": None,
                "validated": False, "error": str(e)}


def sign_submit(tx: Transaction, w: Wallet, c: JsonRpcClient, **kw: Any) -> dict:
    """Single-signer path (treasury funding fallback, credential issuer, vendor accept)."""
    return submit_capture(sign(prepare(tx, c), w), c, **kw)


def multisign_submit(tx: Transaction, signers: list[Wallet], c: JsonRpcClient, *, quorum_signers: int | None = None,
                     **kw: Any) -> dict:
    """Multi-sign with the given wallets and submit. Pass ONE wallet to reproduce the tefBAD_QUORUM refusal.

    quorum_signers sizes the fee (defaults to len(signers)); the refusal demo should size for 2 so the
    only thing wrong with the transaction is the missing signature.
    """
    filled = prepare(tx, c, signers_count=quorum_signers or len(signers))
    parts = [sign(filled, w, multisign=True) for w in signers]
    return submit_capture(multisign(filled, parts), c, **kw)


def cosign_and_submit(agent_signed: Transaction, cosigner: Wallet, c: JsonRpcClient) -> dict:
    """Take a transaction the agent already signed as a multisig signer, add cereal's signature, submit."""
    d = agent_signed.to_dict()
    d.pop("signers", None)
    base = Transaction.from_dict(d)
    ours = sign(base, cosigner, multisign=True)
    return submit_capture(multisign(base, [agent_signed, ours]), c)


# ---- reads ----------------------------------------------------------------------------------

def account_info(c: JsonRpcClient, addr: str) -> dict:
    return c.request(AccountInfo(account=addr, ledger_index="validated")).result["account_data"]


def account_objects(c: JsonRpcClient, addr: str, type_: str | None = None) -> list[dict]:
    req = AccountObjects(account=addr, type=type_) if type_ else AccountObjects(account=addr)
    return c.request(req).result.get("account_objects", [])


def rlusd_balance(c: JsonRpcClient, addr: str) -> Decimal:
    for line in c.request(AccountLines(account=addr)).result.get("lines", []):
        if line.get("currency") in (config.RLUSD_CURRENCY, "RLUSD") and line.get("account") == config.RLUSD_ISSUER:
            return Decimal(line["balance"])
    return Decimal(0)


def account_tx(c: JsonRpcClient, addr: str, limit: int = 400) -> list[dict]:
    """Validated transactions for an account; each item normalised to {'tx': ..., 'meta': ..., 'hash': ...}."""
    res = c.request(AccountTx(account=addr, limit=limit)).result
    out = []
    for t in res.get("transactions", []):
        tx = t.get("tx_json") or t.get("tx") or {}
        out.append({"tx": tx, "meta": t.get("meta"), "hash": t.get("hash") or tx.get("hash"),
                    "ledger_index": t.get("ledger_index") or tx.get("ledger_index")})
    return out
