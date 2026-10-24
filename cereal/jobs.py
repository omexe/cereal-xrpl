"""cereal's private job store: job → sentence, burner, budget, expiry, tag → team/project/task. Gitignored JSON."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from . import config
from .ledger import job_tag


def _load() -> dict:
    if config.JOBS_FILE.exists():
        return json.loads(config.JOBS_FILE.read_text())
    return {}


def _save(data: dict) -> None:
    config.JOBS_FILE.write_text(json.dumps(data, indent=2))


def create(sentence: str, card: dict, burner: str) -> dict:
    """Register a job from a compiled conditions card and the burner it will use."""
    tag_fields = card["tag"]
    job = {
        "id": uuid.uuid4().hex[:8],
        "sentence": sentence,
        "burner": burner,
        "budget": str(card["budget"]),
        "currency": card.get("currency", "RLUSD"),
        "vendor_class": card.get("vendor_class", "data"),
        "expires_at": card["expires_at"],
        "tag": job_tag(tag_fields["team"], tag_fields["project"], tag_fields["task"]),
        "team": tag_fields["team"], "project": tag_fields["project"], "task": tag_fields["task"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payments": [], "status": "created",
    }
    data = _load(); data[job["id"]] = job; _save(data)
    return job


def get(job_id: str) -> dict | None:
    return _load().get(job_id)


def by_burner(burner: str) -> dict | None:
    return next((j for j in _load().values() if j["burner"] == burner), None)


def by_tag(tag: str) -> dict | None:
    return next((j for j in _load().values() if j["tag"] == tag), None)


def update(job_id: str, **fields) -> dict:
    data = _load(); data[job_id].update(fields); _save(data); return data[job_id]


def record_payment(job_id: str, entry: dict) -> None:
    data = _load(); data[job_id]["payments"].append(entry); _save(data)


def all_jobs() -> list[dict]:
    return list(_load().values())


def default_expiry(hours: int = 24) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
