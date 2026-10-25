"""Sites, per-user identity (owner: unit 2). Contract in docs/SITES.md.

A user is a name plus a random bearer token (only its hash is stored, next to the record file). Requests carry
`Authorization: Bearer <token>`; the React app keeps the token in the browser (src/session.ts). This scopes sites and
the wallets bought for them to one user; it is not yet full account security (checklist R05).

Store: <records stem>.users.json, {"users": {"u_<hex>": {"id", "name", "created_at"}}, "tokens": {"<sha256>": "u_<hex>"}},
written atomically under a machine-wide lock (cereal/sidestore.py). The token itself is never stored, logged or
returned again after create_session; a request's token is found by its hash (one dict lookup, no scan).
"""
from __future__ import annotations

import hashlib
import secrets
import unicodedata
from datetime import datetime, timezone

from .sidestore import SideStore

MAX_NAME = 40
_store = SideStore(".users.json")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public(u: dict) -> dict:
    return {"id": u["id"], "name": u["name"]}


def clean_name(raw: object) -> tuple[str | None, str | None]:
    """(trimmed name, None) or (None, why it is not a valid name): 1-40 printable characters."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "empty"
    name = unicodedata.normalize("NFC", raw.strip())
    if len(name) > MAX_NAME:
        return None, "too_long"
    if not name.isprintable():
        return None, "unprintable"
    return name, None


def create_session(name: str) -> dict:
    """New user: {ok: True, user: {id, name}, token} (the token is shown once), or a refusal (invalid_name)."""
    clean, why = clean_name(name)
    if why:
        return {"ok": False, "refused": "invalid_name", "problem": why, "limit": MAX_NAME}
    token = secrets.token_urlsafe(32)
    with _store.locked():
        data = _store.load()
        users, tokens = data.setdefault("users", {}), data.setdefault("tokens", {})
        uid = "u_" + secrets.token_hex(8)
        while uid in users:
            uid = "u_" + secrets.token_hex(8)
        users[uid] = {"id": uid, "name": clean, "created_at": datetime.now(timezone.utc).isoformat()}
        tokens[_hash(token)] = uid
        _store.save(data)
    return {"ok": True, "user": {"id": uid, "name": clean}, "token": token}


def user_for_token(token: str | None) -> dict | None:
    """{id, name} for a valid token, else None."""
    if not isinstance(token, str) or not token:
        return None
    data = _store.load()
    uid = data.get("tokens", {}).get(_hash(token))  # keyed by the sha256 of a 256-bit random token
    u = data.get("users", {}).get(uid) if uid else None
    return _public(u) if u else None


def get(user_id: str | None) -> dict | None:
    """{id, name} of a known user, else None."""
    u = _store.load().get("users", {}).get(user_id) if user_id else None
    return _public(u) if u else None


def bearer(request) -> str | None:
    """The token in a request's `Authorization: Bearer <token>` header, or None."""
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def current_user(request) -> dict | None:
    """The user behind a FastAPI request's Authorization header, or None."""
    return user_for_token(bearer(request))


def require_user(request) -> dict:
    """current_user(request), or raise HTTPException(401)."""
    from fastapi import HTTPException
    user = current_user(request)
    if not user:
        raise HTTPException(401, "sign in first: POST /session, then send Authorization: Bearer <token>",
                            headers={"WWW-Authenticate": "Bearer"})
    return user
