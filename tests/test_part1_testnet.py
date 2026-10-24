"""Part 1 acceptance on the live XRPL testnet (opt-in: `make acceptance` or `pytest --run-testnet -m testnet`).

Starts its own cereal service on :8011 with a tight outstanding cap (2.5 RLUSD) and its own deployments file, so it
never collides with a service already running on :8001. Every check is asserted against the ledger itself, not only
against API responses. Evidence (all hashes) is written to exports/part1-acceptance-<utc>.json.
Cost per run: ~1 RLUSD paid to vendor A (our own account) and ~3.8 XRP of reserves held until the subwallets retire.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import requests
from xrpl.models.requests import AccountLines, Tx

from cereal import config
from cereal.ledger import account_info, client, decode_memos, rlusd_balance
from cereal.lock import is_locked

pytestmark = pytest.mark.testnet
PORT = 8011
URL = f"http://localhost:{PORT}"
STORE = config.ROOT / "deployments.testnet.json"
VENDOR_A = config.address("VENDOR_A")
VENDOR_B = config.address("VENDOR_B")
MAIN = config.address("TREASURY")
COSIGNER = config.address("CEREAL_COSIGN")


@pytest.fixture(scope="module")
def service():
    env = {**os.environ, "CEREAL_DEPLOYMENTS_FILE": str(STORE), "MAX_SUBAGENT_BUDGET": "5",
           "MAX_OUTSTANDING_BUDGET": "2.5", "MAX_ACTIVE_SUBAGENTS": "5", "CEREAL_LEDGER_RECOVERY": "0",
           "CEREAL_REQUIRE_VENDOR_CREDENTIAL": "0", "CEREAL_DEVICE_FUNDING": "0"}
    log = open("/tmp/cereal-acceptance-service.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "cereal.service:app", "--port", str(PORT)],
                            cwd=str(config.ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            if requests.get(f"{URL}/health", timeout=2).ok:
                break
        except requests.ConnectionError:
            time.sleep(0.5)
    else:
        proc.terminate(); pytest.fail("test service did not start; see /tmp/cereal-acceptance-service.log")
    # subagent subprocesses inherit this; in-process modules are patched
    os.environ["CEREAL_SERVICE_URL"] = URL
    import cereal.main_agent as main_agent
    old = (config.SERVICE_URL, main_agent.API)
    config.SERVICE_URL, main_agent.API = URL, URL
    yield URL
    config.SERVICE_URL, main_agent.API = old
    proc.terminate(); proc.wait(timeout=10); log.close()


def _post(path, body=None):
    return requests.post(f"{URL}{path}", json=body or {}, timeout=240).json()


def _get(path):
    return requests.get(f"{URL}{path}", timeout=60).json()


def _tx(c, h: str) -> tuple[dict, dict]:
    """Validated transaction json and meta for a hash (waits briefly for validation)."""
    for _ in range(20):
        r = c.request(Tx(transaction=h)).result
        if r.get("validated"):
            return r.get("tx_json", r), r["meta"]
        time.sleep(1)
    raise AssertionError(f"{h} not validated")


def _seq(c, addr: str) -> int:
    return int(account_info(c, addr)["Sequence"])


def _amount(tx: dict):
    return tx.get("Amount") or tx.get("DeliverMax")


def test_part1_acceptance(service):
    c = client()
    ev: dict = {"started": datetime.now(timezone.utc).isoformat(), "service": URL, "checks": {}}
    check = ev["checks"]

    # 0. preconditions
    main = _get("/main")
    assert Decimal(main["rlusd"]) >= Decimal("2.5"), f"main wallet needs ≥2.5 RLUSD, has {main['rlusd']}"
    assert Decimal(main["xrp"]) >= Decimal("10"), f"main wallet needs ≥10 XRP, has {main['xrp']}"
    assert main["caps"]["MAX_OUTSTANDING_BUDGET"] == 2.5

    # 1. per-subagent cap: refused, nothing sent
    seq = _seq(c, MAIN)
    r = _post("/subagents", {"task": "too big", "budget": "6", "allowed_payees": [VENDOR_A]})
    assert r.get("refused") == "cap_exceeded" and r.get("cap") == "MAX_SUBAGENT_BUDGET", r
    assert _seq(c, MAIN) == seq, "a refused deploy must not send a transaction"
    check["cap_per_subagent"] = r

    # 2. deploy two subagents into two subwallets
    rlusd_before = rlusd_balance(c, MAIN)
    vendor_before = rlusd_balance(c, VENDOR_A)
    deps = []
    for i in range(2):
        d = _post("/subagents", {"task": f"acceptance subtask {i + 1}", "budget": "1", "allowed_payees": [VENDOR_A]})
        assert d.get("ok") and d.get("status") == "active", d
        deps.append(d)
    assert deps[0]["subwallet"] != deps[1]["subwallet"], "each subagent gets its own subwallet"
    assert deps[0]["subagent"] != deps[1]["subagent"], "each subagent gets its own key"
    for d in deps:
        h = d["hashes"]
        assert h.get("activate") and len(h.get("lock", [])) == 3 and all(h["lock"]) and h.get("fund"), h
        act, meta = _tx(c, h["activate"])
        assert meta["TransactionResult"] == "tesSUCCESS" and act["Account"] == MAIN and act["Destination"] == d["subwallet"]
        st = is_locked(c, d["subwallet"])
        assert st["master_disabled"] and st["signer_quorum"] == 2, st
        assert sorted(st["signers"]) == sorted([(d["subagent"], 1), (COSIGNER, 1)]), st
        assert rlusd_balance(c, d["subwallet"]) == Decimal("1")
        lines = c.request(AccountLines(account=d["subwallet"])).result["lines"]
        assert len(lines) == 1 and Decimal(lines[0]["limit"]) == Decimal("1"), "trust-line limit must equal the budget"
        fund, fmeta = _tx(c, h["fund"])
        assert fmeta["TransactionResult"] == "tesSUCCESS" and fund["Account"] == MAIN and fund["Destination"] == d["subwallet"]
        assert Decimal(_amount(fund)["value"]) == Decimal("1")
        assert decode_memos(fund)[0]["job"] == d["id"]
    check["deployments"] = [{k: d[k] for k in ("id", "subwallet", "subagent", "hashes")} for d in deps]

    # 3. outstanding cap (2 outstanding + 1 > 2.5): refused, nothing sent
    seq = _seq(c, MAIN)
    r = _post("/subagents", {"task": "over the envelope", "budget": "1", "allowed_payees": [VENDOR_A]})
    assert r.get("refused") == "cap_exceeded" and r.get("cap") == "MAX_OUTSTANDING_BUDGET", r
    assert _seq(c, MAIN) == seq
    check["cap_outstanding"] = r

    # 4. both subagents run as separate processes: prove the lock, pay twice each
    from cereal.main_agent import MainAgent
    agent = MainAgent([VENDOR_A], prove_lock=True)
    for d in deps:
        agent.start_subagent(d["id"], d["task"], payments=2)
    runs = {d["id"]: agent.wait_subagent(d["id"], timeout_s=300) for d in deps}
    check["subagents"] = {}
    for d in deps:
        events = agent.logs[d["id"]]
        assert runs[d["id"]]["exit"] == 0, events
        alone = [e["data"] for e in events if e.get("event") == "prove_lock"]
        assert alone and alone[0]["result"] == "tefBAD_QUORUM" and alone[0]["hash"] is None, alone
        pays = [e["data"] for e in events if e.get("event") == "pay"]
        assert len(pays) == 2 and all(p.get("result") == "tesSUCCESS" for p in pays), pays
        for p in pays:
            tx, meta = _tx(c, p["hash"])
            assert meta["TransactionResult"] == "tesSUCCESS"
            assert tx["Account"] == d["subwallet"] and tx["Destination"] == VENDOR_A
            assert tx.get("SigningPubKey", "") == "", "subwallet payments are multi-signed"
            signers = sorted(s["Signer"]["Account"] for s in tx["Signers"])
            assert signers == sorted([d["subagent"], COSIGNER]), signers
            assert tx.get("SourceTag") == config.SOURCE_TAG
            memo = decode_memos(tx)[0]
            assert memo["job"] == d["id"] and memo["kind"] == "pay"
        check["subagents"][d["id"]] = {"alone": alone[0]["result"], "payments": [p["hash"] for p in pays]}

    # 5. co-sign policy refusals: nothing reaches the ledger
    from cereal.subagent import Subagent
    s0 = Subagent(deps[0]["id"])
    seq = _seq(c, deps[0]["subwallet"])
    r_payee = s0.pay(VENDOR_B, "0.1")
    r_over = s0.pay(VENDOR_A, "5")
    assert r_payee.get("refused") == "payee_not_allowed", r_payee
    assert r_over.get("refused") == "over_budget", r_over
    assert _seq(c, deps[0]["subwallet"]) == seq, "refused payments must not send a transaction"
    check["policy_refusals"] = {"payee_not_allowed": r_payee, "over_budget": r_over}

    # 6. reclaim both: remainder home, trust line gone
    check["reclaim"] = {}
    for d in deps:
        r = _post(f"/subagents/{d['id']}/reclaim")
        assert r.get("ok") and Decimal(r["returned"]) == Decimal("0.5"), r
        sweep = next(s for s in r["steps"] if s["step"] == "sweep")
        tx, meta = _tx(c, sweep["hash"])
        assert meta["TransactionResult"] == "tesSUCCESS" and tx["Destination"] == MAIN
        assert c.request(AccountLines(account=d["subwallet"])).result["lines"] == [], "trust line must be deleted"
        assert _get(f"/subagents/{d['id']}")["status"] == "reclaimed"
        check["reclaim"][d["id"]] = [s["hash"] for s in r["steps"]]

    # 7. reconciliation: the main wallet lost exactly what the subagents paid; vendor A gained it
    paid = Decimal("1.0")
    assert rlusd_before - rlusd_balance(c, MAIN) == paid, (rlusd_before, rlusd_balance(c, MAIN))
    assert rlusd_balance(c, VENDOR_A) - vendor_before == paid
    check["reconciliation"] = {"main_before": str(rlusd_before), "main_after": str(rlusd_balance(c, MAIN)), "paid": str(paid)}

    # 8. retire is refused until the subwallet is old enough
    r = _post(f"/subagents/{deps[0]['id']}/retire")
    assert r.get("refused") == "too_young" and r.get("ready_in_ledgers", 0) > 0, r
    check["retire_too_early"] = r

    ev["finished"] = datetime.now(timezone.utc).isoformat()
    out = config.ROOT / "exports" / f"part1-acceptance-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(ev, indent=2, default=str))
    print(f"\nPart 1 acceptance passed; evidence: {out}")


def test_part1_retire_when_old_enough(service):
    """Retires every reclaimed subwallet in the test store that is old enough; skips if none are yet."""
    c = client()
    ready = [d for d in _get("/subagents") if d["status"] == "reclaimed"]
    if not ready:
        pytest.skip("no reclaimed subwallets in the test store")
    retired, waiting = [], []
    for d in ready:
        r = _post(f"/subagents/{d['id']}/retire")
        if r.get("refused") == "too_young":
            waiting.append((d["id"], r["ready_in_seconds"]))
            continue
        assert r.get("ok"), r
        with pytest.raises(Exception):
            account_info(c, d["subwallet"])  # actNotFound: the subwallet is gone
        retired.append((d["id"], r["hash"]))
    print(f"\nretired {retired}; waiting {waiting}")
    if not retired:
        pytest.skip(f"none old enough yet; rerun in ~{max(s for _, s in waiting) // 60 + 1} min")
