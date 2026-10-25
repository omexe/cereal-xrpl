"""A01, A02, A07: start a wallet's task from the API and track the run.

Contract (frontend/src/api.ts):
    POST /subagents/{id}/run  {}            → {ok, run: Run} | refusal (not_active, already_running, nothing_to_buy)
    GET  /subagents/{id}/run                → {ok, run: Run | null}
    Run = {id, deployment, status: starting|running|succeeded|failed|timed_out|interrupted,
           started_at, finished_at, exit_code, plan, summary, error}
Creating a wallet never starts its task; only this endpoint does.
"""
from fastapi import APIRouter

router = APIRouter()
