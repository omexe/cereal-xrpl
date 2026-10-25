"""Step 5: the co-sign service. POST /cosign {job_id, tx} → verify → co-sign → submit.

Checks, in order: the job exists and is active; the transaction is a Payment from that job's burner; the
destination holds a valid cereal vendor credential (read from the ledger); the amount is RLUSD and within the
remaining budget; the job has not expired; the memo tag matches the job. Refusals are returned with evidence.
Cereal never holds a budget and signs nothing but Payments from burners it created (and burns, see burn.py).

Run: uvicorn cereal.cosign:app --port 8001
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI
from pydantic import BaseModel
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.transactions.transaction import Transaction

from . import config, jobs, vendors
from .ledger import client, cosign_and_submit, decode_memos, rlusd_balance

app = FastAPI(title="cereal co-signer")


class CosignRequest(BaseModel):
    job_id: str
    tx: dict  # the agent-signed transaction, xrpl JSON (Signers present, SigningPubKey empty)


def refuse(reason: str, **evidence) -> dict:
    return {"ok": False, "refused": reason, **evidence}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "cosigner": config.address("CEREAL_COSIGN")}


@app.post("/cosign")
def cosign(req: CosignRequest) -> dict:
    job = jobs.get(req.job_id)
    if not job or job.get("status") not in ("created", "funded", "active"):
        return refuse("unknown_or_closed_job", job_id=req.job_id)
    tx = Transaction.from_xrpl(req.tx)
    if tx.transaction_type.value != "Payment" or tx.account != job["burner"]:
        return refuse("not_a_burner_payment", account=tx.account, type=tx.transaction_type.value)
    c = client()
    vendor = vendors.check(c, tx.destination)
    if vendor["status"] != "valid":
        return refuse("vendor_not_credentialed", vendor=vendor, hint="credential missing, pending or revoked on-ledger")
    amount = tx.amount
    if not isinstance(amount, IssuedCurrencyAmount) or amount.currency != config.RLUSD_CURRENCY:
        return refuse("not_rlusd", amount=str(amount))
    if amount.issuer != config.RLUSD_ISSUER:  # R01: the RLUSD code from any other issuer is a different token
        return refuse("wrong_issuer", issuer=amount.issuer, expected=config.RLUSD_ISSUER, currency=amount.currency)
    remaining = rlusd_balance(c, job["burner"])
    if Decimal(amount.value) > remaining:
        return refuse("over_budget", requested=amount.value, remaining=str(remaining))
    if datetime.now(timezone.utc) >= datetime.fromisoformat(job["expires_at"]):
        return refuse("job_expired", expires_at=job["expires_at"])
    memos = decode_memos(req.tx)
    if not memos or memos[0].get("tag") != job["tag"] or memos[0].get("job") != job["id"]:
        return refuse("tag_mismatch")
    result = cosign_and_submit(tx, config.wallet("CEREAL_COSIGN"), c)
    jobs.record_payment(job["id"], {"to": tx.destination, "amount": amount.value, **result,
                                    "at": datetime.now(timezone.utc).isoformat()})
    if result["ok"]:
        jobs.update(job["id"], status="active")
    return result
