"""Run one command while holding the machine-wide live-testnet lock, so parallel workers take turns on the shared
treasury, vendors and Speculos device. Exit code is the command's.

    .venv/bin/python scripts/with_testnet_lock.py -- npx playwright test -c playwright.live.config.ts tests/live-x.spec.ts
"""
import fcntl
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

args = sys.argv[1:]
if args[:1] == ["--"]:
    args = args[1:]
if not args:
    sys.exit("usage: with_testnet_lock.py -- <command> [args...]")
path = Path(os.getenv("CEREAL_LOCK_DIR") or tempfile.gettempdir()) / "cereal-testnet-e2e.lock"
fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
start = time.time()
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print(f"waiting for the live-testnet lock ({path}) held by another worker...", flush=True)
    fcntl.flock(fd, fcntl.LOCK_EX)
    print(f"got the lock after {time.time() - start:.0f}s", flush=True)
try:
    sys.exit(subprocess.call(args))
finally:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
