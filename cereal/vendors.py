"""Part 2 — vendor trust as XLS-70 credentials: issue, accept, revoke, and the check the co-signer runs.

A vendor is trusted for a class (e.g. "data") when cereal's CREDENTIAL_ISSUER has issued it a credential of type
`cereal:vendor:<class>` and the vendor has accepted it. Revocation is a public CredentialDelete with a reason memo,
so one customer's report blocks the vendor for every cereal customer, and anyone can audit why.

CLI (vendor roles or raw addresses):
    python -m cereal.vendors check  VENDOR_B
    python -m cereal.vendors issue  VENDOR_B [--class data] [--days 30]
    python -m cereal.vendors accept VENDOR_B            # signed by the vendor's own key (demo vendors are ours)
    python -m cereal.vendors revoke VENDOR_B --reason overcharge [--report <ref>]
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from xrpl.clients import JsonRpcClient
from xrpl.models.requests import LedgerEntry
from xrpl.models.transactions import CredentialAccept, CredentialCreate, CredentialDelete, Memo
from xrpl.utils import datetime_to_ripple_time, str_to_hex
from xrpl.wallet import Wallet

from . import config
from .ledger import account_objects, account_tx, explorer, sign_submit, stamp

LSF_ACCEPTED = 0x00010000
REVOCATION_MEMO_TYPE = "cereal/vendor-revocation"


def ctype_hex(vendor_class: str = "data") -> str:
    return str_to_hex(f"cereal:vendor:{vendor_class}")


CTYPE_HEX = ctype_hex("data")  # kept for existing imports


def issue(issuer: Wallet, vendor_addr: str, c: JsonRpcClient, uri: str | None = None, vendor_class: str = "data",
          days: float | None = None) -> dict:
    exp = datetime_to_ripple_time(datetime.now(timezone.utc) + timedelta(days=days)) if days else None
    tx = CredentialCreate(account=issuer.classic_address, subject=vendor_addr, credential_type=ctype_hex(vendor_class),
                          uri=str_to_hex(uri) if uri else None, expiration=exp)
    return sign_submit(stamp(tx, []), issuer, c)


def accept(vendor: Wallet, issuer_addr: str, c: JsonRpcClient, vendor_class: str = "data") -> dict:
    tx = CredentialAccept(account=vendor.classic_address, issuer=issuer_addr, credential_type=ctype_hex(vendor_class))
    return sign_submit(stamp(tx, []), vendor, c)


def revoke(issuer: Wallet, vendor_addr: str, c: JsonRpcClient, reason: str, report_hash: str = "",
           vendor_class: str = "data") -> dict:
    """Blocked for every cereal customer at once: one public transaction with the reason in the memo."""
    memo = Memo(memo_data=str_to_hex(json.dumps({"reason": reason, "report": report_hash})),
                memo_type=str_to_hex(REVOCATION_MEMO_TYPE), memo_format=str_to_hex("application/json"))
    tx = CredentialDelete(account=issuer.classic_address, subject=vendor_addr, credential_type=ctype_hex(vendor_class))
    return sign_submit(stamp(tx, [memo]), issuer, c)


def revocation(c: JsonRpcClient, vendor_addr: str, issuer_addr: str | None = None,
               vendor_class: str = "data") -> dict | None:
    """The public evidence for a revoked vendor: the issuer's latest CredentialDelete for this subject and class."""
    issuer_addr = issuer_addr or config.address("CREDENTIAL_ISSUER")
    want = ctype_hex(vendor_class).upper()
    for t in account_tx(c, issuer_addr, limit=200):  # newest first
        tx = t["tx"]
        if tx.get("TransactionType") == "CredentialCreate" and tx.get("Subject") == vendor_addr \
                and tx.get("CredentialType", "").upper() == want:
            return None  # re-issued after the last revocation
        if tx.get("TransactionType") == "CredentialDelete" and tx.get("Subject") == vendor_addr \
                and tx.get("CredentialType", "").upper() == want:
            reason = {}
            for m in tx.get("Memos", []) or []:
                try:
                    reason = json.loads(bytes.fromhex(m["Memo"]["MemoData"]).decode())
                except (KeyError, ValueError):
                    pass
            return {"hash": t["hash"], "explorer": explorer(t["hash"]), "ledger_index": t.get("ledger_index"), **reason}
    return None


def check(c: JsonRpcClient, vendor_addr: str, issuer_addr: str | None = None, vendor_class: str = "data") -> dict:
    """What the co-signer reads before signing. Statuses: valid | pending | expired | revoked | none.

    Reads the ledger, not a database. `pending` = issued but not accepted by the vendor.
    """
    issuer_addr = issuer_addr or config.address("CREDENTIAL_ISSUER")
    want = ctype_hex(vendor_class)
    try:
        from xrpl.models.requests.ledger_entry import Credential  # xrpl-py 5.x
        res = c.request(LedgerEntry(credential=Credential(subject=vendor_addr, issuer=issuer_addr, credential_type=want))).result
        node = res.get("node") or {}
    except Exception:
        node = next((o for o in account_objects(c, vendor_addr, "credential")
                     if o.get("Issuer") == issuer_addr and o.get("CredentialType", "").upper() == want.upper()), None) or {}
    base = {"vendor": vendor_addr, "issuer": issuer_addr, "class": vendor_class}
    if not node:
        rev = revocation(c, vendor_addr, issuer_addr, vendor_class)
        return {"status": "revoked", **base, "revocation": rev} if rev else {"status": "none", **base}
    exp = node.get("Expiration")
    if exp and int(exp) <= datetime_to_ripple_time(datetime.now(timezone.utc)):
        return {"status": "expired", **base, "expiration": exp, "index": node.get("index")}
    accepted = bool(int(node.get("Flags", 0)) & LSF_ACCEPTED)
    return {"status": "valid" if accepted else "pending", **base, "index": node.get("index"), "expiration": exp}


def _addr(who: str) -> str:
    return who if who.startswith("r") and len(who) > 24 else config.address(who)


def main() -> None:
    import argparse
    from .ledger import client
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "issue", "accept", "revoke"])
    ap.add_argument("who", help="vendor role (VENDOR_A) or r-address")
    ap.add_argument("--class", dest="vendor_class", default="data")
    ap.add_argument("--days", type=float); ap.add_argument("--reason", default="policy"); ap.add_argument("--report", default="")
    a = ap.parse_args()
    c = client(); addr = _addr(a.who)
    if a.action == "check":
        out = check(c, addr, vendor_class=a.vendor_class)
    elif a.action == "issue":
        out = issue(config.wallet("CREDENTIAL_ISSUER"), addr, c, vendor_class=a.vendor_class, days=a.days)
    elif a.action == "accept":
        out = accept(config.wallet(a.who), config.address("CREDENTIAL_ISSUER"), c, vendor_class=a.vendor_class)
    else:
        out = revoke(config.wallet("CREDENTIAL_ISSUER"), addr, c, a.reason, a.report, vendor_class=a.vendor_class)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
