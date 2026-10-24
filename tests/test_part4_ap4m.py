"""Part 4b unit tests: the AP4M rail's policy in cereal's service (one budget across both rails), without the network."""
from decimal import Decimal

import pytest

from cereal import ap4m, config, deployments

SUB = "rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR"
URL = "http://127.0.0.1:4308/resource"


@pytest.fixture
def svc(tmp_path, monkeypatch):
    from cereal import service
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(service, "client", lambda: object())
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: Decimal("1"))
    monkeypatch.setattr(ap4m, "available", lambda: {"node_modules": True, "env_file": True})
    monkeypatch.setattr(config, "AP4M_ENABLED", True)
    calls = []
    monkeypatch.setattr(ap4m, "pay", lambda *a, **k: calls.append(a) or {
        "ok": True, "rail": "ap4m", "amount": "0.25", "channel_id": "0xch", "redeem_tx": "0xredeem",
        "explorer": "https://explorer.testnet.xrplevm.org/tx/0xredeem", "merchant_payout": "0xpayout",
        "receipt_id": "https://r", "payout_tx": "0xpay"})
    chain = {"redemptions": [{"tx": "0xredeem", "amount": "0.25", "cumulative": "0.25", "payout": "0xpayout"}]}
    monkeypatch.setattr(ap4m, "channel_state", lambda ch, **k: {"ok": True, "channel_id": ch, **chain})
    monkeypatch.setattr(ap4m, "channel_for_job", lambda job: "0xch")
    d = deployments.create("t", "1", [])
    rec = deployments.update(d["id"], status="active", subwallet=SUB)
    service._chain = chain  # tests edit what the chain shows
    return service, rec, calls, monkeypatch


def test_ap4m_payment_is_recorded_with_its_channel_and_receipt(svc):
    service, rec, calls, _ = svc
    r = service.pay_ap4m(rec["id"], service.Ap4mRequest(resource=URL, max_rlusd="0.25"))
    assert r["ok"]
    resource, max_rlusd, cap, job, tag = calls[0]
    assert cap == "1" and job == rec["id"] and tag == rec["tag"], "the Channel's on-chain cap is the subagent's budget"
    p = deployments.get(rec["id"])["payments"][0]
    assert p["rail"] == "ap4m" and p["amount"] == "0.25" and p["hash"] == "0xredeem" and p["channel_id"] == "0xch"


def test_one_budget_across_both_rails(svc):
    service, rec, calls, mp = svc
    # 0.75 already spent over AP4M; the subwallet still holds its full 1 RLUSD on XRPL
    deployments.record_payment(rec["id"], {"rail": "ap4m", "amount": "0.75", "ok": True, "hash": "0xold"})
    r = service.pay_ap4m(rec["id"], service.Ap4mRequest(resource=URL, max_rlusd="0.5"))
    assert r["refused"] == "over_budget" and r["remaining"] == "0.25" and calls == []
    # and the XRPL co-signer sees the same remaining budget
    from cereal.ledger import rlusd
    from xrpl.models.transactions import Payment
    tx = Payment(account=SUB, destination="rGrhEwizViewpp8b91RTdUV2MpdWUdaEay", amount=rlusd("0.5")).to_xrpl()
    mp.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)
    assert service._cosign_deployment(deployments.get(rec["id"]), tx)["refused"] == "over_budget"


def test_inactive_or_unavailable_rail_is_refused_before_paying(svc):
    service, rec, calls, mp = svc
    mp.setattr(ap4m, "available", lambda: {"node_modules": True, "env_file": False})
    assert service.pay_ap4m(rec["id"], service.Ap4mRequest(resource=URL))["refused"] == "ap4m_unavailable"
    deployments.update(rec["id"], status="reclaimed")
    assert service.pay_ap4m(rec["id"], service.Ap4mRequest(resource=URL))["refused"] == "unknown_or_inactive_deployment"
    assert calls == []


def test_a_refusal_from_the_rail_is_recorded_not_counted(svc):
    service, rec, calls, mp = svc
    service._chain["redemptions"] = []  # nothing redeemed on-chain
    mp.setattr(ap4m, "pay", lambda *a, **k: {"ok": False, "rail": "ap4m", "refused": "over_cap"})
    r = service.pay_ap4m(rec["id"], service.Ap4mRequest(resource=URL))
    assert r["refused"] == "over_cap"
    d = deployments.get(rec["id"])
    assert d["payments"] == [] and d["refusals"][-1]["refused"] == "over_cap"
    assert service.ap4m_spent(d) == 0


def test_ap4m_pay_parses_the_last_json_line(monkeypatch):
    class P:
        stdout = 'noise\n{"ok": true, "rail": "ap4m", "amount": "0.25"}\n'
        stderr = ""
    monkeypatch.setattr(ap4m.subprocess, "run", lambda *a, **k: P())
    assert ap4m.pay(URL, "0.25", "1", "d_x", "t")["amount"] == "0.25"


def test_a_crash_after_redemption_is_still_recorded_from_the_chain(svc):
    """Seen live Oct 24: the voucher was redeemed (0x911de0c0…) but pay.mjs failed afterwards. The ledger decides."""
    service, rec, calls, mp = svc
    mp.setattr(ap4m, "pay", lambda *a, **k: {"ok": False, "rail": "ap4m", "refused": "ap4m_error"})
    r = service.pay_ap4m(rec["id"], service.Ap4mRequest(resource=URL))
    assert r["recorded"] and r["recorded"][0]["hash"] == "0xredeem" and r["recorded"][0]["source"] == "chain"
    d = deployments.get(rec["id"])
    assert service.ap4m_spent(d) == Decimal("0.25") and not d.get("refusals")


def test_reconcile_is_idempotent(svc):
    service, rec, calls, _ = svc
    assert len(service.ap4m_reconcile(rec["id"])["added"]) == 1
    assert service.ap4m_reconcile(rec["id"])["added"] == []
    assert service.ap4m_spent(deployments.get(rec["id"])) == Decimal("0.25")


def test_reclaim_records_then_closes_the_ap4m_channel(svc):
    service, rec, calls, mp = svc
    order = []
    mp.setattr(service, "reconcile_ap4m", lambda dep_id, *a, **k: order.append("reconcile") or [])
    mp.setattr(ap4m, "close", lambda ch, **k: order.append(("close", ch)) or {"ok": True, "tx_hash": "0xclose"})
    mp.setattr(ap4m, "forget_job", lambda job: order.append(("forget", job)))
    out = service.close_ap4m_channel(rec["id"])
    assert order == ["reconcile", ("close", "0xch"), ("forget", rec["id"])], "record from the chain before closing"
    assert out["ok"] and deployments.get(rec["id"])["hashes"]["ap4m_close"] == "0xclose"


def test_reclaim_without_ap4m_closes_nothing(svc):
    service, rec, calls, mp = svc
    mp.setattr(ap4m, "channel_for_job", lambda job: None)
    mp.setattr(ap4m, "close", lambda ch, **k: pytest.fail("no Channel to close"))
    assert service.close_ap4m_channel(rec["id"]) is None


def test_the_sidelined_rail_refuses_and_pays_nothing(svc):
    service, rec, calls, mp = svc
    mp.setattr(config, "AP4M_ENABLED", False)
    assert service.pay_ap4m(rec["id"], service.Ap4mRequest(resource=URL))["refused"] == "ap4m_disabled"
    assert calls == []
