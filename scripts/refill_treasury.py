"""Demo plumbing, testnet only: move the RLUSD our own test vendors earned back to the main wallet (TREASURY).

In real life a vendor is somebody else's business and cereal never holds its keys. Here every vendor account is ours
(VENDOR_A..E in .env), so their earnings can go back into the main wallet and the demo never runs out of RLUSD.
This script is not part of the cereal service. Never prints seeds.

    .venv/bin/python scripts/refill_treasury.py            # sweep every vendor's RLUSD home
    .venv/bin/python scripts/refill_treasury.py --below 5  # only if the main wallet holds less than 5 RLUSD
    .venv/bin/python scripts/refill_treasury.py --dry-run  # show what would move
"""
import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xrpl.models.transactions import Payment  # noqa: E402

from cereal import config  # noqa: E402
from cereal.ledger import client, job_memo, rlusd, rlusd_balance, sign_submit, stamp  # noqa: E402

VENDORS = ["VENDOR_A", "VENDOR_B", "VENDOR_C", "VENDOR_D", "VENDOR_E", "VENDOR_G"]

ap = argparse.ArgumentParser()
ap.add_argument("--below", type=Decimal, default=None, help="only refill when the main wallet holds less than this")
ap.add_argument("--keep", type=Decimal, default=Decimal("0"), help="RLUSD each vendor keeps")
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()

c = client()
if "altnet" not in str(c.url) and "testnet" not in str(c.url).lower() and not os.getenv("QUICKNODE_XRPL_HTTP"):
    sys.exit(f"refusing: {c.url} does not look like XRPL testnet")
treasury = config.address("TREASURY")
before = rlusd_balance(c, treasury)
print(f"main wallet {treasury}: {before} RLUSD")
if a.below is not None and before >= a.below:
    sys.exit(f"nothing to do: {before} >= {a.below}")
moved = Decimal(0)
for role in VENDORS:
    try:
        w = config.wallet(role)
    except Exception:
        continue  # no seed for this role in .env
    amount = rlusd_balance(c, w.classic_address) - a.keep
    if amount <= 0:
        continue
    if a.dry_run:
        print(f"  would move {amount} RLUSD from {role} {w.classic_address}")
        continue
    tx = stamp(Payment(account=w.classic_address, destination=treasury, amount=rlusd(str(amount)),
                       source_tag=config.SOURCE_TAG), [job_memo("treasury-refill", "demo", kind="refill")])
    r = sign_submit(tx, w, c)
    print(f"  {role}: {amount} RLUSD {r.get('result')} {config.EXPLORER}/transactions/{r.get('hash')}")
    if r.get("ok"):
        moved += amount
if not a.dry_run:
    print(f"moved {moved} RLUSD; main wallet now {rlusd_balance(c, treasury)} RLUSD")
