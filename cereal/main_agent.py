"""p1.6 — the main agent: takes a goal and an envelope, deploys subagents into subwallets, waits, reclaims.

    python -m cereal.main_agent --goal "…" --envelope 2 --subagents 2 [--payee r…] [--prove-lock]
    python -m cereal.main_agent --retire-all          # later: AccountDelete every reclaimed subwallet (≥15 min old)

It holds no keys: every action is a call to the cereal service (CEREAL_SERVICE_URL), which enforces the caps and
owns the main-wallet and co-signer keys. Each subagent runs as its own process with its own key.
With ANTHROPIC_API_KEY it plans with tools; without it, it splits the goal evenly.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from decimal import ROUND_DOWN, Decimal

import requests

from . import config, llm

API = config.SERVICE_URL
EXPLORER = config.EXPLORER


def _get(path: str):
    return requests.get(f"{API}{path}", timeout=60).json()


def _post(path: str, body: dict | None = None, timeout: int = 180):
    return requests.post(f"{API}{path}", json=body or {}, timeout=timeout).json()


class MainAgent:
    def __init__(self, payees: list[str], prove_lock: bool = False):
        self.payees = payees
        self.prove_lock = prove_lock
        self.procs: dict[str, subprocess.Popen] = {}
        self.logs: dict[str, list[dict]] = {}

    # ---- tools (each is a service call; no keys here) ----
    def main_wallet(self) -> dict:
        """Main wallet balances, outstanding subagent budget and the caps."""
        return _get("/main")

    def deploy_subagent(self, task: str, budget: str, allowed_payees: list[str] | None = None) -> dict:
        """Deploy a subagent for one task into a new subwallet funded with exactly `budget` RLUSD."""
        return _post("/subagents", {"task": task, "budget": str(budget), "allowed_payees": allowed_payees or self.payees})

    def start_subagent(self, deployment_id: str, task: str, payments: int = 2) -> dict:
        """Launch the subagent process for a deployment (it signs with its own key only)."""
        cmd = [sys.executable, "-m", "cereal.subagent", deployment_id, task, "--payments", str(payments)]
        if self.prove_lock:
            cmd.append("--prove-lock")
        self.procs[deployment_id] = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                                     cwd=str(config.ROOT))
        return {"started": deployment_id}

    def wait_subagent(self, deployment_id: str, timeout_s: int = 300) -> dict:
        """Wait for a subagent process to finish and return its events."""
        p = self.procs[deployment_id]
        out, _ = p.communicate(timeout=timeout_s)
        events = []
        for line in out.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                events.append({"event": "log", "data": line})
        self.logs[deployment_id] = events
        return {"deployment": deployment_id, "exit": p.returncode, "events": events[-3:]}

    def list_subagents(self) -> list:
        """Every deployment with status and live balance."""
        return _get("/subagents")

    def reclaim_subagent(self, deployment_id: str) -> dict:
        """Sweep what is left in a subagent's subwallet back to the main wallet and close its trust line."""
        return _post(f"/subagents/{deployment_id}/reclaim")


def plan_even(goal: str, envelope: Decimal, n: int) -> list[tuple[str, str]]:
    each = (envelope / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return [(f"{goal} (part {i + 1} of {n})", str(each)) for i in range(n)]


def print_tree(agent: MainAgent, ids: list[str], before: dict, after: dict) -> None:
    print("\nmain wallet", before["address"])
    for dep_id in ids:
        r = _get(f"/subagents/{dep_id}")
        print(f"├─ subagent {r['subagent']}  [{r['status']}]  budget {r['budget']} RLUSD  task: {r['task']}")
        print(f"│  └─ subwallet {r['subwallet']}")
        h = r.get("hashes", {})
        print(f"│     activate {EXPLORER}/transactions/{h.get('activate')}")
        print(f"│     lock     " + ", ".join(x[:10] + "…" for x in h.get("lock", []) if x))
        print(f"│     fund     {EXPLORER}/transactions/{h.get('fund')}")
        for ev in agent.logs.get(dep_id, []):
            if ev.get("event") == "prove_lock":
                print(f"│     alone    {ev['data'].get('result')} (subagent signed by itself)")
        for p in r["payments"]:
            print(f"│     pay {p['amount']} → {p['to'][:10]}…  {p.get('result')}  {EXPLORER}/transactions/{p.get('hash')}")
        for x in h.get("reclaim", []) or []:
            print(f"│     reclaim  {EXPLORER}/transactions/{x}")
    paid = sum(Decimal(p["amount"]) for d in ids for p in _get(f"/subagents/{d}")["payments"] if p.get("ok"))
    delta = Decimal(before["rlusd"]) - Decimal(after["rlusd"])
    print(f"\nmain wallet RLUSD {before['rlusd']} → {after['rlusd']}  (Δ {delta}); subagent payments {paid}; "
          f"{'reconciled ✓' if abs(delta - paid) < Decimal('0.000001') else 'MISMATCH'}")


def run(goal: str, envelope: Decimal, n: int, payees: list[str], prove_lock: bool) -> None:
    agent = MainAgent(payees, prove_lock)
    before = agent.main_wallet()
    print(f"goal: {goal}\nenvelope: {envelope} RLUSD · main wallet {before['rlusd']} RLUSD · caps {before['caps']}")
    ids: list[str] = []
    if llm.available():
        def deploy_tool(task: str, budget: str) -> dict:
            r = agent.deploy_subagent(task, budget)
            if r.get("ok"):
                ids.append(r["id"])
            return {k: r.get(k) for k in ("ok", "id", "subwallet", "budget", "refused", "cap", "limit")}
        tools = {
            "main_wallet": ({"type": "object", "properties": {}}, agent.main_wallet),
            "deploy_subagent": ({"type": "object", "properties": {"task": {"type": "string"}, "budget": {"type": "string"}},
                                 "required": ["task", "budget"]}, deploy_tool),
            "start_subagent": ({"type": "object", "properties": {"deployment_id": {"type": "string"}, "task": {"type": "string"}},
                                "required": ["deployment_id", "task"]}, agent.start_subagent),
            "wait_subagent": ({"type": "object", "properties": {"deployment_id": {"type": "string"}},
                               "required": ["deployment_id"]}, agent.wait_subagent),
            "reclaim_subagent": ({"type": "object", "properties": {"deployment_id": {"type": "string"}},
                                  "required": ["deployment_id"]}, agent.reclaim_subagent),
        }
        system = (f"You are the main agent of a company's main wallet. Goal: {goal}. Envelope: {envelope} RLUSD in total. "
                  f"Split the goal into {n} subtasks, deploy one subagent per subtask with deploy_subagent (budgets must sum "
                  f"to at most the envelope), start each with start_subagent, wait for each, then reclaim every subagent. "
                  f"You hold no keys; the service enforces caps. Finish with a short report.")
        report = llm.run_tool_loop(system, "Start.", tools,
                                   on_event=lambda name, out: print(f"  · {name}: {json.dumps(out, default=str)[:160]}"))
        print("\nmain agent report:", report)
    else:
        for task, budget in plan_even(goal, envelope, n):
            r = agent.deploy_subagent(task, budget)
            print(f"deploy {budget} RLUSD → {r.get('id')} {r.get('subwallet')} {'ok' if r.get('ok') else r}")
            if r.get("ok"):
                ids.append(r["id"]); agent.start_subagent(r["id"], task)
        for d in ids:
            w = agent.wait_subagent(d)
            print(f"subagent {d} finished (exit {w['exit']})")
        for d in ids:
            rc = agent.reclaim_subagent(d)
            print(f"reclaim {d}: returned {rc.get('returned')} RLUSD {'ok' if rc.get('ok') else rc}")
    time.sleep(2)
    print_tree(agent, ids, before, agent.main_wallet())
    print("\nretire the subwallets in ~15 minutes: python -m cereal.main_agent --retire-all")


def retire_all() -> None:
    for r in _get("/subagents"):
        if r["status"] == "reclaimed":
            out = _post(f"/subagents/{r['id']}/retire")
            print(r["id"], r["subwallet"], out.get("result") or out.get("refused"), out.get("hash") or out.get("ready_in_ledgers", ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal"); ap.add_argument("--envelope", default="2"); ap.add_argument("--subagents", type=int, default=2)
    ap.add_argument("--payee", action="append"); ap.add_argument("--prove-lock", action="store_true")
    ap.add_argument("--retire-all", action="store_true")
    a = ap.parse_args()
    if a.retire_all:
        return retire_all()
    run(a.goal, Decimal(a.envelope), a.subagents, a.payee or [config.address("VENDOR_A")], a.prove_lock)


if __name__ == "__main__":
    main()
