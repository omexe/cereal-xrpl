"""A01, A02, A07: start a wallet's task from the API and track the run (the logic and its cleanup policy: cereal/runs.py).

Contract (frontend/src/api.ts):
    POST /subagents/{id}/run  {}            → {ok, run: Run} | refusal (not_active, expired, already_running,
                                              balance_unavailable, nothing_to_buy, already_bought,
                                              no_trusted_vendor, over_budget)
    GET  /subagents/{id}/run                → {ok, run: Run | null}
    Run = {id, deployment, status: starting|running|succeeded|failed|timed_out|interrupted,
           started_at, finished_at, exit_code, plan, summary, error}
Creating a wallet never starts its task; only this endpoint does.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/subagents/{dep_id}/run")
def start_run(dep_id: str) -> dict:
    from .. import runs
    out = runs.start(dep_id)
    if out.get("refused") == "unknown_deployment":
        raise HTTPException(404, "unknown deployment")
    return out


@router.get("/subagents/{dep_id}/run")
def get_run(dep_id: str) -> dict:
    from .. import runs
    out = runs.current(dep_id)
    if out.get("refused") == "unknown_deployment":
        raise HTTPException(404, "unknown deployment")
    return out
