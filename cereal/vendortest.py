"""One-command proof that vendor lists and blacklisting work, live on XRPL testnet.

    make vendor-test          (needs the cereal service on :8001 and the Ledger emulator)

1. create a wallet from "only at Vendor C" (the owner's Ledger approves the budget)
2. pay Vendor C                 → paid (it is on the list and trusted)
3. pay Vendor A                 → refused: trusted, but not on this wallet's list
4. pay Vendor B                 → refused: blacklisted (credential publicly revoked)
5. pay a brand-new address      → refused: no credential at all
6. blacklist Vendor C live      → one public CredentialDelete; paying C is now refused, citing that transaction
7. restore Vendor C             → re-issued and accepted; paying C works again
8. finish                       → leftovers sweep back to the main wallet
Every refusal is checked to have sent nothing (the subwallet's Sequence does not move). Vendor C is always restored,
even if a step fails. Prints a pass/fail table with explorer links and writes the evidence to exports/.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import requests
from xrpl.wallet import Wallet

from . import config, vendors
from .ledger import account_info, client

EXPLORER = config.EXPLORER


def _tx(h):
    return f"{EXPLORER}/transactions/{h}" if h else ""


def _seq(c, addr):
    return int(account_info(c, addr)["Sequence"])


def run() -> int:
    c = client()
    url = config.SERVICE_URL
    A, B, C = config.address("VENDOR_A"), config.address("VENDOR_B"), config.address("VENDOR_C")
    issuer = config.wallet("CREDENTIAL_ISSUER")
    rows, ev = [], {"started": datetime.now(timezone.utc).isoformat()}

    def row(step, expected, got, ok, proof="", note=""):
        rows.append({"step": step, "expected": expected, "got": got, "result": "PASS" if ok else "FAIL",
                     "proof": proof, "note": note})
        print(f"  {'PASS' if ok else 'FAIL'}  {step}: {got}" + (f"  {proof}" if proof else ""), flush=True)

    if vendors.check(c, C)["status"] != "valid":
        sys.exit("Vendor C must start trusted (python scripts/setup_demo_state.py)")
    print("vendor rules test, live on XRPL testnet\n")
    sentence = "Vendor rules test: spend up to 0.5 RLUSD over 1 hour, only at Vendor C. Sweep back when done."
    w = requests.post(f"{url}/wallets", json={"sentence": sentence, "folder": "Tests"}, timeout=900).json()
    ok = bool(w.get("ok")) and w.get("allowed_payees") == [C]
    row("1 create wallet 'only at Vendor C'", "created, owner approved on Ledger, may pay C only",
        f"{w.get('id')} approved on Ledger, may pay {len(w.get('allowed_payees') or [])} vendor" if w.get("ok") else str(w.get("refused")),
        ok, _tx((w.get("hashes") or {}).get("fund")))
    if not w.get("ok"):
        return _finish(rows, ev)
    from .subagent import Subagent
    s = Subagent(w["id"])
    sub = w["subwallet"]
    revoked_c = False

    def refused(step, payee, amount, want_code, want_status=None, want_hash=None):
        before = _seq(c, sub)
        r = s.pay(payee, amount)
        code = r.get("refused") or r.get("result")
        v = r.get("vendor") or {}
        rev = (v.get("revocation") or {}).get("hash")
        nothing_sent = _seq(c, sub) == before
        good = code == want_code and nothing_sent and (want_status is None or v.get("status") == want_status) \
            and (want_hash is None or rev == want_hash)
        got = f"refused: {code}" + (f" (vendor {v.get('status')})" if v.get("status") else "") + \
              ("; nothing sent" if nothing_sent else "; A TRANSACTION WAS SENT")
        row(step, f"refused: {want_code}" + (f" ({want_status})" if want_status else ""), got, good, _tx(rev))
        return r

    try:
        r = s.pay(C, "0.15")
        row("2 pay Vendor C 0.15", "paid", f"paid: {r.get('result')}", r.get("result") == "tesSUCCESS", _tx(r.get("hash")))
        refused("3 pay Vendor A 0.05 (trusted, not on the list)", A, "0.05", "payee_not_allowed")
        refused("4 pay Vendor B 0.05 (blacklisted)", B, "0.05", "vendor_not_credentialed", "revoked",
                (vendors.check(c, B).get("revocation") or {}).get("hash"))
        unknown = Wallet.create().classic_address
        refused(f"5 pay a brand-new address {unknown[:8]}… 0.05", unknown, "0.05", "vendor_not_credentialed", "none")

        rv = vendors.revoke(issuer, C, c, reason="vendor rules test: live blacklist", report_hash=f"vendortest-{w['id']}")
        revoked_c = bool(rv.get("ok"))
        row("6a blacklist Vendor C (public CredentialDelete)", "revoked on-ledger",
            f"{rv.get('result')}", rv.get("result") == "tesSUCCESS", _tx(rv.get("hash")))
        refused("6b pay Vendor C 0.05 after the blacklist", C, "0.05", "vendor_not_credentialed", "revoked", rv.get("hash"))
    finally:
        if revoked_c or vendors.check(c, C)["status"] != "valid":
            iss = vendors.issue(issuer, C, c)
            acc = vendors.accept(config.wallet("VENDOR_C"), issuer.classic_address, c)
            restored = vendors.check(c, C)["status"] == "valid"
            row("7a restore Vendor C (issue + accept)", "trusted again",
                f"issue {iss.get('result')}, accept {acc.get('result')}, status {vendors.check(c, C)['status']}",
                restored, _tx(acc.get("hash")))
    r = s.pay(C, "0.05")
    row("7b pay Vendor C 0.05 after the restore", "paid", f"paid: {r.get('result')}", r.get("result") == "tesSUCCESS",
        _tx(r.get("hash")))
    d = requests.post(f"{url}/subagents/{w['id']}/done", json={"summary": "vendor rules test"}, timeout=600).json()
    sw = d.get("swept") or {}
    row("8 finish: sweep leftovers home", "0.30 RLUSD returned", f"returned {sw.get('returned')}",
        bool(sw.get("ok")) and sw.get("returned") in ("0.3", "0.30"))
    ev["wallet"] = w["id"]
    return _finish(rows, ev)


def _finish(rows, ev) -> int:
    passed = sum(r["result"] == "PASS" for r in rows)
    print(f"\n{passed} of {len(rows)} passed\n")
    w1 = max(len(r["step"]) for r in rows)
    print(f"{'step'.ljust(w1)}  result  proof")
    for r in rows:
        print(f"{r['step'].ljust(w1)}  {r['result']:6s}  {r['proof']}")
    ev.update({"finished": datetime.now(timezone.utc).isoformat(), "rows": rows})
    out = config.ROOT / "exports" / f"vendor-test-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(ev, indent=2))
    print(f"\nevidence: {out}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(run())
