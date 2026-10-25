"""Live testnet check of site access (unit 3), in-process, before the probe (unit 1) and the registry (unit 2) exist.

Run inside the machine-wide testnet lock, next to a private cereal service the subagent talks to:

    .venv/bin/python scripts/with_testnet_lock.py -- bash -c 'CEREAL_SWEEPER=0 CEREAL_LLM=off \
        CEREAL_DEPLOYMENTS_FILE=deployments.e2e.json CEREAL_SERVICE_URL=http://127.0.0.1:8113 \
        .venv/bin/uvicorn cereal.service:app --port 8113 & pid=$!; sleep 6; \
        CEREAL_DEPLOYMENTS_FILE=deployments.e2e.json CEREAL_SERVICE_URL=http://127.0.0.1:8113 CEREAL_LLM=off \
        .venv/bin/python scripts/e2e_site_access.py; kill $pid'

Stand-ins (test only): sites_probe.safe_get fetches only the local test merchants (no redirects, bounded), and the
site registry is an in-memory dict. Everything else is real: the owner's Ledger (Speculos) approves the budget, the
wallet is locked and funded on testnet, the subagent pays Vendor C over x402 with cereal's co-signature, the wallet
sweeps home, and content() reads the delivered agenda back from the run log. Prints explorer links; never a seed.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from cereal import config, deployments, runs, site_access, site_registry, sites_probe  # noqa: E402

LOCAL = ("http://localhost:8003", "http://localhost:8004")
OWNER = {"id": "u_e2e_" + uuid.uuid4().hex[:6], "name": "e2e owner"}


def safe_get(url: str, *, headers: dict | None = None, max_bytes: int = 2_000_000, timeout: float = 20.0):
    """Test-only stand-in for unit 1's safe_get: the local test merchants only, no redirects, bounded body."""
    if not url.startswith(tuple(o + "/" for o in LOCAL)):
        raise sites_probe.UnsafeURL(f"the e2e stand-in only fetches {', '.join(LOCAL)}")
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False, stream=True)
    body = b""
    for chunk in r.iter_content(65536):
        body += chunk
        if len(body) >= max_bytes:
            body = body[:max_bytes]
            break
    r._content = body
    r.close()
    return r


SITES: dict[tuple[str, str], dict] = {}
sites_probe.safe_get = safe_get
site_registry.get = lambda owner_id, site_id: SITES.get((owner_id, site_id))


def _update(owner_id, site_id, **fields):
    site = SITES.get((owner_id, site_id))
    if site is not None:
        site.update(fields)
    return site


site_registry.update = _update


def tx(h: str | None) -> str | None:
    return f"{config.EXPLORER}/transactions/{h}" if h else None


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    print(f"records: {config.DEPLOYMENTS_FILE}  service: {config.SERVICE_URL}  owner: {OWNER['id']}", flush=True)

    # 1. a free page
    free = {"id": "s_free", "owner": OWNER["id"], "name": "Vendor D brief", "url": "http://localhost:8004/free/brief",
            "kind": "free", "trust": "free", "wallets": []}
    SITES[(OWNER["id"], free["id"])] = free
    opened = site_access.open_free(OWNER, free)
    print(json.dumps({k: v for k, v in opened.items() if k != "text"}), flush=True)
    print("text: " + (opened.get("text") or "")[:300].replace("\n", " | "), flush=True)
    check(opened.get("ok") is True and bool(opened.get("title")) and bool(opened.get("text")), "free page: title and text")

    # 2. a paid page on a public site (Vendor C, credentialed)
    vendor_c = config.address("VENDOR_C")
    probe = requests.get("http://localhost:8003/swell/agenda", timeout=20).json()["accepts"][0]
    site = {"id": "s_agenda", "owner": OWNER["id"], "name": "Vendor C agenda", "url": "http://localhost:8003/swell/agenda",
            "host": "localhost", "kind": "payable", "trust": "public", "status": 402,
            "payment": {"network": probe["network"], "amount": probe["amount"], "pay_to": probe["payTo"],
                        "resource": "http://localhost:8003/swell/agenda"}, "wallets": []}
    check(probe["payTo"] == vendor_c and probe["amount"] == "0.15", "Vendor C asks 0.15 RLUSD to VENDOR_C")
    SITES[(OWNER["id"], site["id"])] = site
    check(site_access.content(OWNER, site).get("refused") == "nothing_bought", "content before buying: nothing_bought")
    t0 = time.time()
    bought = site_access.buy(OWNER, site, speculos_decision="approve", request_id="e2e-" + uuid.uuid4().hex[:8])
    print(json.dumps({k: bought.get(k) for k in ("ok", "refused", "error", "hint")}), flush=True)
    check(bought.get("ok") is True, "buy started")
    w = bought["wallet"]
    dep = w["id"]
    rec = deployments.get(dep)
    print(json.dumps({k: rec.get(k) for k in ("id", "owner", "site", "budget", "allowed_payees", "buy_only",
                                              "sweep_when_done", "expires_at", "created_at", "subwallet", "hashes")}),
          flush=True)
    hours = (datetime.fromisoformat(rec["expires_at"]) - datetime.fromisoformat(rec["created_at"])).total_seconds() / 3600
    check(rec["owner"] == OWNER["id"] and rec["site"] == "s_agenda", "wallet: owner and site set")
    check(rec.get("buy_only") is True and rec.get("sweep_when_done") is True, "wallet: buy_only, sweep_when_done")
    check(rec["budget"] == "0.20" and rec["allowed_payees"] == [vendor_c], "wallet: budget 0.20, payee VENDOR_C only")
    check(abs(hours - 1) < 0.01, "wallet: 1 hour")
    check(bought["run"]["plan"]["buy"] == ["http://localhost:8003/swell/agenda@0.15"], "run: plan is exactly url@0.15")
    check(SITES[(OWNER["id"], "s_agenda")]["wallets"] == [dep], "site lists the wallet")

    # 3. wait for the run (this process launched and watches it)
    end = time.time() + 900
    while time.time() < end:
        run = (deployments.get(dep) or {}).get("run") or {}
        if run.get("status") not in runs.LIVE:
            break
        time.sleep(3)
    rec = deployments.get(dep)
    run = rec.get("run") or {}
    print(f"run {run.get('id')}: {run.get('status')} exit={run.get('exit_code')} after {time.time() - t0:.0f}s; "
          f"error={run.get('error')}", flush=True)
    for line in Path(run["log"]).read_text().splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            print("  log: " + line[:200])
            continue
        d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        print("  event " + ev.get("event", "?") + ": " + json.dumps({k: d.get(k) for k in (
            "ok", "refused", "resource", "price", "payee", "hash", "approved_by", "data_keys", "remaining")
            if k in d}), flush=True)
    check(run.get("status") == "succeeded", "run succeeded")

    # 4. the ledger: one settled payment to Vendor C, then the sweep home
    for _ in range(40):  # the record may lag the service's /done sweep by a moment
        rec = deployments.get(dep)
        if rec["status"] != "active":
            break
        time.sleep(3)
    rec = requests.get(f"{config.SERVICE_URL}/subagents/{dep}", timeout=60).json()  # resolves presented payments
    pays = [p for p in rec.get("payments", []) if p.get("ok")]
    for p in rec.get("payments", []):
        print(f"payment {p.get('amount')} RLUSD to {p.get('to')} result={p.get('result')} {tx(p.get('hash'))}")
    hashes = rec.get("hashes") or {}
    for k, v in hashes.items():
        for h in (v if isinstance(v, list) else [v]):
            print(f"{k}: {tx(h)}")
    print(f"wallet {dep}: status={rec['status']} returned={rec.get('returned')} balance={rec.get('balance')}")
    check(len(pays) == 1 and pays[0]["to"] == vendor_c and pays[0]["amount"] == "0.15"
          and pays[0].get("result") == "tesSUCCESS", "one validated 0.15 payment to Vendor C")
    check(rec["status"] == "reclaimed" and Decimal(str(rec.get("returned"))) == Decimal("0.05"),
          "wallet swept home (0.05 returned)")

    # 5. what the purchase delivered
    got = site_access.content(OWNER, SITES[(OWNER["id"], "s_agenda")])
    print(json.dumps({k: got.get(k) for k in ("ok", "refused", "wallet", "hash", "paid", "settled", "truncated",
                                              "explorer")}), flush=True)
    print("content: " + json.dumps(got.get("content"))[:400], flush=True)
    check(got.get("ok") is True and got["hash"] == pays[0]["hash"] and got["settled"] is True and got["paid"] == "0.15",
          "content: the settled payment's hash")
    check(isinstance(got.get("content"), dict) and bool(got["content"]), "content: the agenda JSON")
    print("E2E OK", flush=True)


def reclaim_leftovers() -> None:
    """Never leave an e2e wallet holding testnet RLUSD."""
    for rec in deployments.all_():
        if rec.get("owner") == OWNER["id"] and rec.get("status") == "active":
            out = requests.post(f"{config.SERVICE_URL}/subagents/{rec['id']}/reclaim", timeout=600).json()
            print(f"reclaimed leftover {rec['id']}: ok={out.get('ok')} {out.get('refused') or ''}", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        reclaim_leftovers()
