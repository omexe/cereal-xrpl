"""Step 2 (software path): the treasury funds a burner with exactly the budget in RLUSD, tagged.

The demo path signs this same Payment on the Ledger device from ledger/ (clear-signed). Keep the fields identical.
"""
from __future__ import annotations

from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import Payment
from xrpl.wallet import Wallet

import json
import subprocess

from . import config
from .ledger import job_memo, rlusd, sign_submit, stamp


def funding_payment(treasury_addr: str, burner_addr: str, budget: str, job_id: str, tag: str) -> Payment:
    tx = Payment(account=treasury_addr, destination=burner_addr, amount=rlusd(budget))
    return stamp(tx, [job_memo(job_id, tag, kind="fund")])


def fund_burner(treasury: Wallet, burner_addr: str, budget: str, job_id: str, tag: str, c: JsonRpcClient) -> dict:
    return sign_submit(funding_payment(treasury.classic_address, burner_addr, budget, job_id, tag), treasury, c)


def fund_burner_on_device(burner_addr: str, budget: str, job_id: str, tag: str, timeout: int = 240) -> dict:
    """Demo path: the treasury's budget payment signed on the owner's Ledger (Speculos), clear-signed.

    Runs `npm --prefix ledger run fund`; the device is a signer on TREASURY (scripts/setup_demo_state.py step 4).
    Returns the same result shape as the software path, or {'ok': False, 'result': 'device_error', ...}.
    """
    cmd = ["npm", "--prefix", str(config.ROOT / "ledger"), "run", "--silent", "fund", "--",
           burner_addr, str(budget), job_id, tag]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    for line in reversed(p.stdout.strip().splitlines()):
        if line.startswith("{"):
            out = json.loads(line); out["signed_on"] = "ledger"; return out
    return {"ok": False, "result": "device_error", "error": (p.stdout + p.stderr)[-400:]}
