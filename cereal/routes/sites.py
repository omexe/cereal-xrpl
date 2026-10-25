"""The signed-in user's private site list (owner: unit 2).
GET /sites → [site]; POST /sites {url} → probe + site_registry.add; POST /sites/{id}/remove. All need a session.

    GET  /sites                → [site]  (only the caller's)
    POST /sites {url}          → {ok: true, site, refreshed} | refusal (invalid_url, unsafe_url, not_accessible,
                                 site_blocked: stored as blocked, returned with `site` so the owner sees why)
    POST /sites/{id}/remove    → {ok: true} | 404 (unknown, or another user's site)
No session → 401. The probe never pays or signs; adding a site sends nothing to the ledger.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
MAX_URL = 2048


class AddSite(BaseModel):
    url: str | None = None


@router.get("/sites")
def list_sites(request: Request) -> list[dict]:
    from .. import owners, site_registry
    return site_registry.list_for(owners.require_user(request)["id"])


@router.post("/sites")
def add_site(req: AddSite, request: Request) -> dict:
    from .. import owners, site_registry, sites_probe
    user = owners.require_user(request)
    url = (req.url or "").strip()
    if not url or len(url) > MAX_URL:
        return {"ok": False, "refused": "invalid_url", "reason": "Give a web address (http or https)."}
    probe = sites_probe.probe(url)  # reads the site and the ledger; never pays, never signs
    return site_registry.add(user["id"], probe)  # a probe refusal (invalid_url, unsafe_url) comes back as is


@router.post("/sites/{site_id}/remove")
def remove_site(site_id: str, request: Request) -> dict:
    from .. import owners, site_registry
    user = owners.require_user(request)
    if not site_registry.remove(user["id"], site_id):
        raise HTTPException(404, "unknown site")
    return {"ok": True}
