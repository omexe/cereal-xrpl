"""Part 3 unit tests: the owner's Ledger in the deploy path and in recovery, without the network or the device."""
from decimal import Decimal

import pytest
from xrpl.models.transactions import Payment, SignerListSet, TrustSet
from xrpl.wallet import Wallet

from cereal import config, deployments, device, keystore, subwallets

MAIN = "rGP3CdfnKSSz4BYPNTjKiNGzM98xDxbEfj"
DEV = "rn1FZHRNBPX8g2Y5Xzhx1LonhmSheFYMAq"
SUBAGENT = "rDm4QaxZY47F9dKf9tN43Dz73NPXMbZw9R"


@pytest.fixture
def svc(tmp_path, monkeypatch):
    """The service with the ledger reads faked and every transaction path recorded."""
    from cereal import service
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(config, "DEVICE_FUNDING", True)
    monkeypatch.setattr(config, "DEVICE_DECISION", "approve")
    monkeypatch.setattr(config, "LEDGER_ADDRESS", DEV)
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", True)
    monkeypatch.setattr(config, "MAX_SUBAGENT_BUDGET", 5.0)
    monkeypatch.setattr(config, "MAX_OUTSTANDING_BUDGET", 10.0)
    monkeypatch.setattr(config, "MAX_ACTIVE_SUBAGENTS", 5)
    monkeypatch.setattr(config, "address", lambda role: MAIN if role == "TREASURY" else "rCOSIGN")
    calls = {"create": [], "submit": [], "sign": [], "software_fund": []}
    monkeypatch.setattr(service, "client", lambda: object())
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: Decimal("100"))
    monkeypatch.setattr(service, "account_info", lambda c, a: {"Balance": str(200 * 10**6), "Sequence": 500})
    monkeypatch.setattr(service, "prepare", lambda tx, c, **kw: tx)
    monkeypatch.setattr(subwallets, "activation_xrp", lambda c: Decimal("1.9"))
    monkeypatch.setattr(keystore, "new_subagent_key", lambda dep_id: SUBAGENT)

    def fake_create(dep_id, tag, budget, sub_key, c, main=None, sub=None):
        calls["create"].append(sub.classic_address)
        return {"ok": True, "address": sub.classic_address, "hashes": {"activate": "ACT", "lock": ["L1", "L2", "L3"]}}
    monkeypatch.setattr(subwallets, "create", fake_create)
    monkeypatch.setattr(device, "submit_signed", lambda signed, c, **kw: calls["submit"].append(signed) or
                        {"ok": True, "hash": "FUND", "signed_on": "ledger"})
    monkeypatch.setattr(service, "fund_burner", lambda *a, **k: calls["software_fund"].append(a) or {"ok": True})
    return service, calls, monkeypatch


def _sign_as(decision_result, calls):
    def fake_sign(tx, decision=None):
        calls["sign"].append((tx, decision))
        screens = ["Transaction Type: Payment", f"Destination: {tx.destination}", "Amount: 1", "Currency: RLUSD"]
        if decision_result == "approve":
            return {"ok": True, "address": DEV, "screens": screens, "signedBlob": "00"}
        return {"ok": False, "result": "owner_rejected", "screens": screens}
    return fake_sign


def test_device_unavailable_refuses_before_any_transaction(svc):
    service, calls, mp = svc
    mp.setattr(device, "available", lambda: False)
    r = service.deploy(service.DeployRequest(task="t", budget="1"))
    assert r["refused"] == "device_unavailable"
    assert calls == {"create": [], "submit": [], "sign": [], "software_fund": []}
    assert deployments.all_() == []


def test_owner_rejects_on_device_and_nothing_touches_the_ledger(svc):
    service, calls, mp = svc
    mp.setattr(device, "available", lambda: True)
    mp.setattr(device, "sign", _sign_as("reject", calls))
    r = service.deploy(service.DeployRequest(task="t", budget="1", speculos_decision="reject"))
    assert r["refused"] == "owner_rejected" and r["sent_transactions"] == 0
    assert "Amount: 1" in r["screens"]
    assert calls["create"] == [] and calls["submit"] == [] and calls["software_fund"] == []
    assert calls["sign"][0][1] == "reject"
    rec = deployments.get(r["deployment"])
    assert rec["status"] == "rejected" and rec["approval"]["result"] == "owner_rejected"


def test_owner_approves_first_then_the_presigned_funding_is_submitted(svc):
    service, calls, mp = svc
    mp.setattr(device, "available", lambda: True)
    mp.setattr(device, "sign", _sign_as("approve", calls))
    r = service.deploy(service.DeployRequest(task="t", budget="1"))
    assert r["ok"] and r["status"] == "active"
    tx, _ = calls["sign"][0]
    assert isinstance(tx, Payment) and tx.account == MAIN and tx.amount.value == "1"
    assert tx.sequence == 501, "activation takes the main wallet's next Sequence; funding the one after"
    assert calls["create"] == [tx.destination], "the device approved exactly the subwallet that was then created"
    assert len(calls["submit"]) == 1 and calls["software_fund"] == []
    assert r["approval"]["by"] == DEV and r["approval"]["result"] == "approved"
    assert f"Destination: {tx.destination}" in r["approval"]["screens"]
    assert r["hashes"]["fund"] == "FUND"


def test_manual_mode_ignores_api_button_choice(svc):
    service, calls, mp = svc
    mp.setattr(config, "DEVICE_DECISION", "manual")
    mp.setattr(device, "available", lambda: True)
    mp.setattr(device, "sign", _sign_as("approve", calls))
    service.deploy(service.DeployRequest(task="t", budget="1", speculos_decision="approve"))
    assert calls["sign"][0][1] is None, "with a human at the device, the API cannot press buttons"


def test_software_funding_when_device_funding_is_off(svc):
    service, calls, mp = svc
    mp.setattr(config, "DEVICE_FUNDING", False)
    # Funding is mocked by svc; this unit test must not load a real treasury seed.
    treasury = object()
    mp.setattr(config, "wallet", lambda role: treasury if role == "TREASURY" else pytest.fail("unexpected wallet role"))
    r = service.deploy(service.DeployRequest(task="t", budget="1"))
    assert r["ok"] and calls["sign"] == [] and len(calls["software_fund"]) == 1 and "approval" not in r
    assert calls["software_fund"][0][0] is treasury


def test_recovery_signer_has_weight_to_meet_quorum_alone():
    from cereal.lock import lock_transactions
    txs = lock_transactions("rSUB", SUBAGENT, "rCOSIGN", "1", recovery_addr=DEV)
    sls = next(t for t in txs if isinstance(t, SignerListSet))
    weights = {e.account: e.signer_weight for e in sls.signer_entries}
    assert weights == {SUBAGENT: 1, "rCOSIGN": 1, DEV: 2} and sls.signer_quorum == 2
    assert weights[DEV] >= sls.signer_quorum > max(weights[SUBAGENT], weights["rCOSIGN"])


def test_screens_summary_rejoins_wrapped_values_and_drops_noise():
    raw = ["XRP | app is ready", "Destination | raNMoqu6qUG69dbf | 3oKfVcSDiyQvvUWko | J", "Amount | 1",
           "Amount | 1", "Sign transaction?", "Reject transaction", "Transaction signed"]
    assert device.screens_summary(raw) == ["Destination: raNMoqu6qUG69dbf3oKfVcSDiyQvvUWkoJ", "Amount: 1",
                                           "Sign transaction?"]


class _Lines:
    def __init__(self, lines):
        self.lines = lines

    def request(self, req):
        return type("R", (), {"result": {"lines": self.lines}})()


def test_recover_sweeps_everything_then_closes_the_line_on_the_device(monkeypatch):
    from cereal import recover
    from cereal.burn import TF_SET_NO_RIPPLE
    signed = []
    monkeypatch.setattr(recover, "rlusd_balance", lambda c, a: Decimal("0.75"))
    monkeypatch.setattr(device, "sign_submit", lambda tx, c, **kw: signed.append(tx) or {"ok": True, "hash": "H"})
    steps = recover.recover("rSUB", _Lines([{"currency": "RLUSD"}]), to=MAIN)
    assert [n for n, _ in steps] == ["sweep", "close_line"]
    pay, ts = signed
    assert isinstance(pay, Payment) and pay.account == "rSUB" and pay.destination == MAIN and pay.amount.value == "0.75"
    assert isinstance(ts, TrustSet) and ts.limit_amount.value == "0" and ts.flags & TF_SET_NO_RIPPLE


def test_recover_stops_if_the_sweep_fails(monkeypatch):
    from cereal import recover
    signed = []
    monkeypatch.setattr(recover, "rlusd_balance", lambda c, a: Decimal("0.75"))
    monkeypatch.setattr(device, "sign_submit", lambda tx, c, **kw: signed.append(tx) or
                        {"ok": False, "result": "owner_rejected", "hash": None})
    steps = recover.recover("rSUB", _Lines([{"currency": "RLUSD"}]), to=MAIN)
    assert [n for n, _ in steps] == ["sweep"] and len(signed) == 1


def test_a_device_error_is_retried_once_but_an_owner_rejection_never(monkeypatch):
    seq = [{"ok": False, "result": "device_error"}, {"ok": True, "address": DEV}]
    monkeypatch.setattr(device, "_sign_once", lambda tx, d, t: seq.pop(0))
    monkeypatch.setattr(device, "reset", lambda: True)
    out = device.sign(object(), "approve")
    assert out["ok"] and out["retried_after_device_error"]
    calls = []
    monkeypatch.setattr(device, "_sign_once", lambda tx, d, t: calls.append(1) or {"ok": False, "result": "owner_rejected"})
    assert device.sign(object(), "reject")["result"] == "owner_rejected" and calls == [1], "a no from the owner is final"
