"""Locks that hold across processes, not just threads: several cereal services (a worker's private service, the
demo service on :8001) share one treasury account sequence and one Speculos device on the same machine.

    with ProcessLock("treasury"): ...   # one main-wallet transaction sequence at a time, machine-wide
    with ProcessLock("speculos"): ...   # one device signing session at a time, machine-wide
"""
from __future__ import annotations

import fcntl
import os
import tempfile
import threading
from pathlib import Path

LOCK_DIR = Path(os.getenv("CEREAL_LOCK_DIR") or tempfile.gettempdir())


class ProcessLock:
    def __init__(self, name: str):
        self.path = LOCK_DIR / f"cereal-{name}.lock"
        self._thread = threading.Lock()
        self._fd: int | None = None

    def __enter__(self):
        self._thread.acquire()
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self._fd, fcntl.LOCK_EX)
        except BaseException:
            self._release_fd()
            self._thread.release()
            raise
        return self

    def __exit__(self, *exc):
        self._release_fd()
        self._thread.release()
        return False

    def _release_fd(self):
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None
