"""Part 2 demo beat, run as its own process: an attacker has stolen BOTH a subagent's key and cereal's co-signer key.

    python -m cereal.beats stolen-keys <deployment_id>

With both keys the attacker bypasses cereal's policy entirely, so the only limits left are the ledger's:
  1. they cannot take more than the subwallet holds: an over-balance payment fails on-ledger (tecPATH_PARTIAL);
  2. the stolen keys are not signers on the main wallet: a payment from it is refused (tef*), never applied.
Prints one JSON line per attempt. This simulates an attack for the demo; it is not part of the product path.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal

from xrpl.models.transactions import Payment

from . import config, deployments, keystore
from .ledger import client, multisign_submit, rlusd, rlusd_balance, stamp


def stolen_keys(dep_id: str) -> list[dict]:
    rec = deployments.get(dep_id)
    c = client()
    sub_key, cosign_key = keystore.load(dep_id), config.wallet("CEREAL_COSIGN")
    sink = config.address("VENDOR_B")  # any account that can hold RLUSD
    balance = rlusd_balance(c, rec["subwallet"])
    over = str(balance + Decimal("1"))
    out = []
    r = multisign_submit(stamp(Payment(account=rec["subwallet"], destination=sink, amount=rlusd(over)), []),
                         [sub_key, cosign_key], c)
    out.append({"attempt": "drain more than the subwallet holds", "amount": over, "balance": str(balance), **r})
    main = config.address("TREASURY")
    r = multisign_submit(stamp(Payment(account=main, destination=sink, amount=rlusd("1")), []),
                         [sub_key, cosign_key], c, quorum_signers=2)
    out.append({"attempt": "spend from the main wallet with the stolen keys", "amount": "1", **r})
    return out


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "stolen-keys":
        sys.exit("usage: python -m cereal.beats stolen-keys <deployment_id>")
    for item in stolen_keys(sys.argv[2]):
        print(json.dumps({"event": "stolen_keys", "data": item}, default=str), flush=True)


if __name__ == "__main__":
    main()
