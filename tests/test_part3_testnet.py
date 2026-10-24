"""Part 3 acceptance on the live XRPL testnet with the Ledger device (Speculos). Opt-in: `make acceptance`.

Own service on :8013 with device funding and the recovery signer ON. Checks: the owner rejects a budget on the
device and nothing touches the ledger; the owner approves and the main wallet's funding Payment is signed by the
device alone; every subwallet carries the device at weight 2; cereal alone cannot spend; the owner takes the money
back with the device alone (no cereal key, no service). Cost: 0.25 RLUSD to vendor A, small XRP fees, ~1.9 XRP reserve.
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

from cereal import config, device
from cereal.ledger import account_info, client, multisign_submit, rlusd_balance
from cereal.lock import is_locked

pytestmark = pytest.mark.testnet
PORT = 8013
URL = f"http://localhost:{PORT}"
STORE = config.ROOT / "deployments.testnet3.json"
A, MAIN, DEV = config.address("VENDOR_A"), config.address("TREASURY"), config.LEDGER_ADDRESS


@pytest.fixture(scope="module")
def service():
    if not DEV or not device.available():
        pytest.skip("needs LEDGER_ADDRESS and the Speculos device (docker start speculos-xrp)")
    env = {**os.environ, "CEREAL_DEPLOYMENTS_FILE": str(STORE), "CEREAL_REQUIRE_VENDOR_CREDENTIAL": "1",
           "CEREAL_LEDGER_RECOVERY": "1", "CEREAL_DEVICE_FUNDING": "1", "CEREAL_DEVICE_DECISION": "approve"}
    log = open("/tmp/cereal-acceptance3-service.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "cereal.service:app", "--port", str(PORT)],
                            cwd=str(config.ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            if requests.get(f"{URL}/health", timeout=2).ok:
                break
        except requests.ConnectionError:
            time.sleep(0.5)
    else:
        proc.terminate(); pytest.fail("test service did not start; see /tmp/cereal-acceptance3-service.log")
    old = (config.SERVICE_URL, config.DEPLOYMENTS_FILE)
    config.SERVICE_URL, config.DEPLOYMENTS_FILE = URL, STORE  # Subagent and recover read these in-process
    yield URL
    config.SERVICE_URL, config.DEPLOYMENTS_FILE = old
    proc.terminate(); proc.wait(timeout=10); log.close()


def _post(path, body=None):
    return requests.post(f"{URL}{path}", json=body or {}, timeout=600).json()


def _get(path):
    return requests.get(f"{URL}{path}", timeout=60).json()


def _tx(c, h):
    for _ in range(30):
        r = c.request(Tx(transaction=h)).result
        if r.get("validated"):
            return r.get("tx_json", r), r["meta"]
        time.sleep(1)
    raise AssertionError(f"{h} not validated")


def _signed_by_device_only(c, h, account):
    tx, meta = _tx(c, h)
    assert meta["TransactionResult"] == "tesSUCCESS", (h, meta["TransactionResult"])
    assert tx["Account"] == account and tx["SigningPubKey"] == ""
    assert [s["Signer"]["Account"] for s in tx["Signers"]] == [DEV], tx["Signers"]
    return tx


def test_part3_acceptance(service):
    c = client()
    ev = {"started": datetime.now(timezone.utc).isoformat(), "checks": {}}
    chk = ev["checks"]
    pol = _get("/main")["policy"]
    assert pol["device_funding"] and pol["ledger_recovery"] and pol["device"] == DEV
    main_before = rlusd_balance(c, MAIN)

    # 1. the owner rejects the budget on the device: refused, and not one transaction from the main wallet
    seq0 = int(account_info(c, MAIN)["Sequence"])
    r = _post("/subagents", {"task": "part 3 reject", "budget": "1", "speculos_decision": "reject"})
    assert r.get("refused") == "owner_rejected" and r["sent_transactions"] == 0, r
    assert "Amount: 1" in r["screens"] and "Currency: RLUSD" in r["screens"], r["screens"]
    assert int(account_info(c, MAIN)["Sequence"]) == seq0
    assert _get(f"/subagents/{r['deployment']}")["status"] == "rejected"
    chk["rejected"] = {"deployment": r["deployment"], "screens": r["screens"]}

    # 2. the owner approves: the device saw this subwallet and this amount; the funding is signed by the device alone
    dep = _post("/subagents", {"task": "part 3 approve", "budget": "1", "speculos_decision": "approve"})
    assert dep.get("ok"), dep
    ap = dep["approval"]
    assert ap["result"] == "approved" and ap["by"] == DEV
    assert f"Destination: {dep['subwallet']}" in ap["screens"] and "Amount: 1" in ap["screens"], ap["screens"]
    ftx = _signed_by_device_only(c, dep["hashes"]["fund"], MAIN)
    assert ftx["Destination"] == dep["subwallet"] and (ftx.get("Amount") or ftx["DeliverMax"])["value"] == "1"
    chk["approved"] = {"deployment": dep["id"], "fund": dep["hashes"]["fund"], "activate": dep["hashes"]["activate"]}

    # 3. the subwallet carries the owner's device at weight 2
    st = is_locked(c, dep["subwallet"])
    assert st["locked"] and st["master_disabled"] and st["signer_quorum"] == 2
    assert dict(st["signers"]) == {dep["subagent"]: 1, config.address("CEREAL_COSIGN"): 1, DEV: 2}, st
    chk["signer_list"] = st["signers"]

    # 4. normal path unchanged: subagent + cereal pay a credentialed vendor
    from cereal.subagent import Subagent
    s = Subagent(dep["id"])
    p = s.pay(A, "0.25")
    assert p.get("ok"), p
    chk["pay_A"] = p["hash"]

    # 5. cereal alone cannot spend, nor can the subagent alone
    from cereal.pay import build_payment
    for who, wallet in (("cereal", config.wallet("CEREAL_COSIGN")), ("subagent", s.key)):
        r = multisign_submit(build_payment(dep["subwallet"], A, "0.1", dep["id"], dep["tag"]), [wallet], c,
                             quorum_signers=2)
        assert r["result"] == "tefBAD_QUORUM" and r["hash"] is None, (who, r)
    chk["alone"] = {"cereal": "tefBAD_QUORUM", "subagent": "tefBAD_QUORUM"}

    # 6. the owner takes the money back with the device alone: no cereal key, no service call
    from cereal.recover import recover_deployment
    out = recover_deployment(dep["id"])
    assert out["ok"], out
    steps = {st["step"]: st for st in out["steps"]}
    assert steps["sweep"]["amount"] == "0.75"
    for st in out["steps"]:
        _signed_by_device_only(c, st["hash"], dep["subwallet"])
    assert rlusd_balance(c, dep["subwallet"]) == 0
    assert not c.request(AccountLines(account=dep["subwallet"])).result.get("lines")
    assert _get(f"/subagents/{dep['id']}")["status"] == "recovered"
    chk["recovered"] = {st["step"]: st["hash"] for st in out["steps"]}

    # 7. reconcile: the main wallet is down exactly the one payment
    assert main_before - rlusd_balance(c, MAIN) == Decimal("0.25")

    ev["finished"] = datetime.now(timezone.utc).isoformat()
    path = config.ROOT / "exports" / f"part3-acceptance-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.parent.mkdir(exist_ok=True); path.write_text(json.dumps(ev, indent=2, default=str))
    print(f"\nPart 3 acceptance passed; evidence: {path}")
