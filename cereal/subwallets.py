"""p1.1 — the subwallet factory. The main wallet creates, locks and (via fund.py) funds each subagent's subwallet.

create(): fresh keypair → XRP activation Payment from the main wallet (reserve read from server_info) →
sequential lock (TrustSet limit=budget → SignerListSet {subagent 1, cereal 1[, Ledger 2]} q=2 → AccountSet
asfDisableMaster) → the master seed is dropped and never written anywhere.
"""
from __future__ import annotations

from decimal import Decimal

from xrpl.clients import JsonRpcClient
from xrpl.models.requests import ServerInfo
from xrpl.models.transactions import Payment
from xrpl.utils import xrp_to_drops
from xrpl.wallet import Wallet

from . import config
from .ledger import job_memo, sign_submit, stamp
from .lock import is_locked, lock_burner


def activation_xrp(c: JsonRpcClient) -> Decimal:
    """Base reserve + two owner objects (trust line, signer list) + 0.5 XRP for fees."""
    v = c.request(ServerInfo()).result["info"]["validated_ledger"]
    return Decimal(str(v["reserve_base_xrp"])) + 2 * Decimal(str(v["reserve_inc_xrp"])) + Decimal("0.5")


def create(deployment_id: str, tag: str, budget: str, subagent_addr: str, c: JsonRpcClient,
           main: Wallet | None = None, sub: Wallet | None = None) -> dict:
    """`sub`: a keypair generated before the owner's approval (Part 3), so the device showed this exact address."""
    main = main or config.wallet("TREASURY")
    sub = sub or Wallet.create()
    addr = sub.classic_address
    amount = activation_xrp(c)
    act = sign_submit(stamp(Payment(account=main.classic_address, destination=addr, amount=xrp_to_drops(amount)),
                            [job_memo(deployment_id, tag, kind="activate")]), main, c)
    out = {"address": addr, "activation_xrp": str(amount), "hashes": {"activate": act.get("hash"), "lock": []},
           "ok": False}
    if not act["ok"]:
        out["error"] = act
        return out
    results = lock_burner(sub, subagent_addr, config.address("CEREAL_COSIGN"), budget, c, job_id=deployment_id,
                          tag=tag, sequential=True,
                          recovery_addr=config.LEDGER_ADDRESS if config.LEDGER_RECOVERY else None)
    del sub  # the master seed is never stored; after the lock it cannot sign anyway
    results = results if isinstance(results, list) else [results]
    out["hashes"]["lock"] = [r.get("hash") for r in results]
    state = is_locked(c, addr)
    out["locked"] = state
    out["ok"] = bool(state["locked"]) and all(r.get("ok") for r in results)
    if not out["ok"]:
        out["error"] = [r for r in results if not r.get("ok")]
    return out
