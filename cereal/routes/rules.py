"""A03: edit an existing wallet's spending rules. The rules, their limits and their effects are in cereal/rules.py.

Contract (frontend/src/api.ts):
    POST /subagents/{id}/rules/preview  RulesChange → {ok, changes: [...], problems: [...], notes: [...], rules, returns}
                                        reads only: signs and sends nothing
    POST /subagents/{id}/rules          RulesChange → {ok, rules, changes, notes, hashes: {return?}, returned, explorer?,
                                        wallet} | refusal (not_active, use_add_funds, rules_problems, return_failed)
    RulesChange = {sentence?: str, spend?: str, expires_in_hours?: float, merchants?: [address],
                   approval_threshold?: str | null, sweep_when_done?: bool}   (a sentence or fields, never both)
The budget is the balance: lowering the spend limit returns the excess on-ledger; raising it is refused
(use_add_funds) because only an owner-approved top-up can add money. Unknown fields are rejected (422), never ignored.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class RulesChange(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a field we don't know is never silently dropped
    sentence: str | None = None
    spend: str | float | int | None = None
    expires_in_hours: float | None = None
    merchants: list[str] | None = None
    approval_threshold: str | float | int | None = None  # null = no wallet threshold (company default only)
    sweep_when_done: bool | None = None


def _change(req: RulesChange) -> dict:
    out = {}
    for k in req.model_fields_set:
        v = getattr(req, k)
        out[k] = str(v) if k in ("spend", "approval_threshold") and isinstance(v, (int, float)) else v
    return out


def _known(dep_id: str) -> None:
    from .. import deployments
    if not deployments.get(dep_id):
        raise HTTPException(404, "unknown deployment")


@router.post("/subagents/{dep_id}/rules/preview")
def rules_preview(dep_id: str, req: RulesChange) -> dict:
    """What this change would do, what's wrong with it, and what to know. Signs and sends nothing."""
    from .. import rules
    _known(dep_id)
    return rules.preview(dep_id, _change(req))


@router.post("/subagents/{dep_id}/rules")
def rules_apply(dep_id: str, req: RulesChange) -> dict:
    """Re-validate and persist. A lower spend limit first returns the excess to the main wallet on-ledger."""
    from .. import rules
    _known(dep_id)
    return rules.apply(dep_id, _change(req))
