"""Get a site's content (unit 3; the logic is cereal/site_access.py). All need a session and the site must be the
user's: another user's site, or an unknown id, is a 404.

    POST /sites/{id}/open                                  → site_access.open_free
         {ok, url, status, content_type, title, text, truncated, bytes} | refusal (site_blocked, not_payable,
         unsafe_url, not_accessible)
    POST /sites/{id}/buy  {speculos_decision?, request_id?} → site_access.buy
         {ok, wallet, run} | refusal (site_blocked, not_payable, price_above_cap, already_running, every deploy refusal)
    GET  /sites/{id}/content                               → site_access.content
         {ok, wallet, hash, paid, explorer, resource, content, truncated} | refusal (nothing_bought, not_delivered)
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class BuyRequest(BaseModel):
    # Speculos demos only: which button the emulated owner presses (approve | reject). Ignored when a human is
    # driving the device (CEREAL_DEVICE_DECISION=manual); a real device always waits for its owner.
    speculos_decision: str | None = None
    request_id: str | None = None  # retrying with the same id returns the original purchase, never a second wallet


def _users_site(request: Request, site_id: str) -> tuple[dict, dict]:
    from .. import owners, site_registry
    user = owners.require_user(request)  # 401 without a valid session
    site = site_registry.get(user["id"], site_id)
    if not site:
        raise HTTPException(404, "unknown site")
    return user, site


@router.post("/sites/{site_id}/open")
def open_site(site_id: str, request: Request) -> dict:
    from .. import site_access
    user, site = _users_site(request, site_id)
    return site_access.open_free(user, site)


@router.post("/sites/{site_id}/buy")
def buy_site(site_id: str, request: Request, req: BuyRequest | None = None) -> dict:
    from .. import site_access
    user, site = _users_site(request, site_id)
    req = req or BuyRequest()
    decision = req.speculos_decision if req.speculos_decision in ("approve", "reject") else None
    return site_access.buy(user, site, speculos_decision=decision, request_id=req.request_id)


@router.get("/sites/{site_id}/content")
def site_content(site_id: str, request: Request) -> dict:
    from .. import site_access
    user, site = _users_site(request, site_id)
    return site_access.content(user, site)
