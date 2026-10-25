"""A05: the folder store. A folder is a name the owner files wallets under; it is presentation only.

Folders live next to the deployment records (`<records>.folders.json`, gitignored with them) and are written
atomically. A wallet's record stores its folder's *name* (`record["folder"]`), so the folders the app lists are the
stored ones plus any name a record already uses (e.g. one given at creation). Names are trimmed, NFC-normalised,
1-60 characters, and unique ignoring case and surrounding spaces. A folder a record uses is stored the first time
it is created or moved into/out of, so it does not vanish when its last wallet leaves. Nothing here touches a
payment policy, a balance or the ledger.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config, deployments

MAX_NAME = 60
_lock = threading.RLock()


def path() -> Path:
    f = config.DEPLOYMENTS_FILE
    return f.with_name(f.stem + ".folders.json")


def _stored() -> list[dict]:
    p = path()
    return json.loads(p.read_text()) if p.exists() else []


def _save(items: list[dict]) -> None:
    """Write to a temp file in the same directory, fsync, then rename over the store: a crash never leaves half a file."""
    p = path()
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.stem + ".", suffix=".tmp.json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(items, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def clean(raw: object, limit: int) -> tuple[str | None, str | None]:
    """(trimmed name, None) or (None, why it is not a valid name)."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "empty"
    name = unicodedata.normalize("NFC", raw.strip())
    if len(name) > limit:
        return None, "too_long"
    if not name.isprintable():
        return None, "unprintable"
    return name, None


def key(name: str) -> str:
    """What makes two folder names the same folder: case, surrounding spaces and Unicode composition do not count."""
    return unicodedata.normalize("NFC", name.strip()).casefold()


def all_() -> list[dict]:
    """Stored folders (in creation order), then names records use that match no stored folder (each once)."""
    with _lock:
        out = [{"id": f["id"], "name": f["name"]} for f in _stored()]
    seen = {key(f["name"]) for f in out}
    for name in sorted({r["folder"] for r in deployments.all_() if isinstance(r.get("folder"), str) and r["folder"].strip()}):
        if key(name) not in seen:
            seen.add(key(name))
            out.append({"id": name, "name": name})
    return out


def find(name: str) -> dict | None:
    """The known folder with this name: an exact match first, else one that is the same folder by `key`."""
    known = all_()
    return next((f for f in known if f["name"] == name), None) or next((f for f in known if key(f["name"]) == key(name)), None)


def _store(name: str) -> dict:
    """Append a folder to the store (callers hold _lock and have checked it is not stored yet)."""
    folder = {"id": "f_" + uuid.uuid4().hex[:8], "name": name, "created_at": datetime.now(timezone.utc).isoformat()}
    _save(_stored() + [folder])
    return {"id": folder["id"], "name": folder["name"]}


def create(name: str) -> tuple[dict, bool]:
    """(folder, True) when stored now; (the existing folder, False) when a stored folder already has this name.
    A name only records use so far is stored under that same spelling, so wallets already in it stay in it."""
    with _lock:
        stored = next((f for f in _stored() if key(f["name"]) == key(name)), None)
        if stored:
            return {"id": stored["id"], "name": stored["name"]}, False
        used = find(name)  # not stored, so any match is a name only records use
        return _store(used["name"] if used else name), True


def ensure(name: str | None) -> None:
    """Store a folder records use, if it is not stored yet (a no-op for None and for stored folders)."""
    if not name:
        return
    with _lock:
        if not any(key(f["name"]) == key(name) for f in _stored()):
            _store(name)
