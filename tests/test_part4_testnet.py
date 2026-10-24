"""Part 4 acceptance on the live XRPL testnet: a subagent pays x402 paywalls through the t54 facilitator.

Own service on :8014 (device off, for speed) and two x402 paywalls: vendor A (credentialed) on :8010 and vendor B
(revoked) on :8016. Checks: the facilitator accepts the 2-of-2 subwallet's co-signed payment and the vendor serves
the resource; the on-ledger payment is multisigned by subagent + cereal with cereal's memo and the x402 invoice;
cereal refuses the revoked vendor's paywall before anything is signed for it; a price over the limit is refused;
the main wallet reconciles. Cost: 0.25 RLUSD to vendor A, small XRP fees, ~1.9 XRP reserve until retire.
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
from xrpl.models.requests import Tx

from cereal import config
from cereal.ledger import account_info, client, decode_memos, rlusd_balance

pytestmark = pytest.mark.testnet
PORT, A_PORT, B_PORT = 8014, 8010, 8016
URL = f"http://localhost:{PORT}"
STORE = config.ROOT / "deployments.testnet4.json"
A, B, MAIN = config.address("VENDOR_A"), config.address("VENDOR_B"), config.address("TREASURY")


def _start(args, env, log, health):
    proc = subprocess.Popen(args, cwd=str(config.ROOT), env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            if requests.get(health, timeout=2).ok:
                return proc
        except requests.ConnectionError:
            time.sleep(0.5)
    proc.terminate()
    pytest.fail(f"{args} did not start; see {log}")


@pytest.fixture(scope="module")
def stack():
    base = {**os.environ, "CEREAL_DEPLOYMENTS_FILE": str(STORE), "CEREAL_REQUIRE_VENDOR_CREDENTIAL": "1",
            "CEREAL_DEVICE_FUNDING": "0", "CEREAL_LEDGER_RECOVERY": "0"}
    procs = [
        _start([sys.executable, "-m", "uvicorn", "cereal.service:app", "--port", str(PORT)], base,
               "/tmp/cereal-acceptance4-service.log", f"{URL}/health"),
        _start([sys.executable, "x402/server.py"], {**base, "X402_PORT": str(A_PORT), "XRPL_PAY_TO": A},
               "/tmp/cereal-acceptance4-vendor-a.log", f"http://localhost:{A_PORT}/health"),
        _start([sys.executable, "x402/server.py"], {**base, "X402_PORT": str(B_PORT), "XRPL_PAY_TO": B},
               "/tmp/cereal-acceptance4-vendor-b.log", f"http://localhost:{B_PORT}/health"),
    ]
    old = (config.SERVICE_URL, config.DEPLOYMENTS_FILE)
    config.SERVICE_URL, config.DEPLOYMENTS_FILE = URL, STORE
    yield
    config.SERVICE_URL, config.DEPLOYMENTS_FILE = old
    for p in procs:
        p.terminate(); p.wait(timeout=10)


def _tx(c, h):
    for _ in range(30):
        r = c.request(Tx(transaction=h)).result
        if r.get("validated"):
            return r.get("tx_json", r), r["meta"]
        time.sleep(1)
    raise AssertionError(f"{h} not validated")


def test_part4_x402_acceptance(stack):
    c = client()
    ev = {"started": datetime.now(timezone.utc).isoformat(), "checks": {}}
    chk = ev["checks"]
    main_before = rlusd_balance(c, MAIN)
    dep = requests.post(f"{URL}/subagents", json={"task": "part 4 x402 acceptance", "budget": "1"}, timeout=300).json()
    assert dep.get("ok"), dep
    from cereal.subagent import Subagent
    s = Subagent(dep["id"])

    # 1. vendor A's paywall: 402 → co-signed payment → t54 verifies and settles → the resource is served
    r = s.buy(f"http://localhost:{A_PORT}/swell/agenda")
    assert r["ok"] and r["status"] == 200 and r["data"]["data"]["event"], r
    assert r["settlement"]["success"] and r["settlement"]["transaction"] == r["hash"]
    att = (r["settlement"].get("extensions") or {}).get("t54Attestation") or {}
    chk["x402_paid"] = {"hash": r["hash"], "t54_attestation": att.get("status"), "retried_after_409": r.get("retried_after_409")}

    # 2. on-ledger: multisigned by exactly subagent + cereal, to vendor A, with cereal's memo first and the invoice bound
    tx, meta = _tx(c, r["hash"])
    assert meta["TransactionResult"] == "tesSUCCESS"
    assert tx["Account"] == dep["subwallet"] and tx["Destination"] == A and tx["SigningPubKey"] == ""
    assert {x["Signer"]["Account"] for x in tx["Signers"]} == {dep["subagent"], config.address("CEREAL_COSIGN")}
    assert (tx.get("Amount") or tx["DeliverMax"])["value"] == "0.25" and len(tx["InvoiceID"]) == 64
    m = decode_memos(tx)
    assert m[0]["job"] == dep["id"] and m[0]["rail"] == "x402"
    assert tx["SourceTag"] == config.SOURCE_TAG

    # 3. cereal's record resolves the presented payment from the ledger
    rec = requests.get(f"{URL}/subagents/{dep['id']}", timeout=60).json()
    p = next(x for x in rec["payments"] if x["hash"] == r["hash"])
    assert p["rail"] == "x402" and p["result"] == "tesSUCCESS" and p["resource"].endswith("/swell/agenda")

    # 4. vendor B's paywall (revoked): cereal refuses with the public revocation; nothing signed, nothing sent
    seq = int(account_info(c, dep["subwallet"])["Sequence"])
    rb = s.buy(f"http://localhost:{B_PORT}/swell/agenda")
    assert rb["refused"] == "vendor_not_credentialed" and rb["vendor"]["status"] == "revoked", rb
    assert rb["vendor"]["revocation"]["hash"]
    assert int(account_info(c, dep["subwallet"])["Sequence"]) == seq
    chk["x402_refused_B"] = {"revocation": rb["vendor"]["revocation"]["hash"]}

    # 5. the subagent's own limit: a price above it is refused before cereal is even asked
    rl = s.buy(f"http://localhost:{A_PORT}/swell/speakers", max_rlusd="0.1")
    assert rl["refused"] == "price_above_limit"
    assert int(account_info(c, dep["subwallet"])["Sequence"]) == seq

    # 6. reclaim and reconcile
    assert requests.post(f"{URL}/subagents/{dep['id']}/reclaim", timeout=240).json().get("ok")
    assert main_before - rlusd_balance(c, MAIN) == Decimal("0.25")

    ev["finished"] = datetime.now(timezone.utc).isoformat()
    path = config.ROOT / "exports" / f"part4-acceptance-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.parent.mkdir(exist_ok=True); path.write_text(json.dumps(ev, indent=2, default=str))
    print(f"\nPart 4 x402 acceptance passed; evidence: {path}")
