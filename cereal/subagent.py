"""p1.5 — a subagent: one task, one budget, one key, one subwallet. Runs as its own process.

    python -m cereal.subagent <deployment_id> "<task>" [--payments 2] [--amount 0.25] [--prove-lock]

It loads only its own key (keys/subagents/<id>.json), talks to the cereal service for its record and for every
co-signature, and can never sign alone (a solo submit is refused by the ledger with tefBAD_QUORUM).
With ANTHROPIC_API_KEY it reasons with tools; without it, it runs a deterministic plan.
Prints one JSON line per action and a final {"event": "done", ...} line.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal

import requests

from . import config, keystore, llm
from .ledger import client, multisign_submit
from .pay import agent_sign, build_payment, request_cosign


class Subagent:
    def __init__(self, dep_id: str):
        self.dep_id = dep_id
        self.key = keystore.load(dep_id)
        self.c = client()

    def record(self) -> dict:
        return requests.get(f"{config.SERVICE_URL}/subagents/{self.dep_id}", timeout=30).json()

    # ---- tools ----
    def budget_left(self) -> dict:
        """How much RLUSD is left in my subwallet, my allowed payees and my expiry."""
        r = self.record()
        return {"remaining_rlusd": r.get("balance"), "allowed_payees": r["allowed_payees"], "expires_at": r["expires_at"]}

    def pay(self, payee: str, amount: str, invoice_id: str | None = None) -> dict:
        """Pay a payee from my subwallet in RLUSD. I sign; cereal checks policy and co-signs."""
        r = self.record()
        tx = build_payment(r["subwallet"], payee, str(amount), self.dep_id, r["tag"], invoice_id)
        return request_cosign(self.dep_id, agent_sign(tx, self.key, self.c),
                              url=f"{config.SERVICE_URL}/cosign", deployment=True)

    def done(self, summary: str) -> dict:
        """Report that my task is finished, with a one-line summary."""
        return requests.post(f"{config.SERVICE_URL}/subagents/{self.dep_id}/done", json={"summary": summary},
                             timeout=30).json()

    def prove_lock(self) -> dict:
        """Submit a payment with only my own signature. The ledger must refuse it (tefBAD_QUORUM)."""
        r = self.record()
        tx = build_payment(r["subwallet"], r["allowed_payees"][0], "0.01", self.dep_id, r["tag"])
        return multisign_submit(tx, [self.key], self.c, quorum_signers=2)


def emit(event: str, data) -> None:
    print(json.dumps({"event": event, "data": data}, default=str), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("deployment_id"); ap.add_argument("task")
    ap.add_argument("--payments", type=int, default=2); ap.add_argument("--amount", default=None)
    ap.add_argument("--prove-lock", action="store_true")
    a = ap.parse_args()
    s = Subagent(a.deployment_id)
    rec = s.record()
    budget = Decimal(rec["budget"])
    amount = a.amount or str(min(Decimal("0.25"), (budget / 4).quantize(Decimal("0.01"))))
    emit("start", {"deployment": a.deployment_id, "subwallet": rec["subwallet"], "subagent": rec["subagent"],
                   "budget": rec["budget"], "task": a.task, "mode": "llm" if llm.available() else "plan"})
    if a.prove_lock:
        emit("prove_lock", s.prove_lock())
    if llm.available():
        system = (f"You are a cereal subagent. Task: {a.task}. You have a subwallet with {rec['budget']} RLUSD and may "
                  f"pay only {rec['allowed_payees']}. Each purchase from the vendor costs {amount} RLUSD. Make "
                  f"{a.payments} purchases with pay(), never exceed budget_left(), then call done() with a summary.")
        tools = {
            "budget_left": ({"type": "object", "properties": {}}, s.budget_left),
            "pay": ({"type": "object", "properties": {"payee": {"type": "string"}, "amount": {"type": "string"},
                                                       "invoice_id": {"type": "string"}},
                     "required": ["payee", "amount"]}, s.pay),
            "done": ({"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}, s.done),
        }
        llm.run_tool_loop(system, f"Begin: {a.task}", tools, on_event=emit)
    else:
        payee = rec["allowed_payees"][0]
        for i in range(a.payments):
            emit("pay", s.pay(payee, amount, invoice_id=None))
        s.done(f"{a.task}: made {a.payments} purchases of {amount} RLUSD from {payee}")
    final = s.record()
    emit("done", {"deployment": a.deployment_id, "remaining": final.get("balance"),
                  "payments": [{k: p.get(k) for k in ("to", "amount", "result", "hash")} for p in final["payments"]]})


if __name__ == "__main__":
    main()
