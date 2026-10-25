"""A05, A06: wallet names, folders, and presentation-only archiving. Metadata never touches payment policy.

Contract (frontend/src/api.ts):
    GET  /folders                         → [{id, name}]
    POST /folders  {name}                 → {ok, folder: {id, name}}
    POST /subagents/{id}/meta  {name?, folder?: str | null, archived?: bool} → {ok, wallet} | refusal
Archiving hides a wallet; it does not move funds or delete an account. A retired account stays retired.
"""
from fastapi import APIRouter

router = APIRouter()
