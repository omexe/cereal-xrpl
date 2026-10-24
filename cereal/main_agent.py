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

    def deploy_subagent(self, task: str, budget: str, allowed_payees: list[str] | None = None,
                        speculos_decision: str | None = None) -> dict:
        """Deploy a subagent for one task into a new subwallet funded with exactly `budget` RLUSD.

        With a Ledger configured the owner approves the budget on the device first (this call waits for it)."""
        body = {"task": task, "budget": str(budget), "allowed_payees": allowed_payees or self.payees}
        if speculos_decision:
            body["speculos_decision"] = speculos_decision
        return _post("/subagents", body, timeout=900)

    def start_subagent(self, deployment_id: str, task: str, payments: int = 2, extra: list[str] | None = None) -> dict:
        """Launch the subagent process for a deployment (it signs with its own key only)."""
        cmd = [sys.executable, "-m", "cereal.subagent", deployment_id, task, "--payments", str(payments)]
        if self.prove_lock:
            cmd.append("--prove-lock")
        cmd += extra or []
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

    def run_beat(self, name: str, deployment_id: str) -> list[dict]:
        """Run a demo beat process (e.g. stolen-keys) and return its events. The main agent itself holds no keys."""
        p = subprocess.run([sys.executable, "-m", "cereal.beats", name, deployment_id], capture_output=True, text=True,
                           cwd=str(config.ROOT), timeout=240)
        events = [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{")]
        self.logs.setdefault(deployment_id, []).extend(events)
        return events

    def reclaim_subagent(self, deployment_id: str) -> dict:
        """Sweep what is left in a subagent's subwallet back to the main wallet and close its trust line."""
        return _post(f"/subagents/{deployment_id}/reclaim")


def owner_recover(deployment_id: str) -> dict:
    """Not a main-agent tool: the OWNER takes a subwallet's money back with the Ledger alone (cereal/recover.py).

    No cereal key, no service call for signing: the device's weight 2 meets the subwallet's quorum by itself."""
    from .recover import recover_deployment
    return recover_deployment(deployment_id)


def plan_even(goal: str, envelope: Decimal, n: int) -> list[tuple[str, str]]:
    each = (envelope / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return [(f"{goal} (part {i + 1} of {n})", str(each)) for i in range(n)]


def _device_saw(screens: list[str]) -> str:
    f = dict(x.split(": ", 1) for x in screens if ": " in x)
    dest = f.get("Destination", "")
    return f"{f.get('Transaction Type', '?')} {f.get('Amount', '?')} {f.get('Currency', '')} → {dest[:10]}…".strip()


def print_tree(agent: MainAgent, ids: list[str], before: dict, after: dict, rejected: list[dict] | None = None) -> None:
    print("\nmain wallet", before["address"])
    for rj in rejected or []:
        print(f"├─ ✗ rejected on the owner's Ledger: {rj.get('task')}  (device showed {_device_saw(rj.get('screens', []))}); "
              f"transactions sent: {rj.get('sent_transactions', 0)}")
    for dep_id in ids:
        r = _get(f"/subagents/{dep_id}")
        print(f"├─ subagent {r['subagent']}  [{r['status']}]  budget {r['budget']} RLUSD  task: {r['task']}")
        print(f"│  └─ subwallet {r['subwallet']}")
        h = r.get("hashes", {})
        print(f"│     activate {EXPLORER}/transactions/{h.get('activate')}")
        print(f"│     lock     " + ", ".join(x[:10] + "…" for x in h.get("lock", []) if x))
        ap = r.get("approval")
        if ap:
            print(f"│     approve  owner {ap.get('result')} on Ledger {str(ap.get('by'))[:10]}…  (device showed {_device_saw(ap.get('screens', []))})")
        print(f"│     fund     {EXPLORER}/transactions/{h.get('fund')}" + ("  (signed by the Ledger alone)" if ap else ""))
        for ev in agent.logs.get(dep_id, []):
            e, d = ev.get("event"), ev.get("data", {})
            if e == "prove_lock":
                print(f"│     alone    {d.get('result')} (subagent signed by itself)")
            elif e == "hijack_instruction":
                print(f"│     hijack   injected: \"{d.get('text')}\"")
            elif e == "hijack_policy":
                print(f"│       layer 1 cereal: {d.get('refused') or d.get('result')} ({(d.get('vendor') or {}).get('status', '')})")
            elif e == "hijack_alone":
                print(f"│       layer 2 ledger: {d.get('result')} (agent went rogue and signed alone)")
            elif e == "stolen_keys":
                print(f"│     stolen keys: {d.get('attempt')}: {d.get('result')}"
                      + (f"  {EXPLORER}/transactions/{d['hash']}" if d.get("hash") else ""))
        for f in r.get("refusals", []):
            v = f.get("vendor") or {}
            ev = (v.get("revocation") or {}).get("hash")
            if (v.get("status") or f.get("refused")) and f.get("payee") and f.get("refused") == "vendor_not_credentialed" and ev:
                print(f"│     refused  {f['payee'][:10]}… vendor {v.get('status')}: {(v.get('revocation') or {}).get('reason', '')} "
                      f"(public revocation {EXPLORER}/transactions/{ev})")
        for p in r["payments"]:
            if p.get("rail") == "ap4m":  # Mastercard AP4M on XRPL EVM: voucher redeemed on PaymentLedger
                print(f"│     ap4m {p['amount']} → {str(p['to'])[:10]}…  {p.get('result')}  {p.get('explorer')}  (channel {str(p.get('channel_id'))[:10]}…)")
                continue
            via = f"x402 {p['resource'].split('//')[-1].split('/', 1)[-1]}" if p.get("rail") == "x402" and p.get("resource") else "pay"
            print(f"│     {via} {p['amount']} → {p['to'][:10]}…  {p.get('result')}  {EXPLORER}/transactions/{p.get('hash')}")
        for x in h.get("reclaim", []) or []:
            print(f"│     reclaim  {EXPLORER}/transactions/{x}")
        for x in h.get("recover", []) or []:
            print(f"│     recover  {EXPLORER}/transactions/{x}  (owner's Ledger alone: no cereal key)")
    paid = sum(Decimal(p["amount"]) for d in ids for p in _get(f"/subagents/{d}")["payments"] if p.get("ok"))
    delta = Decimal(before["rlusd"]) - Decimal(after["rlusd"])
    print(f"\nmain wallet RLUSD {before['rlusd']} → {after['rlusd']}  (Δ {delta}); subagent payments {paid}; "
          f"{'reconciled ✓' if abs(delta - paid) < Decimal('0.000001') else 'MISMATCH'}")


def _up(url: str) -> bool:
    try:
        return requests.get(f"{url}/health", timeout=3).ok
    except requests.RequestException:
        return False


def run(goal: str, envelope: Decimal, n: int, payees: list[str] | None, prove_lock: bool, beats: bool = False,
        device_beats: bool = False, x402: bool = False, ap4m: bool = False) -> None:
    before = _get("/main")
    if payees is None:  # Part 2: any vendor credentialed on-ledger; Part 1: allowlist vendor A
        payees = [] if before.get("policy", {}).get("vendor_credentials") else [config.address("VENDOR_A")]
    agent = MainAgent(payees, prove_lock or beats)
    print(f"goal: {goal}\nenvelope: {envelope} RLUSD · main wallet {before['rlusd']} RLUSD · caps {before['caps']}")
    ids: list[str] = []
    rejected: list[dict] = []
    if device_beats and not before.get("policy", {}).get("device_funding"):
        sys.exit("--device needs the Ledger configured: LEDGER_ADDRESS set and CEREAL_DEVICE_FUNDING not 0")
    if ap4m and not before.get("policy", {}).get("ap4m", {}).get("env_file"):
        sys.exit("--ap4m needs ap4m/.env (the AP4M agent key) and ap4m/node_modules (cd ap4m && npm ci)")
    if x402 and not _up(config.X402_VENDOR_A_URL):
        sys.exit(f"--x402 needs vendor A's paywall at {config.X402_VENDOR_A_URL} (make vendor)")
    if device_beats:  # the main agent asks for one budget too many; the owner says no on the device
        r = agent.deploy_subagent(f"{goal} (an extra subagent the owner did not ask for)", "1", speculos_decision="reject")
        print(f"deploy 1 RLUSD → owner {r.get('refused')} on the Ledger; transactions sent: {r.get('sent_transactions')}")
        rejected.append({"task": "an extra subagent the owner did not ask for", **r})
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
        for i, (task, budget) in enumerate(plan_even(goal, envelope, n)):
            r = agent.deploy_subagent(task, budget)
            print(f"deploy {budget} RLUSD → {r.get('id')} {r.get('subwallet')} {'ok' if r.get('ok') else r}")
            if r.get("ok"):
                ids.append(r["id"])
                extra = []
                if beats and i == 0:  # tries the revoked vendor first, falls back to a credentialed one
                    extra = ["--vendors", f"{config.address('VENDOR_B')},{config.address('VENDOR_A')}"]
                if beats and i == 1:  # receives a prompt-injected instruction after its purchases
                    extra = ["--hijack"]
                if x402:  # Part 4: buy over x402 paywalls; subagent 1 meets the revoked vendor's paywall first
                    a_url = config.X402_VENDOR_A_URL
                    urls = [f"{a_url}/swell/agenda", f"{a_url}/swell/speakers"]
                    if i == 0 and _up(config.X402_VENDOR_B_URL):
                        urls.insert(0, f"{config.X402_VENDOR_B_URL}/swell/agenda")
                    extra = [x for u in urls for x in ("--buy", u)]
                if ap4m:  # Part 4b: each subagent also buys once from the Mastercard AP4M merchant (its own Channel)
                    extra += ["--ap4m", config.AP4M_MERCHANT_URL]
                agent.start_subagent(r["id"], task, extra=extra)
        for d in ids:
            w = agent.wait_subagent(d)
            print(f"subagent {d} finished (exit {w['exit']})")
        if beats and len(ids) > 1:
            for ev in agent.run_beat("stolen-keys", ids[1]):
                print(f"beat stolen-keys {ids[1]}: {ev['data']['attempt']}: {ev['data'].get('result')}")
        recover_ids = ids[-1:] if device_beats else []
        for d in recover_ids:  # cereal goes dark: the owner's Ledger takes this subagent's money back alone
            out = owner_recover(d)
            sweep = next((st for st in out["steps"] if st["step"] == "sweep"), {})
            print(f"recover {d} with the owner's Ledger alone: returned {sweep.get('amount', '0')} RLUSD "
                  f"{'ok' if out.get('ok') else out}")
        for d in [x for x in ids if x not in recover_ids]:
            rc = agent.reclaim_subagent(d)
            print(f"reclaim {d}: returned {rc.get('returned')} RLUSD {'ok' if rc.get('ok') else rc}")
    time.sleep(2)
    print_tree(agent, ids, before, agent.main_wallet(), rejected)
    print("\nretire the subwallets in ~15 minutes: make retire")


def retire_all() -> int:
    """AccountDelete every reclaimed subwallet in CEREAL_DEPLOYMENTS_FILE (default deployments.json).

    Runs in-process, so it works without the service and on the test stores. Returns how many are still too young.
    """
    from . import deployments
    from .service import retire
    waiting = 0
    for r in deployments.all_():
        if r["status"] == "reclaimed":
            out = retire(r["id"])
            waiting += out.get("refused") == "too_young"
            print(r["id"], r["subwallet"], out.get("result") or out.get("refused"), out.get("hash") or out.get("ready_in_ledgers", ""))
    return waiting


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal"); ap.add_argument("--envelope", default="2"); ap.add_argument("--subagents", type=int, default=2)
    ap.add_argument("--payee", action="append"); ap.add_argument("--prove-lock", action="store_true")
    ap.add_argument("--retire-all", action="store_true")
    ap.add_argument("--beats", action="store_true", help="Part 2 demo: revoked vendor, hijack, stolen keys")
    ap.add_argument("--x402", action="store_true", help="Part 4 demo: subagents buy over x402 paywalls (t54); "
                                                        "vendor B's paywall is refused before any payment")
    ap.add_argument("--ap4m", action="store_true", help="Part 4b: each subagent also buys from the Mastercard AP4M "
                                                        "merchant (needs ap4m/merchant.mjs on :4308)")
    ap.add_argument("--device", action="store_true", help="Part 3 demo: owner rejects one budget on the Ledger, "
                                                          "approves the rest, recovers one subwallet alone")
    a = ap.parse_args()
    if a.retire_all:
        sys.exit(1 if retire_all() else 0)  # non-zero while some are still too young
    run(a.goal, Decimal(a.envelope), a.subagents, a.payee, a.prove_lock, a.beats, a.device, a.x402, a.ap4m)


if __name__ == "__main__":
    main()
