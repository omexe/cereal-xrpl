"""POST /session {name} → owners.create_session; GET /session → {ok, user} for the bearer token (owner: unit 2)."""
from fastapi import APIRouter

router = APIRouter()
