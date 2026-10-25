"""POST /session {name} → owners.create_session; GET /session → {ok, user} for the bearer token (owner: unit 2).

    POST /session {name}  → {ok: true, user: {id, name}, token} (the token is shown this once) | refusal invalid_name
    GET  /session         → {ok: true, user: {id, name}} | 401 without a valid `Authorization: Bearer <token>`
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class SessionRequest(BaseModel):
    name: str | None = None


@router.post("/session")
def create_session(req: SessionRequest) -> dict:
    from .. import owners
    return owners.create_session(req.name)


@router.get("/session")
def current_session(request: Request) -> dict:
    from .. import owners
    return {"ok": True, "user": owners.require_user(request)}
