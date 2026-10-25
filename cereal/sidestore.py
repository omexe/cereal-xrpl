"""A small JSON file kept next to the record file (<records stem><suffix>, e.g. deployments.users.json), gitignored with
it by `deployments*.json`. Used by the Sites stores (cereal/owners.py, cereal/site_registry.py).

Every read-modify-write holds `locked()`: a re-entrant thread lock plus, at the outermost level, a machine-wide
ProcessLock keyed by the file's real path, so every cereal process sharing the record file shares these too. Saves are
atomic (temp file in the same directory, fsync, os.replace), so a reader or a crash only ever sees a whole file.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager, suppress
from pathlib import Path

from . import config
from .xlock import ProcessLock


class SideStore:
    def __init__(self, suffix: str):
        self.suffix = suffix  # ".users.json"
        self._thread = threading.RLock()
        self._depth = 0  # guarded by _thread

    def path(self) -> Path:
        f = config.DEPLOYMENTS_FILE.resolve()  # a symlinked record file keeps its stores next to its target
        return f.with_name(f.stem + self.suffix)

    @contextmanager
    def locked(self):
        with self._thread:
            held = None
            if self._depth == 0:
                key = hashlib.sha256(str(self.path()).encode()).hexdigest()[:16]
                held = ProcessLock(f"side{self.suffix.replace('.', '-')}-{key}")  # e.g. cereal-side-users-json-<key>
                held.__enter__()
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if held is not None:
                    held.__exit__(None, None, None)

    def load(self) -> dict:
        p = self.path()
        return json.loads(p.read_text()) if p.exists() else {}

    def save(self, data: dict) -> None:
        target = self.path()
        text = json.dumps(data, indent=2)  # serialize first: a value JSON cannot hold fails before anything is written
        tmp = target.with_name(f"{target.stem}.tmp-{uuid.uuid4().hex[:12]}{target.suffix}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # holds token hashes: owner-only
        try:
            with os.fdopen(fd, "w") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
