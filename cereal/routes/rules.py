"""A03: edit an existing wallet's spending rules.

Contract (frontend/src/api.ts):
    POST /subagents/{id}/rules/preview  RulesChange → {ok, changes: [...], problems: [...], notes: [...], rules}
    POST /subagents/{id}/rules          RulesChange → {ok, rules, changes, hashes?} | refusal
    RulesChange = {sentence?: str, spend?: str, expires_in_hours?: float, merchants?: [address],
                   approval_threshold?: str | null, sweep_when_done?: bool}
The budget is the balance: lowering the spend limit returns the excess on-ledger; raising it is refused
(use_add_funds) because only an owner-approved top-up can add money.
"""
from fastapi import APIRouter

router = APIRouter()
