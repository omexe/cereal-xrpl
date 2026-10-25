"""Sites, per-user identity (owner: unit 2). Contract in docs/SITES.md.

A user is a name plus a random bearer token (only its hash is stored, next to the record file). Requests carry
`Authorization: Bearer <token>`; the React app keeps the token in the browser (src/session.ts). This scopes sites and
the wallets bought for them to one user; it is not yet full account security (checklist R05).
"""
from __future__ import annotations


def create_session(name: str) -> dict:
    """New user: {ok: True, user: {id, name}, token} (the token is shown once), or a refusal (invalid_name)."""
    raise NotImplementedError


def user_for_token(token: str | None) -> dict | None:
    """{id, name} for a valid token, else None."""
    raise NotImplementedError


def current_user(request) -> dict | None:
    """The user behind a FastAPI request's Authorization header, or None."""
    raise NotImplementedError


def require_user(request) -> dict:
    """current_user(request), or raise HTTPException(401)."""
    raise NotImplementedError
