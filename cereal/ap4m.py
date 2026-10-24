"""Part 4b: the Mastercard AP4M rail (XRPL EVM testnet). Python drives ap4m/pay.mjs like cereal/device.py drives ledger/.

The AP4M agent key lives only in ap4m/.env and is used by ap4m/pay.mjs; this module never reads it. cereal's service
calls pay() after its own policy check, one payment at a time. Each subagent gets its own AP4M Channel, capped on-chain
at the subagent's budget (`--cap`), so Mastercard's PaymentLedger enforces the same limit cereal does.
"""
from __future__ import annotations

import json
import subprocess
import threading

from . import config

AP4M_DIR = config.ROOT / "ap4m"
_one_at_a_time = threading.Lock()  # one agent key = one EVM nonce sequence


def available() -> dict:
    """Is the AP4M rail runnable here? (dependencies installed, key file present). Never reads the key."""
    return {"node_modules": (AP4M_DIR / "node_modules").exists(), "env_file": (AP4M_DIR / ".env").exists()}


def pay(resource: str, max_rlusd: str, cap: str, job: str, tag: str, timeout: int = 600) -> dict:
    """Run ap4m/pay.mjs: open or reuse this job's Channel (cap = budget), pay the 402 with an EIP-712 voucher, have it
    redeemed and settled. Returns pay.mjs's JSON line ({ok, rail: ap4m, channel_id, amount, redeem_tx, …} or a refusal)."""
    cmd = ["node", str(AP4M_DIR / "pay.mjs"), "--resource", resource, "--amount", str(max_rlusd), "--cap", str(cap),
           "--job", job, "--tag", tag]
    with _one_at_a_time:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(AP4M_DIR))
        except subprocess.TimeoutExpired:
            return {"ok": False, "rail": "ap4m", "refused": "ap4m_timeout"}
    for line in reversed(p.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    return {"ok": False, "rail": "ap4m", "refused": "ap4m_error", "error": (p.stderr or p.stdout)[-300:]}


def channel_for_job(job: str) -> str | None:
    """The Channel pay.mjs opened for this subagent (ap4m/agent-state/cereal-channels.json; ids only, no secrets)."""
    try:
        return json.loads((AP4M_DIR / "agent-state" / "cereal-channels.json").read_text())["channelsByJob"].get(job)
    except (OSError, ValueError, KeyError):
        return None


def channel_state(channel_id: str, timeout: int = 120) -> dict:
    """The Channel's on-chain state from PaymentLedger: redeemed total, cap, status and its VoucherRedeemed events."""
    try:
        p = subprocess.run(["node", str(AP4M_DIR / "channel.mjs"), channel_id], capture_output=True, text=True,
                           timeout=timeout, cwd=str(AP4M_DIR))
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, ValueError, IndexError) as e:
        return {"ok": False, "error": str(e)}
