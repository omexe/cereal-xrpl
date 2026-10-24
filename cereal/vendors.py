"""Step 4: vendor trust as XLS-70 credentials. Issue, accept, revoke, and the check the co-signer runs."""
from __future__ import annotations

import json

from xrpl.clients import JsonRpcClient
from xrpl.models.requests import LedgerEntry
from xrpl.models.transactions import CredentialAccept, CredentialCreate, CredentialDelete, Memo
from xrpl.utils import str_to_hex
from xrpl.wallet import Wallet

from . import config
from .ledger import account_objects, sign_submit, stamp

CTYPE_HEX = str_to_hex(config.VENDOR_CREDENTIAL_TYPE)
LSF_ACCEPTED = 0x00010000


def issue(issuer: Wallet, vendor_addr: str, c: JsonRpcClient, uri: str | None = None) -> dict:
    tx = CredentialCreate(account=issuer.classic_address, subject=vendor_addr, credential_type=CTYPE_HEX,
                          uri=str_to_hex(uri) if uri else None)
    return sign_submit(stamp(tx, []), issuer, c)


def accept(vendor: Wallet, issuer_addr: str, c: JsonRpcClient) -> dict:
    tx = CredentialAccept(account=vendor.classic_address, issuer=issuer_addr, credential_type=CTYPE_HEX)
    return sign_submit(stamp(tx, []), vendor, c)


def revoke(issuer: Wallet, vendor_addr: str, c: JsonRpcClient, reason: str, report_hash: str = "") -> dict:
    """Blocked for every cereal customer at once: one public transaction with the reason in the memo."""
    memo = Memo(memo_data=str_to_hex(json.dumps({"reason": reason, "report": report_hash})),
                memo_type=str_to_hex("cereal/vendor-revocation"), memo_format=str_to_hex("application/json"))
    tx = CredentialDelete(account=issuer.classic_address, subject=vendor_addr, credential_type=CTYPE_HEX)
    return sign_submit(stamp(tx, [memo]), issuer, c)


def revocation(c: JsonRpcClient, vendor_addr: str, issuer_addr: str | None = None) -> dict | None:
    """The public evidence for a revoked vendor: the issuer's CredentialDelete for this subject, with its reason."""
    from .ledger import account_tx, explorer
    issuer_addr = issuer_addr or config.address("CREDENTIAL_ISSUER")
    for t in account_tx(c, issuer_addr, limit=200):
        tx = t["tx"]
        if tx.get("TransactionType") == "CredentialDelete" and tx.get("Subject") == vendor_addr \
                and tx.get("CredentialType") in (CTYPE_HEX, CTYPE_HEX.upper()):
            reason = {}
            for m in tx.get("Memos", []) or []:
                try:
                    reason = json.loads(bytes.fromhex(m["Memo"]["MemoData"]).decode())
                except (KeyError, ValueError):
                    pass
            return {"hash": t["hash"], "explorer": explorer(t["hash"]), "ledger_index": t.get("ledger_index"), **reason}
    return None


def check(c: JsonRpcClient, vendor_addr: str, issuer_addr: str | None = None) -> dict:
    """What the co-signer reads before signing: valid / pending / none. Reads the ledger, not a database."""
    issuer_addr = issuer_addr or config.address("CREDENTIAL_ISSUER")
    try:
        from xrpl.models.requests.ledger_entry import Credential  # xrpl-py 5.x
        req = LedgerEntry(credential=Credential(subject=vendor_addr, issuer=issuer_addr, credential_type=CTYPE_HEX))
        res = c.request(req).result
        node = res.get("node") or {}
    except Exception:
        # Not found (or an older server): scan the vendor's credential objects.
        node = next((o for o in account_objects(c, vendor_addr, "credential")
                     if o.get("Issuer") == issuer_addr and o.get("CredentialType", "").upper() == CTYPE_HEX.upper()), None) or {}
    if not node:
        rev = revocation(c, vendor_addr, issuer_addr)
        return {"status": "revoked", "vendor": vendor_addr, "revocation": rev} if rev else {"status": "none", "vendor": vendor_addr}
    accepted = bool(int(node.get("Flags", 0)) & LSF_ACCEPTED)
    return {"status": "valid" if accepted else "pending", "vendor": vendor_addr, "issuer": issuer_addr,
            "index": node.get("index"), "expiration": node.get("Expiration")}
