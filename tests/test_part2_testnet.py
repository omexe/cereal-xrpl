"""Part 2 acceptance on the live XRPL testnet (opt-in: `make acceptance`).

Own service on :8012 with vendor credentials ON and its own deployments file. Vendor B goes through its whole
lifecycle on-ledger: issued → refused while pending → accepted → paid → revoked → refused with the exact public
revocation hash. Plus both hijack layers and the stolen-keys cap. Vendor B ends revoked again (the demo state).
Cost: ~0.5 RLUSD paid to our own vendor accounts, small XRP fees, ~1.9 XRP reserve held until retire.
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
from xrpl.wallet import Wallet

from cereal import config, vendors
from cereal.ledger import account_info, client, decode_memos, multisign_submit, rlusd_balance

pytestmark = pytest.mark.testnet
PORT = 8012
URL = f"http://localhost:{PORT}"
STORE = config.ROOT / "deployments.testnet2.json"
A, B = config.address("VENDOR_A"), config.address("VENDOR_B")
MAIN, ISSUER = config.address("TREASURY"), config.address("CREDENTIAL_ISSUER")


@pytest.fixture(scope="module")
def service():
    env = {**os.environ, "CEREAL_DEPLOYMENTS_FILE": str(STORE), "CEREAL_REQUIRE_VENDOR_CREDENTIAL": "1",
           "CEREAL_LEDGER_RECOVERY": "0", "CEREAL_DEVICE_FUNDING": "0"}
    log = open("/tmp/cereal-acceptance2-service.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "cereal.service:app", "--port", str(PORT)],
                            cwd=str(config.ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            if requests.get(f"{URL}/health", timeout=2).ok:
                break
        except requests.ConnectionError:
            time.sleep(0.5)
    else:
        proc.terminate(); pytest.fail("test service did not start; see /tmp/cereal-acceptance2-service.log")
    os.environ["CEREAL_SERVICE_URL"] = URL
    old = (config.SERVICE_URL, config.DEPLOYMENTS_FILE)
    config.SERVICE_URL, config.DEPLOYMENTS_FILE = URL, STORE  # beats.stolen_keys reads the record in-process
    yield URL
    config.SERVICE_URL, config.DEPLOYMENTS_FILE = old
    proc.terminate(); proc.wait(timeout=10); log.close()


def _post(path, body=None):
    return requests.post(f"{URL}{path}", json=body or {}, timeout=240).json()


def _get(path):
    return requests.get(f"{URL}{path}", timeout=60).json()


def _tx(c, h):
    for _ in range(20):
        r = c.request(Tx(transaction=h)).result
        if r.get("validated"):
            return r.get("tx_json", r), r["meta"]
        time.sleep(1)
    raise AssertionError(f"{h} not validated")


@pytest.fixture
def restore_vendor_b():
    """If the test dies mid-lifecycle, put vendor B back to revoked so the demo state holds."""
    yield
    c = client()
    if vendors.check(c, B)["status"] in ("valid", "pending", "expired"):
        vendors.revoke(config.wallet("CREDENTIAL_ISSUER"), B, c, reason="overcharge", report_hash="demo-restore")


def test_part2_acceptance(service, restore_vendor_b):
    c = client()
    ev = {"started": datetime.now(timezone.utc).isoformat(), "checks": {}}
    chk = ev["checks"]
    assert _get("/main")["policy"]["vendor_credentials"] is True

    # 0. one subagent with no allowlist: it may pay any vendor credentialed on-ledger
    main_before = rlusd_balance(c, MAIN)
    dep = _post("/subagents", {"task": "part 2 acceptance", "budget": "1"})
    assert dep.get("ok"), dep
    assert dep["allowed_payees"] == []
    from cereal.subagent import Subagent
    s = Subagent(dep["id"])

    # 1. vendor A is credentialed: paid
    assert vendors.check(c, A)["status"] == "valid"
    r = s.pay(A, "0.25")
    assert r.get("ok"), r
    chk["pay_A"] = r["hash"]

    # 2. vendor B lifecycle. Start from revoked (demo state) or none.
    assert vendors.check(c, B)["status"] in ("revoked", "none")
    issued = vendors.issue(config.wallet("CREDENTIAL_ISSUER"), B, c)
    assert issued["ok"], issued
    assert vendors.check(c, B)["status"] == "pending"
    r = s.pay(B, "0.1")
    assert r.get("refused") == "vendor_not_credentialed" and r["vendor"]["status"] == "pending", r
    accepted = vendors.accept(config.wallet("VENDOR_B"), ISSUER, c)
    assert accepted["ok"], accepted
    assert vendors.check(c, B)["status"] == "valid"
    r = s.pay(B, "0.25")
    assert r.get("ok"), r
    tx, meta = _tx(c, r["hash"])
    assert meta["TransactionResult"] == "tesSUCCESS" and tx["Destination"] == B
    chk["B_lifecycle"] = {"issue": issued["hash"], "accept": accepted["hash"], "paid": r["hash"]}

    # 3. revoke B publicly; the refusal must carry exactly that transaction as evidence
    revoked = vendors.revoke(config.wallet("CREDENTIAL_ISSUER"), B, c, reason="overcharge",
                             report_hash="test-report-001")
    assert revoked["ok"], revoked
    rtx, rmeta = _tx(c, revoked["hash"])
    assert rtx["TransactionType"] == "CredentialDelete" and rtx["Subject"] == B and rtx["Account"] == ISSUER
    assert json.loads(bytes.fromhex(rtx["Memos"][0]["Memo"]["MemoData"]).decode())["reason"] == "overcharge"
    st = vendors.check(c, B)
    assert st["status"] == "revoked" and st["revocation"]["hash"] == revoked["hash"], st
    seq = int(account_info(c, dep["subwallet"])["Sequence"])
    r = s.pay(B, "0.1")
    assert r.get("refused") == "vendor_not_credentialed", r
    assert r["vendor"]["status"] == "revoked" and r["vendor"]["revocation"]["hash"] == revoked["hash"], r
    assert int(account_info(c, dep["subwallet"])["Sequence"]) == seq, "a refused payment must not send a transaction"
    chk["B_revoked"] = {"revoke": revoked["hash"], "refusal_evidence": r["vendor"]["revocation"]["hash"]}

    # 4. hijack: cereal refuses the attacker (no credential), then the agent alone is refused by the ledger
    attacker = Wallet.create().classic_address
    left = s.budget_left()["remaining_rlusd"]
    r1 = s.pay(attacker, left)
    assert r1.get("refused") == "vendor_not_credentialed" and r1["vendor"]["status"] == "none", r1
    rec = _get(f"/subagents/{dep['id']}")
    from cereal.pay import build_payment
    r2 = multisign_submit(build_payment(dep["subwallet"], attacker, left, dep["id"], rec["tag"]), [s.key], c,
                          quorum_signers=2)
    assert r2["result"] == "tefBAD_QUORUM" and r2["hash"] is None, r2
    chk["hijack"] = {"layer1": r1["refused"], "layer2": r2["result"]}

    # 5. refusals are recorded on the deployment with their evidence
    refusals = _get(f"/subagents/{dep['id']}")["refusals"]
    assert sum(1 for f in refusals if f.get("refused") == "vendor_not_credentialed") >= 3
    assert any((f.get("vendor") or {}).get("revocation", {}) and f["vendor"]["revocation"]["hash"] == revoked["hash"]
               for f in refusals)

    # 6. stolen keys (subagent + co-signer): capped by the balance on-ledger; useless on the main wallet
    from cereal.beats import stolen_keys
    bal = rlusd_balance(c, dep["subwallet"])
    drain, main_try = stolen_keys(dep["id"])
    assert drain["result"] == "tecPATH_PARTIAL" and drain["hash"], drain
    _, dmeta = _tx(c, drain["hash"])
    assert dmeta["TransactionResult"] == "tecPATH_PARTIAL"
    assert rlusd_balance(c, dep["subwallet"]) == bal, "an over-balance drain moves nothing"
    assert main_try["result"].startswith("tef") and main_try["hash"] is None, main_try
    chk["stolen_keys"] = {"drain": drain["hash"], "main_wallet": main_try["result"]}

    # 7. reclaim and reconcile: the main wallet lost exactly the two successful payments
    rc = _post(f"/subagents/{dep['id']}/reclaim")
    assert rc.get("ok"), rc
    assert main_before - rlusd_balance(c, MAIN) == Decimal("0.50")
    assert vendors.check(c, B)["status"] == "revoked"  # demo state restored

    ev["finished"] = datetime.now(timezone.utc).isoformat()
    out = config.ROOT / "exports" / f"part2-acceptance-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(ev, indent=2, default=str))
    print(f"\nPart 2 acceptance passed; evidence: {out}")
