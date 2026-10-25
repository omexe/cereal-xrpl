"""p1.3 — deployment records (main agent → subagent → subwallet) and the caps, enforced here, never by the agent.

Persistence (R04): one local JSON file shared by every cereal process that points at it (the API threads, the sweeper,
other local services). Every load-modify-save holds `_lock`: a thread lock plus a machine-wide file lock
(cereal.xlock.ProcessLock keyed by the record file's real path), so concurrent payment, event and refusal updates never
overwrite each other. Callers with their own read-check-write hold it too (`with deployments._lock:`; re-entrant; never
take the main-wallet lock while holding it). Every save writes a temp file in the same directory, fsyncs it and
os.replace()s it over the record file, so a reader or a crash only ever sees a whole old file or a whole new one.
Plain reads take no lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import config
from .ledger import job_tag
from .xlock import ProcessLock

LIVE = ("deploying", "active")


def _path() -> Path:
    return config.DEPLOYMENTS_FILE.resolve()  # the real file: a symlinked store is replaced at its target


class _StoreLock:
    """The store's lock: the existing thread lock (an RLock, so re-entrant within a thread) and, while a thread holds
    it at all, the ProcessLock of the record file it is writing, which every process using that file shares."""

    def __init__(self):
        self._thread = threading.RLock()
        self._depth = 0  # how deeply the holding thread has entered (guarded by _thread)
        self._file: ProcessLock | None = None
        self._files: dict[str, ProcessLock] = {}  # one ProcessLock per record file (guarded by _thread)

    def _file_lock(self) -> ProcessLock:
        key = str(_path())
        if key not in self._files:
            self._files[key] = ProcessLock("deployments-" + hashlib.sha256(key.encode()).hexdigest()[:16])
        return self._files[key]

    def acquire(self) -> bool:
        self._thread.acquire()
        if self._depth == 0:
            try:
                held = self._file_lock()
                held.__enter__()
            except BaseException:
                self._thread.release()
                raise
            self._file = held
        self._depth += 1
        return True

    def release(self) -> None:
        self._depth -= 1
        try:
            if self._depth == 0:
                held, self._file = self._file, None
                held.__exit__(None, None, None)
        finally:
            self._thread.release()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


_lock = _StoreLock()  # every read-modify-write of the store holds it (API threads, the sweeper, other processes)


def _load() -> dict:
    p = config.DEPLOYMENTS_FILE
    return json.loads(p.read_text()) if p.exists() else {}


def _save(d: dict) -> None:
    """Atomic replace: temp file in the same directory, fsync, os.replace, then fsync the directory (the rename)."""
    target = _path()
    data = json.dumps(d, indent=2)  # serialize first: a value JSON cannot hold fails before anything is written
    # deployments.tmp-XXXX.json: a temp file a hard kill leaves behind still matches .gitignore's deployments*.json
    tmp = target.with_name(f"{target.stem}.tmp-{uuid.uuid4().hex[:12]}{target.suffix}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)  # the umask applies, as it did for write_text
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        with suppress(FileNotFoundError):
            os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))  # an existing store keeps its mode
        os.replace(tmp, target)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    with suppress(OSError):
        dfd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def _live(store: dict) -> list[dict]:
    return [d for d in store.values() if d["status"] in LIVE]


def _outstanding(live: list[dict]) -> Decimal:
    return sum((Decimal(d["budget"]) for d in live), Decimal(0))


def active() -> list[dict]:
    return _live(_load())


def outstanding_budget() -> Decimal:
    return _outstanding(active())


def _check_caps(budget, store: dict) -> dict | None:
    try:
        b = Decimal(str(budget))
        valid = b.is_finite() and b > 0
    except InvalidOperation:
        valid = False
    if not valid:
        return {"ok": False, "refused": "invalid_budget", "requested": str(budget)}
    if b > Decimal(str(config.MAX_SUBAGENT_BUDGET)):
        return {"ok": False, "refused": "cap_exceeded", "cap": "MAX_SUBAGENT_BUDGET",
                "limit": str(config.MAX_SUBAGENT_BUDGET), "requested": str(b)}
    live = _live(store)  # one snapshot for every cap and its evidence
    outstanding = _outstanding(live)
    if outstanding + b > Decimal(str(config.MAX_OUTSTANDING_BUDGET)):
        return {"ok": False, "refused": "cap_exceeded", "cap": "MAX_OUTSTANDING_BUDGET",
                "limit": str(config.MAX_OUTSTANDING_BUDGET), "requested": str(b), "outstanding": str(outstanding)}
    if len(live) >= config.MAX_ACTIVE_SUBAGENTS:
        return {"ok": False, "refused": "cap_exceeded", "cap": "MAX_ACTIVE_SUBAGENTS",
                "limit": str(config.MAX_ACTIVE_SUBAGENTS), "active": len(live)}
    return None


def check_caps(budget: str) -> dict | None:
    """None if allowed, else the refusal (no transaction is ever sent for a refused deploy). A read only: reserve()
    checks and claims a slot in one step."""
    return _check_caps(budget, _load())


def _new_record(store: dict, task: str, budget: str, allowed_payees: list[str], expires_in_hours: float,
                vendor_class: str) -> dict:
    dep_id = "d_" + uuid.uuid4().hex[:6]
    while dep_id in store:
        dep_id = "d_" + uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc)
    return {
        "id": dep_id, "parent": "main", "task": task, "budget": str(budget), "currency": "RLUSD",
        "allowed_payees": list(allowed_payees), "vendor_class": vendor_class, "refusals": [],
        "expires_at": (now + timedelta(hours=expires_in_hours)).isoformat(),
        "tag": job_tag("main", dep_id, "subagent"), "subwallet": None, "subagent": None,
        "status": "deploying", "hashes": {}, "payments": [], "summary": None,
        "created_at": now.isoformat(),
    }


def create(task: str, budget: str, allowed_payees: list[str], expires_in_hours: float = 24,
           vendor_class: str = "data") -> dict:
    with _lock:
        d = _load()
        rec = _new_record(d, task, budget, allowed_payees, expires_in_hours, vendor_class)
        d[rec["id"]] = rec
        _save(d)
        return rec


def _find_request(store: dict, request_id: str | None) -> dict | None:
    if not request_id:
        return None
    return next((r for r in store.values() if r.get("request_id") == request_id), None)


def find_request(request_id: str | None) -> dict | None:
    """R03: the deployment an earlier deploy request with this idempotency key created, if any."""
    return _find_request(_load(), request_id)


def reserve(task: str, budget: str, allowed_payees: list[str], expires_in_hours: float = 24,
            vendor_class: str = "data", request_id: str | None = None, **extra) -> dict:
    """R02: check every cap and create the `deploying` record in one locked write, so concurrent deploys (any thread,
    any process sharing the store) can never both pass a stale outstanding-budget or active count. The new record
    counts against the caps from this moment. R03: the request_id is on the record from its first write, so a restart
    mid-deploy can never let a retry deploy a second wallet. Returns the record, or the refusal (`refused`): a cap, or
    `duplicate_request` when a record already carries this request_id. `extra` fields land in the same write."""
    with _lock:
        d = _load()
        prior = _find_request(d, request_id)
        if prior:
            return {"ok": False, "refused": "duplicate_request", "deployment": prior["id"], "request_id": request_id}
        refused = _check_caps(budget, d)
        if refused:
            return refused
        rec = _new_record(d, task, budget, allowed_payees, expires_in_hours, vendor_class)
        rec.update({k: v for k, v in extra.items() if v is not None})
        if request_id:
            rec["request_id"] = request_id
        d[rec["id"]] = rec
        _save(d)
        return rec


def release(dep_id: str) -> bool:
    """Undo a reservation that never reached the ledger: drop the `deploying` record so its cap slot (and its
    request_id) are free again. Refuses (False) once the record shows any sign of the ledger: a subwallet or a hash."""
    with _lock:
        d = _load()
        rec = d.get(dep_id)
        if not rec or rec["status"] != "deploying" or rec.get("subwallet") or any((rec.get("hashes") or {}).values()):
            return False
        del d[dep_id]
        _save(d)
        return True


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
        d = _load(); d[dep_id].setdefault("payments", []).append(entry); _save(d)


def update_payment(dep_id: str, tx_hash: str, **fields) -> None:
    with _lock:
        d = _load()
        for pmt in d[dep_id].get("payments", []):
            if pmt.get("hash") == tx_hash:
                pmt.update(fields)
        _save(d)


def record_event(dep_id: str, entry: dict) -> None:
    with _lock:
        d = _load()
        d[dep_id].setdefault("events", []).append(entry)
        _save(d)


def record_refusal(dep_id: str, entry: dict) -> None:
    with _lock:
        d = _load()
        if dep_id in d:
            d[dep_id].setdefault("refusals", []).append(entry); _save(d)


def public(rec: dict) -> dict:
    """What the API returns: never a key, never a seed (records never hold them anyway)."""
    return dict(rec)
