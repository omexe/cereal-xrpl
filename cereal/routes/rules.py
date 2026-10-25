"""A03: edit an existing wallet's spending rules. The rules, their limits and their effects are in cereal/rules.py.

Contract (frontend/src/api.ts):
    POST /subagents/{id}/rules/preview  RulesChange → {ok, changes: [...], problems: [...], notes: [...], rules, returns, resolved_change}
                                        reads only: signs and sends nothing
    POST /subagents/{id}/rules          RulesChange → {ok, rules, changes, notes, hashes: {return?}, returned, explorer?,
                                        wallet} | refusal (not_active, use_add_funds, rules_problems, return_failed)
    RulesChange = {sentence?: str, spend?: str, expires_in_hours?: float, merchants?: [address],
                   approval_threshold?: str | null, sweep_when_done?: bool}   (a sentence or fields, never both)
The budget is the balance: lowering the spend limit returns the excess on-ledger; raising it is refused
(use_add_funds) because only an owner-approved top-up can add money. Unknown fields are rejected (422), never ignored.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

router = APIRouter()


class RulesChange(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a field we don't know is never silently dropped
    sentence: str | None = Field(default=None, max_length=1000)
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


# Browser-only demo wallets use the same AI interpreter, without reading or writing a ledger wallet.
class DemoConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    spend: float = Field(gt=0)
    days: float = Field(ge=1, le=365)
    merchants: list[str] = Field(min_length=1)
    approval: float = Field(ge=0)
    sweep: bool


class DemoRulesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sentence: str = Field(min_length=1, max_length=1000)
    name: str = Field(max_length=200)
    current: DemoConstraints


@router.post("/demo/rules/preview")
def demo_rules_preview(req: DemoRulesRequest) -> dict:
    from ..rule_intent import interpret
    current = req.current
    proposal = interpret(req.sentence, req.name, {
        "budget": str(current.spend), "approval_threshold": str(current.approval),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=current.days)).isoformat(),
        "allowed_payees": current.merchants, "sweep_when_done": current.sweep,
    }, [{"name": name, "address": name} for name in current.merchants])
    problems = proposal["problems"]
    draft = current.model_dump()
    for key, value in proposal["fields"].items():
        dest = {"spend": "spend", "expires_in_hours": "days", "approval_threshold": "approval",
                "sweep_when_done": "sweep"}[key]
        draft[dest] = value / 24 if key == "expires_in_hours" else value
    for op, names in proposal["merchants"]:
        if op == "only":
            draft["merchants"] = names
        elif op == "add":
            draft["merchants"] = list(dict.fromkeys([*draft["merchants"], *names]))
        else:
            removed = {name.casefold() for name in names}
            draft["merchants"] = [name for name in draft["merchants"] if name.casefold() not in removed]
    try:
        result = DemoConstraints.model_validate(draft).model_dump()
        if any(not name.strip() for name in result["merchants"]):
            problems.append("Name at least one allowed merchant.")
        if not problems and result == current.model_dump():
            problems.append("Nothing to change: these are already this wallet's rules.")
    except ValidationError:
        result = None
        problems.append("Use a positive spend limit, 1–365 days, at least one merchant, and a nonnegative approval threshold.")
    return {"ok": not problems, "problems": problems, "constraints": result if not problems else None}
