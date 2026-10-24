"""Idempotent ledger setup for the demo. Safe to rerun; never prints seeds.

  1. RLUSD trust lines on TREASURY, VENDOR_A, VENDOR_B, VENDOR_C
  2. testnet RLUSD for TREASURY from the RippleX faucet (tryrlusd.com, 10 RLUSD per claim, rate-limited)
  3. vendor credentials: issue to A, B and C, accept by all three, then revoke B with a reason memo
  4. the owner's Ledger (LEDGER_ADDRESS) as a signer on TREASURY (quorum 1; master kept as the software fallback)

Usage: python scripts/setup_demo_state.py [--claims N] [--skip-faucet] [--skip-revoke]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xrpl.models.transactions import SignerListSet, TrustSet  # noqa: E402
from xrpl.models.transactions.signer_list_set import SignerEntry  # noqa: E402

from cereal import config, vendors  # noqa: E402
from cereal.ledger import account_objects, client, rlusd, rlusd_balance, sign_submit, stamp  # noqa: E402

FAUCET = "https://tryrlusd.com/api/mint-xrpl"


def has_rlusd_line(c, addr: str) -> bool:
    from xrpl.models.requests import AccountLines
    return any(l.get("account") == config.RLUSD_ISSUER and l.get("currency") == config.RLUSD_CURRENCY
               for l in c.request(AccountLines(account=addr)).result.get("lines", []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", type=int, default=3)
    ap.add_argument("--skip-faucet", action="store_true")
    ap.add_argument("--skip-revoke", action="store_true")
    args = ap.parse_args()
    c = client()

    print("1. trust lines")
    for role in ("TREASURY", "VENDOR_A", "VENDOR_B", "VENDOR_C"):
        addr = config.address(role)
        if has_rlusd_line(c, addr):
            print(f"   {role:9s} already has an RLUSD line")
            continue
        r = sign_submit(stamp(TrustSet(account=addr, limit_amount=rlusd("1000000"), flags=0x00040000), []),
                        config.wallet(role), c)
        print(f"   {role:9s} TrustSet {r['result']} {r.get('hash')}")

    print("2. RLUSD for TREASURY")
    treasury = config.address("TREASURY")
    print(f"   balance before: {rlusd_balance(c, treasury)}")
    if not args.skip_faucet:
        for i in range(args.claims):
            resp = requests.post(FAUCET, json={"address": treasury}, timeout=60)
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            print(f"   claim {i + 1}: HTTP {resp.status_code} {body.get('txHash') or body.get('error') or ''}")
            if resp.status_code != 200:
                break
            time.sleep(5)
    time.sleep(5)
    print(f"   balance after:  {rlusd_balance(c, treasury)}")

    print("3. vendor credentials")
    issuer = config.wallet("CREDENTIAL_ISSUER")
    for role in ("VENDOR_A", "VENDOR_B", "VENDOR_C"):
        addr = config.address(role)
        st = vendors.check(c, addr)
        if st["status"] in ("valid",):
            print(f"   {role} already valid")
            continue
        if st["status"] == "revoked" and role == "VENDOR_B":
            print(f"   {role} already revoked: {st['revocation']['hash']}")
            continue
        if st["status"] in ("none", "revoked"):
            r = vendors.issue(issuer, addr, c)
            print(f"   {role} CredentialCreate {r['result']} {r.get('hash')}")
        r = vendors.accept(config.wallet(role), issuer.classic_address, c)
        print(f"   {role} CredentialAccept {r['result']} {r.get('hash')}")
    if not args.skip_revoke and vendors.check(c, config.address("VENDOR_B"))["status"] == "valid":
        r = vendors.revoke(issuer, config.address("VENDOR_B"), c, reason="overcharge",
                           report_hash="customer-report:invoice-0042")
        print(f"   VENDOR_B CredentialDelete {r['result']} {r.get('hash')}")
    for role in ("VENDOR_A", "VENDOR_B", "VENDOR_C"):
        st = vendors.check(c, config.address(role))
        print(f"   {role}: {st['status']}" + (f"  evidence {st['revocation']['hash']}" if st.get("revocation") else ""))

    print("4. Ledger as a signer on TREASURY")
    if not config.LEDGER_ADDRESS:
        print("   LEDGER_ADDRESS not set; skipped (cd ledger && npm run address)")
    else:
        lists = account_objects(c, treasury, "signer_list")
        current = [e["SignerEntry"]["Account"] for e in lists[0].get("SignerEntries", [])] if lists else []
        if config.LEDGER_ADDRESS in current:
            print("   already a signer")
        else:
            tx = SignerListSet(account=treasury, signer_quorum=1,
                               signer_entries=[SignerEntry(account=config.LEDGER_ADDRESS, signer_weight=1)])
            r = sign_submit(stamp(tx, []), config.wallet("TREASURY"), c)
            print(f"   SignerListSet {r['result']} {r.get('hash')}")


if __name__ == "__main__":
    main()
