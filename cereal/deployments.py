"""p1.3 — deployment records (main agent → subagent → subwallet) and the caps, enforced here, never by the agent."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from . import config
from .ledger import job_tag

_lock = threading.Lock()
LIVE = ("deploying", "active")


def _load() -> dict:
    return json.loads(config.DEPLOYMENTS_FILE.read_text()) if config.DEPLOYMENTS_FILE.exists() else {}


def _save(d: dict) -> None:
    config.DEPLOYMENTS_FILE.write_text(json.dumps(d, indent=2))


def active() -> list[dict]:
    return [d for d in _load().values() if d["status"] in LIVE]


def outstanding_budget() -> Decimal:
    return sum((Decimal(d["budget"]) for d in active()), Decimal(0))


def check_caps(budget: str) -> dict | None:
    """None if allowed, else the refusal (no transaction is ever sent for a refused deploy)."""
    b = Decimal(str(budget))
    if b <= 0:
        return {"ok": False, "refused": "invalid_budget", "requested": str(b)}
    if b > Decimal(str(config.MAX_SUBAGENT_BUDGET)):
        return {"ok": False, "refused": "cap_exceeded", "cap": "MAX_SUBAGENT_BUDGET",
                "limit": str(config.MAX_SUBAGENT_BUDGET), "requested": str(b)}
    if outstanding_budget() + b > Decimal(str(config.MAX_OUTSTANDING_BUDGET)):
        return {"ok": False, "refused": "cap_exceeded", "cap": "MAX_OUTSTANDING_BUDGET",
                "limit": str(config.MAX_OUTSTANDING_BUDGET), "requested": str(b),
                "outstanding": str(outstanding_budget())}
    if len(active()) >= config.MAX_ACTIVE_SUBAGENTS:
        return {"ok": False, "refused": "cap_exceeded", "cap": "MAX_ACTIVE_SUBAGENTS",
                "limit": str(config.MAX_ACTIVE_SUBAGENTS), "active": len(active())}
    return None


def create(task: str, budget: str, allowed_payees: list[str], expires_in_hours: float = 24,
           vendor_class: str = "data") -> dict:
    with _lock:
        d = _load()
        dep_id = "d_" + uuid.uuid4().hex[:6]
        rec = {
            "id": dep_id, "parent": "main", "task": task, "budget": str(budget), "currency": "RLUSD",
            "allowed_payees": list(allowed_payees), "vendor_class": vendor_class, "refusals": [],
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).isoformat(),
            "tag": job_tag("main", dep_id, "subagent"), "subwallet": None, "subagent": None,
            "status": "deploying", "hashes": {}, "payments": [], "summary": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        d[dep_id] = rec
        _save(d)
        return rec


def get(dep_id: str) -> dict | None:
    return _load().get(dep_id)


def all_() -> list[dict]:
    return list(_load().values())


def update(dep_id: str, **fields) -> dict:
    with _lock:
        d = _load(); d[dep_id].update(fields); _save(d); return d[dep_id]


def merge_hashes(dep_id: str, **hashes) -> dict:
    with _lock:
        d = _load(); d[dep_id].setdefault("hashes", {}).update(hashes); _save(d); return d[dep_id]


def record_payment(dep_id: str, entry: dict) -> None:
    with _lock:
        d = _load(); d[dep_id]["payments"].append(entry); _save(d)


def record_refusal(dep_id: str, entry: dict) -> None:
    with _lock:
        d = _load()
        if dep_id in d:
            d[dep_id].setdefault("refusals", []).append(entry); _save(d)


def public(rec: dict) -> dict:
    """What the API returns: never a key, never a seed (records never hold them anyway)."""
    return dict(rec)
