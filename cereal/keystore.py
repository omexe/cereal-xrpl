"""p1.2 — one fresh key per subagent. The subagent process loads only its own file; the main agent never sees keys.

Files: keys/subagents/<deployment_id>.json (gitignored, mode 600) = {"address": ..., "seed": ..., "algorithm": "ed25519"}.
"""
from __future__ import annotations

import json
import os

from xrpl import CryptoAlgorithm
from xrpl.wallet import Wallet

from . import config


def _path(deployment_id: str):
    return config.KEYS_DIR / f"{deployment_id}.json"


def new_subagent_key(deployment_id: str) -> str:
    """Create and store the subagent's key; return only its address."""
    config.KEYS_DIR.mkdir(parents=True, exist_ok=True)
    w = Wallet.create(algorithm=CryptoAlgorithm.ED25519)
    p = _path(deployment_id)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"address": w.classic_address, "seed": w.seed, "algorithm": "ed25519"}, f)
    return w.classic_address


def load(deployment_id: str) -> Wallet:
    data = json.loads(_path(deployment_id).read_text())
    return Wallet.from_seed(data["seed"], algorithm=CryptoAlgorithm.ED25519)


def address(deployment_id: str) -> str:
    return json.loads(_path(deployment_id).read_text())["address"]
