"""Part 3: the owner's Ledger takes a subagent's money back alone. No cereal key, no service, no subagent.

Every subwallet's signer list is {subagent 1, cereal 1, Ledger 2}, quorum 2, so the device's weight meets the quorum
by itself. Recovery is two clear-signed transactions: sweep the RLUSD home, close the trust line. Retire
(AccountDelete, also clear-signed) once the account is >=256 ledgers old.

    python -m cereal.recover <deployment_id | subwallet address> [--retire]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from xrpl.clients import JsonRpcClient
from xrpl.models.requests import AccountLines
from xrpl.models.transactions import AccountDelete, Payment, TrustSet

from . import config, deployments, device
from .burn import TF_SET_NO_RIPPLE, burnable_in
from .ledger import client, job_memo, rlusd, rlusd_balance, stamp


def recover(subwallet: str, c: JsonRpcClient, *, to: str | None = None, dep_id: str = "", tag: str = "",
            decision: str | None = None) -> list[tuple[str, dict]]:
    """Sweep the subwallet's RLUSD to the main wallet and close its trust line, signed on the device alone."""
    to = to or config.address("TREASURY")
    memos = [job_memo(dep_id, tag, kind="recover")] if dep_id and tag else []
    steps: list[tuple[str, dict]] = []
    bal = rlusd_balance(c, subwallet)
    if bal > 0:
        r = device.sign_submit(stamp(Payment(account=subwallet, destination=to, amount=rlusd(bal)), memos), c,
                               decision=decision)
        steps.append(("sweep", {**r, "amount": str(bal)}))
        if not r.get("ok"):
            return steps
    if c.request(AccountLines(account=subwallet)).result.get("lines"):
        r = device.sign_submit(stamp(TrustSet(account=subwallet, limit_amount=rlusd("0"), flags=TF_SET_NO_RIPPLE),
                                     memos), c, decision=decision)
        steps.append(("close_line", r))
    return steps


def retire(subwallet: str, c: JsonRpcClient, *, to: str | None = None, dep_id: str = "", tag: str = "",
           decision: str | None = None) -> dict:
    """AccountDelete on the device alone: the XRP reserve goes back to the main wallet."""
    wait = burnable_in(c, subwallet)
    if wait > 0:
        return {"ok": False, "refused": "too_young", "ready_in_ledgers": wait}
    memos = [job_memo(dep_id, tag, kind="retire")] if dep_id and tag else []
    return device.sign_submit(stamp(AccountDelete(account=subwallet, destination=to or config.address("TREASURY")),
                                    memos), c, decision=decision, fail_hard=True)


def recover_deployment(dep_id_or_addr: str, *, do_retire: bool = False, decision: str | None = None) -> dict:
    rec = deployments.get(dep_id_or_addr) or next(
        (d for d in deployments.all_() if d.get("subwallet") == dep_id_or_addr), None)
    subwallet = rec["subwallet"] if rec else dep_id_or_addr
    dep_id, tag = (rec["id"], rec["tag"]) if rec else ("", "")
    c = client()
    steps = recover(subwallet, c, dep_id=dep_id, tag=tag, decision=decision)
    ok = all(r.get("ok") for _, r in steps)
    out = {"ok": ok, "subwallet": subwallet, "deployment": dep_id or None, "signer": config.LEDGER_ADDRESS,
           "steps": [{"step": n, **r} for n, r in steps]}
    if rec and ok:
        deployments.merge_hashes(dep_id, recover=[r.get("hash") for _, r in steps])
        deployments.update(dep_id, status="recovered", recovered_at=datetime.now(timezone.utc).isoformat())
    if do_retire and ok:
        out["retire"] = retire(subwallet, c, dep_id=dep_id, tag=tag, decision=decision)
        if rec and out["retire"].get("ok"):
            deployments.merge_hashes(dep_id, retire=out["retire"].get("hash"))
            deployments.update(dep_id, status="retired")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Owner recovery with the Ledger alone (no cereal key, no service).")
    ap.add_argument("target", help="deployment id (d_…) or subwallet address")
    ap.add_argument("--retire", action="store_true", help="also AccountDelete if the subwallet is old enough")
    ap.add_argument("--decision", choices=["approve", "reject", "manual"], help="Speculos button driver")
    a = ap.parse_args()
    print(json.dumps(recover_deployment(a.target, do_retire=a.retire, decision=a.decision), indent=2, default=str))


if __name__ == "__main__":
    main()
