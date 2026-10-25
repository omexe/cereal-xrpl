"""A01, A02, A07: start a wallet's task from the API and track the run (the logic and its cleanup policy: cereal/runs.py).

Contract (frontend/src/api.ts):
    POST /subagents/{id}/run  {task?, request_id?, keep_open?}            → {ok, run: Run} | refusal (not_active, expired, already_running,
                                              balance_unavailable, nothing_to_buy, already_bought,
                                              no_trusted_vendor, over_budget)
    GET  /subagents/{id}/run                → {ok, run: Run | null}
    Run = {id, deployment, status: starting|running|succeeded|failed|timed_out|interrupted,
           started_at, finished_at, exit_code, plan, summary, error}
Creating a wallet never starts its task; only this endpoint does.
"""
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    keep_open: bool = False
    task: str | None = Field(default=None, min_length=1, max_length=4000)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


@router.post("/subagents/{dep_id}/run")
def start_run(dep_id: str, body: RunRequest | None = None) -> dict:
    from .. import runs
    out = runs.start(dep_id, task=body.task if body else None, request_id=body.request_id if body else None, keep_open=body.keep_open if body else False)
    if out.get("refused") == "unknown_deployment":
        raise HTTPException(404, "unknown deployment")
    return out


class CrawlRequest(BaseModel):
    pages: list[str] = Field(min_length=1, max_length=6)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


@router.post("/subagents/{dep_id}/crawl")
def start_crawl(dep_id: str, body: CrawlRequest) -> dict:
    """Read pages of a free site the wallet named, through the crawl gateway: one x402 payment for the whole crawl,
    multisigned from this wallet to the gateway (never to the site). Pages of any other site are refused here and by the co-signer."""
    from urllib.parse import quote
    from .. import config, deployments, runs
    from ..service import reads_site
    rec = deployments.get(dep_id)
    if not rec:
        raise HTTPException(404, "unknown deployment")
    outside = [p for p in body.pages if not p.startswith(("https://", "http://")) or not reads_site(rec, p)]
    if outside:
        return {"ok": False, "refused": "site_not_in_wallet", "pages": outside,
                "hint": "the gateway only reads sites this wallet's sentence named"}
    crawl = quote(body.request_id or uuid.uuid4().hex, safe="")  # each crawl is a fresh read, never "already bought"
    urls = "&".join(f"url={quote(p, safe='')}" for p in body.pages)
    specs = [f"{config.CRAWL_GATEWAY_URL}/crawl/page?{urls}&crawl={crawl}@{config.CRAWL_PAGE_MAX}"]
    return runs.start(dep_id, specs=specs, task=f"Read {len(body.pages)} pages through the crawl gateway in one payment",
                      request_id=body.request_id, keep_open=True)


@router.get("/subagents/{dep_id}/run")
def get_run(dep_id: str) -> dict:
    from .. import runs
    out = runs.current(dep_id)
    if out.get("refused") == "unknown_deployment":
        raise HTTPException(404, "unknown deployment")
    return out
