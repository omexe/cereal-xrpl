"""A04: owner-approved funding for an existing wallet. Never automatic: one explicit request, one Ledger approval.

Contract (frontend/src/api.ts):
    POST /subagents/{id}/fund  {amount: str, request_id?: str, speculos_decision?: str}
        → {ok, amount, budget, balance, hashes: {trustline?, fund}, approval} | refusal
          (not_active, cap_exceeded, insufficient_main_balance, device_unavailable, owner_rejected, ...)
"""
from fastapi import APIRouter

router = APIRouter()
