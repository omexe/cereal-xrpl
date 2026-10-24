"""Scripted driver for the 90 seconds (also the fallback and the integration test).

    python -m cereal.demo --sentence "Give the research agent 20 RLUSD for data vendors until tomorrow, project swell-brief, team growth, task news" --burner BURNER_1
    python -m cereal.demo --job <id> --burn

Requires: the co-sign service running (make cosign), vendor credentials issued (vendors.issue/accept), RLUSD on TREASURY.
"""
from __future__ import annotations

import argparse
import json

from . import config, jobs, vendors
from .burn import burn
from .compiler import compile_sentence
from .fund import fund_burner
from .ledger import client, rlusd_balance
from .lock import is_locked, lock_burner
from .pay import pay, refusal_single_signer


def say(step: str, payload) -> None:
    print(f"\n[{step}]")
    print(json.dumps(payload, indent=2, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sentence")
    ap.add_argument("--burner", default="BURNER_1", help="role name of a pooled burner")
    ap.add_argument("--job", help="existing job id (skip create/lock/fund)")
    ap.add_argument("--vendor-a", default=None); ap.add_argument("--vendor-b", default=None)
    ap.add_argument("--amount", default="0.5")
    ap.add_argument("--burn", action="store_true")
    ap.add_argument("--batch-lock", action="store_true", help="try the Batch form first (falls back to sequential)")
    args = ap.parse_args()
    c = client()
    agent = config.wallet("AGENT")
    vendor_a = args.vendor_a or config.address("VENDOR_A")
    vendor_b = args.vendor_b or config.address("VENDOR_B")

    if args.job:
        job = jobs.get(args.job)
    else:
        card = compile_sentence(args.sentence)
        say("conditions card (the owner signs this)", card)
        burner = config.wallet(args.burner)
        job = jobs.create(args.sentence, card, burner.classic_address)
        say("job", {k: job[k] for k in ("id", "burner", "budget", "expires_at", "tag")})
        say("lock (Batch: TrustSet → SignerListSet → AccountSet)",
            lock_burner(burner, agent.classic_address, config.address("CEREAL_COSIGN"), job["budget"], c,
                        job_id=job["id"], tag=job["tag"], sequential=not args.batch_lock))
        say("lock state", is_locked(c, burner.classic_address))
        say("fund (software path; the device path is ledger/)",
            fund_burner(config.wallet("TREASURY"), burner.classic_address, job["budget"], job["id"], job["tag"], c))
        jobs.update(job["id"], status="funded")
    say("balance", {"burner": job["burner"], "rlusd": str(rlusd_balance(c, job["burner"]))})

    say("vendor A credential", vendors.check(c, vendor_a))
    say("pay vendor A (agent signs → cereal co-signs)", pay(job, vendor_a, args.amount, agent, c))
    say("vendor B credential (expected: none, revoked)", vendors.check(c, vendor_b))
    say("pay vendor B (expected: refused by cereal)", pay(job, vendor_b, args.amount, agent, c))
    say("jailbreak: agent signs alone (expected: tefBAD_QUORUM)", refusal_single_signer(job, vendor_a, args.amount, agent, c))
    over = str(rlusd_balance(c, job["burner"]) + 1)
    say(f"over budget {over} (expected: refused over_budget by cereal; on-ledger it would be tecPATH_PARTIAL)",
        pay(job, vendor_a, over, agent, c))

    if args.burn:
        say("burn (sweep → trustset 0 → AccountDelete)",
            burn(job["burner"], config.address("TREASURY"), agent, config.wallet("CEREAL_COSIGN"), c, job["id"], job["tag"]))
        jobs.update(job["id"], status="burned")


if __name__ == "__main__":
    main()
