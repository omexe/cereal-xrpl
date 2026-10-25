"""A04: owner-approved funding for an existing wallet. Never automatic: one explicit request, one Ledger approval.

Contract (frontend/src/api.ts):
    POST /subagents/{id}/fund  {amount: str, request_id?: str, speculos_decision?: str}
        → {ok, amount, budget, balance, hashes: {trustline?, fund}, approval} | refusal
          (not_active, cap_exceeded, insufficient_main_balance, device_unavailable, owner_rejected, ...)
The work (approval first, then the trust-line raise, then the device-signed payment) is cereal/topup.py.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class FundRequest(BaseModel):
    amount: str                              # RLUSD as a decimal string, e.g. "0.25"
    request_id: str | None = None            # retrying with the same id returns the original result
    # Speculos demos only: which button the emulated owner presses (approve | reject). Ignored when a human is
    # driving the device (CEREAL_DEVICE_DECISION=manual); a real device always waits for its owner.
    speculos_decision: str | None = None


@router.post("/subagents/{dep_id}/fund")
def fund(dep_id: str, req: FundRequest) -> dict:
    from .. import topup
    decision = req.speculos_decision if req.speculos_decision in ("approve", "reject") else None
    out = topup.fund(dep_id, req.amount, req.request_id, decision)
    if out is None:
        raise HTTPException(404, "unknown deployment")
    return out
