"""Part 5 acceptance on the live XRPL testnet with Speculos: vendor list, plan preview, plain-English wallets,
Ledger approval above a threshold (approve and reject), the security log, sweep when done, and the export.

Own service on :8015 (device on) and its own three paywalls: A :8020 (trusted), B :8022 (revoked), C :8023 (trusted).
Cost: 0.40 RLUSD to our own vendors, small XRP fees, ~1.9 XRP reserve until retire.
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
from xrpl.models.requests import AccountInfo, Tx

from cereal import config, device
from cereal.ledger import client, multisign_submit, rlusd_balance

pytestmark = pytest.mark.testnet
PORT = 8015
URL = f"http://localhost:{PORT}"
STORE = config.ROOT / "deployments.testnet5.json"
VEND = {"A": (8020, "VENDOR_A", "agenda:0.25,speakers:0.25"), "B": (8022, "VENDOR_B", "agenda:0.05,speakers:0.05"),
        "C": (8023, "VENDOR_C", "agenda:0.15,speakers:0.30")}
SENTENCE = ("Market Sizing: spend up to 1 RLUSD over 2 days, only at Vendor A and Vendor C. "
            "Ask me above 0.2. Sweep back when done.")


def _up(args, env, log, health):
    p = subprocess.Popen(args, cwd=str(config.ROOT), env=env, stdout=open(log, "w"), stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            if requests.get(health, timeout=2).ok:
                return p
        except requests.ConnectionError:
            time.sleep(0.5)
    p.terminate(); pytest.fail(f"{args[-1]} did not start; see {log}")


@pytest.fixture(scope="module")
def stack():
    if not config.LEDGER_ADDRESS or not device.available():
        pytest.skip("needs the Speculos device (docker start speculos-xrp)")
    base = {**os.environ, "CEREAL_DEPLOYMENTS_FILE": str(STORE), "CEREAL_REQUIRE_VENDOR_CREDENTIAL": "1",
            "CEREAL_DEVICE_FUNDING": "1", "CEREAL_LEDGER_RECOVERY": "1", "CEREAL_DEVICE_DECISION": "approve",
            "CEREAL_VENDORS": ",".join(f"http://localhost:{v[0]}" for v in VEND.values())}
    procs = []
    for name, (port, role, items) in VEND.items():
        procs.append(_up([sys.executable, "x402/server.py"], {**base, "X402_PORT": str(port), "X402_VENDOR": f"Vendor {name}",
                          "X402_ITEMS": items, "XRPL_PAY_TO": config.address(role)},
                         f"/tmp/cereal-acceptance5-vendor-{name}.log", f"http://localhost:{port}/health"))
    procs.append(_up([sys.executable, "-m", "uvicorn", "cereal.service:app", "--port", str(PORT)], base,
                     "/tmp/cereal-acceptance5-service.log", f"{URL}/health"))
    old = (config.SERVICE_URL, config.DEPLOYMENTS_FILE)
    config.SERVICE_URL, config.DEPLOYMENTS_FILE = URL, STORE
    yield
    config.SERVICE_URL, config.DEPLOYMENTS_FILE = old
    for p in procs:
        p.terminate(); p.wait(timeout=10)


def _get(path, **params):
    return requests.get(f"{URL}{path}", params=params, timeout=120).json()


def _post(path, body):
    return requests.post(f"{URL}{path}", json=body, timeout=900).json()


def _signers(c, h, names):
    for _ in range(30):
        r = c.request(Tx(transaction=h)).result
        if r.get("validated"):
            tx = r.get("tx_json", r)
            assert r["meta"]["TransactionResult"] == "tesSUCCESS", r["meta"]["TransactionResult"]
            return sorted(names.get(s["Signer"]["Account"], s["Signer"]["Account"]) for s in tx["Signers"])
        time.sleep(1)
    raise AssertionError(f"{h} not validated")


def test_part5_acceptance(stack):
    c = client()
    ev = {"started": datetime.now(timezone.utc).isoformat(), "checks": {}}
    chk = ev["checks"]
    main_before = rlusd_balance(c, config.address("TREASURY"))
    A, B, C = (config.address(r) for r in ("VENDOR_A", "VENDOR_B", "VENDOR_C"))

    # 1. vendor list: names and prices from catalogs, trust from the ledger
    vs = {v["name"]: v for v in _get("/vendors")}
    assert vs["Vendor A"]["credential"]["status"] == "valid" and vs["Vendor C"]["credential"]["status"] == "valid"
    assert vs["Vendor B"]["credential"]["status"] == "revoked" and vs["Vendor B"]["credential"]["revocation"]["hash"]
    assert {"item": "agenda", "price": "0.15"} in vs["Vendor C"]["items"]

    # 2. plan preview: cheapest trusted per need, revoked B skipped, nothing deployed
    n_before = len(_get("/subagents"))
    p = _get("/plan", goal="Pull the Swell agenda and speaker list", envelope="2")
    assert p["ok"] and p["total"] == "0.50"
    assert [l["chosen"]["vendor"] for l in p["lines"]] == ["Vendor C", "Vendor A"]
    assert all(any(r["vendor"] == "Vendor B" and r["reason"] == "vendor_revoked" for r in l["rejected"]) for l in p["lines"])
    assert len(_get("/subagents")) == n_before
    chk["plan"] = p["summary"]

    # 3. a card with problems deploys nothing
    bad = _post("/wallets", {"sentence": "Product X Research: $20 for 2 days, HubSpot, Clearbit and Apollo only, ask me above $5"})
    assert bad["refused"] == "card_problems" and len(_get("/subagents")) == n_before

    # 4. a wallet from a sentence, budget approved on the Ledger
    pv = _post("/wallets/preview", {"sentence": SENTENCE})
    assert pv["ok"] and pv["allowed_payees"] == [A, C] and pv["approval_threshold"] == "0.2"
    w = _post("/wallets", {"sentence": SENTENCE, "folder": "Market Research"})
    assert w.get("ok"), w
    assert w["approval"]["result"] == "approved" and w["approval_threshold"] == "0.2" and w["sweep_when_done"]
    names = {w["subagent"]: "subagent", config.address("CEREAL_COSIGN"): "cereal", config.LEDGER_ADDRESS: "Ledger"}
    from cereal.subagent import Subagent
    s = Subagent(w["id"])

    # 5. under the threshold: x402 from C, co-signed by cereal
    r1 = s.buy("http://localhost:8023/swell/agenda", max_rlusd="0.15")
    assert r1["ok"], r1
    assert _signers(c, r1["hash"], names) == ["cereal", "subagent"]

    # 6. over the threshold: x402 from A, signed by the owner's Ledger instead of cereal, accepted by t54
    r2 = s.buy("http://localhost:8020/swell/speakers", max_rlusd="0.25")
    assert r2["ok"], r2
    assert _signers(c, r2["hash"], names) == ["Ledger", "subagent"]
    chk["payments"] = {"under_threshold": r1["hash"], "over_threshold_ledger": r2["hash"]}

    # 7. over the threshold, owner rejects on the device: nothing sent
    from cereal import deployments
    deployments.update(w["id"], speculos_payment_decision="reject")
    seq = int(c.request(AccountInfo(account=w["subwallet"], ledger_index="validated")).result["account_data"]["Sequence"])
    r3 = s.pay(A, "0.25")
    assert r3.get("refused") == "owner_rejected" and r3["sent_transactions"] == 0, r3
    assert int(c.request(AccountInfo(account=w["subwallet"], ledger_index="validated")).result["account_data"]["Sequence"]) == seq

    # 8. a hijacked subagent signing alone: refused by the ledger, reported, shown in the security log
    from cereal.pay import build_payment
    from cereal.subagent import report
    alone = multisign_submit(build_payment(w["subwallet"], B, "0.1", w["id"], w["tag"]), [s.key], c, quorum_signers=2)
    assert alone["result"] == "tefBAD_QUORUM"
    report(w["id"], "hijack_alone", alone)
    log = [e for e in _get("/events") if e["deployment"] == w["id"]]
    kinds = {e["kind"]: e for e in log}
    assert kinds["hijack_alone"]["by"] == "ledger" and kinds["payment_refused"]["code"] == "owner_rejected"
    assert kinds["large_payment_approved"]["outcome"] == "signed by the owner's Ledger"
    chk["security_log"] = [(e["by"], e["kind"], e["code"]) for e in log]

    # 9. done: sweep back automatically
    d = _post(f"/subagents/{w['id']}/done", {"summary": "acceptance"})
    assert d["swept"]["ok"] and Decimal(d["swept"]["returned"]) == Decimal("0.60")

    # 10. export: both payments, who signed, folder; totals reconcile with the main wallet
    ex = _get("/export.json")
    mine = [r for r in ex["rows"] if r["deployment"] == w["id"]]
    assert sorted((r["amount"], r["signed_by"]) for r in mine) == [("0.15", "subagent + cereal"), ("0.25", "subagent + owner's Ledger")]
    assert all(r["folder"] == "Market Research" and r["wallet"] == "Market Sizing" for r in mine)
    assert requests.get(f"{URL}/export.csv", timeout=60).text.startswith("date,folder,wallet")
    assert main_before - rlusd_balance(c, config.address("TREASURY")) == Decimal("0.40")

    ev["finished"] = datetime.now(timezone.utc).isoformat()
    out = config.ROOT / "exports" / f"part5-acceptance-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(exist_ok=True); out.write_text(json.dumps(ev, indent=2, default=str))
    print(f"\nPart 5 acceptance passed; evidence: {out}")
