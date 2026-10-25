"""POST /sites/probe {url} → sites_probe.probe(url) (owner: unit 1). Reads only; no session needed.

Any input answers 200 with a result: a missing or non-text url, or a body that is not JSON, is the refusal
{ok: false, refused: "invalid_url", reason}; a private or non-http(s) address is {refused: "unsafe_url"}. Never pays,
never signs.
"""
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

router = APIRouter()


@router.post("/sites/probe")
async def probe_site(request: Request) -> dict:
    """What the site at {url} is (free / payable / unpayable / unreachable), its checks, verdict and trust hint."""
    from .. import sites_probe
    try:
        body = await request.json()  # parsed whatever the content type (curl -d sends form-encoded by default)
    except ValueError:
        body = None
    url = body.get("url") if isinstance(body, dict) else None
    return await run_in_threadpool(sites_probe.probe, url)
