"""The agent (step 7). Tools only; the agent never sees a seed, never calls the compiler, never signs alone.

The tool functions below are the contract. Wire them into Strands (AWS bounty) or the Anthropic SDK loop; the
planted instruction for the jailbreak beat lives in vendor A's response payload, and the only thing the agent
can do with it is call pay_vendor, which goes through the co-signer.
"""
from __future__ import annotations

from . import config, jobs, vendors
from .ledger import client, rlusd_balance
from .pay import pay as _pay


def check_vendor(address: str) -> dict:
    """Is this vendor credentialed by cereal? Reads the ledger."""
    return vendors.check(client(), address)


def budget_left(job_id: str) -> dict:
    job = jobs.get(job_id)
    return {"job": job_id, "remaining_rlusd": str(rlusd_balance(client(), job["burner"])), "expires_at": job["expires_at"]}


def pay_vendor(job_id: str, address: str, amount: str, invoice_id: str | None = None) -> dict:
    """Sign as the agent and ask cereal to co-sign. Returns a hash or a refusal with evidence."""
    return _pay(jobs.get(job_id), address, amount, config.wallet("AGENT"), client(), invoice_id)


TOOLS = [check_vendor, budget_left, pay_vendor]
