"""Step 2 (software path): the treasury funds a burner with exactly the budget in RLUSD, tagged.

The demo path signs this same Payment on the Ledger device from ledger/ (clear-signed). Keep the fields identical.
"""
from __future__ import annotations

from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import Payment
from xrpl.wallet import Wallet

from . import config
from .ledger import job_memo, rlusd, sign_submit, stamp


def funding_payment(treasury_addr: str, burner_addr: str, budget: str, job_id: str, tag: str) -> Payment:
    tx = Payment(account=treasury_addr, destination=burner_addr, amount=rlusd(budget))
    return stamp(tx, [job_memo(job_id, tag, kind="fund")])


def fund_burner(treasury: Wallet, burner_addr: str, budget: str, job_id: str, tag: str, c: JsonRpcClient) -> dict:
    return sign_submit(funding_payment(treasury.classic_address, burner_addr, budget, job_id, tag), treasury, c)


def fund_burner_on_device(burner_addr: str, budget: str, job_id: str, tag: str, c: JsonRpcClient | None = None,
                          decision: str | None = None) -> dict:
    """The main wallet's budget payment signed on the owner's Ledger (clear-signed); the device is the main wallet's
    signer (quorum 1). The service uses device.sign + device.submit_signed directly so it can ask before activation."""
    from . import device
    from .ledger import client
    c = c or client()
    return device.sign_submit(funding_payment(config.address("TREASURY"), burner_addr, budget, job_id, tag), c,
                              decision=decision)
