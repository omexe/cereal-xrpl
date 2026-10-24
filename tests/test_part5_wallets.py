"""Part 5 unit tests: plain-English wallets, Ledger approval above a threshold, sweep when done (no network)."""
from decimal import Decimal

import pytest

from cereal import config, deployments, device, wallet_card

KNOWN = [{"name": "Vendor A", "address": "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay", "credential": {"status": "valid"}},
         {"name": "Vendor B", "address": "rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3", "credential": {"status": "revoked"}},
         {"name": "Vendor C", "address": "r3NdoyQhgKorLo54v2VGkMrMTyPHbTXszs", "credential": {"status": "valid"}}]
SUB = "rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR"


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    from cereal import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(config, "APPROVAL_THRESHOLD", None)
    monkeypatch.setattr(config, "MAX_SUBAGENT_BUDGET", 5.0)


def test_parses_our_sentence_shape():
    c = wallet_card.build_card("Market Sizing: spend up to 1 RLUSD over 2 days, only at Vendor A and Vendor C. "
                               "Ask me above 0.2. Sweep back when done.", KNOWN)
    assert c["ok"] and c["name"] == "Market Sizing" and c["budget"] == "1" and c["expires_in_hours"] == 48
    assert c["allowed_payees"] == [KNOWN[0]["address"], KNOWN[2]["address"]]
    assert c["approval_threshold"] == "0.2" and c["sweep_when_done"]
    assert c["summary"].startswith("Spend up to 1 RLUSD over 2 days, only at Vendor A and Vendor C.")


def test_parses_the_figma_sentence_shape_and_refuses_unknown_vendors_and_the_cap():
    c = wallet_card.build_card("Product X Research: $20 for 2 days, HubSpot, Clearbit and Apollo only, ask me above $5",
                               KNOWN)
    assert c["budget"] == "20" and c["approval_threshold"] == "5" and c["expires_in_hours"] == 48
    assert [v["named"] for v in c["vendors"]] == ["HubSpot", "Clearbit", "Apollo"]
    assert not c["ok"] and any("unknown vendor 'HubSpot'" in p for p in c["problems"])
    assert any("company cap" in p for p in c["problems"])


def test_a_revoked_vendor_makes_the_card_fail():
    c = wallet_card.build_card("spend 0.5 RLUSD today only at Vendor B", KNOWN)
    assert not c["ok"] and "not trusted (revoked)" in c["problems"][0] and c["expires_in_hours"] == 12


def test_defaults_are_stated_not_silent(monkeypatch):
    monkeypatch.setattr(config, "APPROVAL_THRESHOLD", "1")
    c = wallet_card.build_card("spend up to 2 RLUSD", KNOWN)
    assert c["ok"] and c["approval_threshold"] == "1" and c["expires_in_hours"] == 24
    assert len(c["notes"]) == 3  # company threshold, 24 h default, any trusted vendor


@pytest.fixture
def svc(tmp_path, monkeypatch):
    from cereal import service
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)
    monkeypatch.setattr(service, "client", lambda: object())
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: Decimal("1"))
    monkeypatch.setattr(config, "wallet", lambda role: None)
    d = deployments.create("t", "1", [KNOWN[0]["address"]])
    rec = deployments.update(d["id"], status="active", subwallet=SUB, approval_threshold="0.2")
    return service, rec, monkeypatch


def _tx(rec, amount):
    from xrpl.models.transactions import Payment
    from cereal.pay import build_payment
    return build_payment(SUB, KNOWN[0]["address"], amount, rec["id"], rec["tag"]).to_xrpl()


def test_threshold_is_the_lower_of_wallet_and_company(svc):
    service, rec, mp = svc
    assert service._approval_threshold(rec) == Decimal("0.2")
    mp.setattr(config, "APPROVAL_THRESHOLD", "0.1")
    assert service._approval_threshold(rec) == Decimal("0.1")
    assert service._approval_threshold({**rec, "approval_threshold": None}) == Decimal("0.1")


def test_below_the_threshold_cereal_cosigns(svc):
    service, rec, mp = svc
    mp.setattr(service, "cosign_and_submit", lambda *a, **k: {"ok": True, "result": "tesSUCCESS", "hash": "H"})
    mp.setattr(service, "_owner_approves_payment", lambda *a, **k: pytest.fail("not above the threshold"))
    assert service._cosign_deployment(rec, _tx(rec, "0.15"))["result"] == "tesSUCCESS"


def test_above_the_threshold_the_ledger_is_asked_and_cereal_never_signs(svc):
    service, rec, mp = svc
    asked = []
    mp.setattr(service, "cosign_and_submit", lambda *a, **k: pytest.fail("cereal must not co-sign above the threshold"))
    mp.setattr(service, "cosign_combine", lambda *a, **k: pytest.fail("cereal must not co-sign above the threshold"))
    mp.setattr(service, "_owner_approves_payment", lambda rec, tx, amt, thr, present, res: asked.append((amt.value, thr))
               or {"ok": True, "approved_by": "ledger"})
    assert service._cosign_deployment(rec, _tx(rec, "0.25"))["approved_by"] == "ledger"
    assert asked == [("0.25", Decimal("0.2"))]


def test_owner_rejection_sends_nothing(svc):
    service, rec, mp = svc
    mp.setattr(device, "available", lambda: True)
    mp.setattr(device, "sign", lambda tx, decision=None: {"ok": False, "result": "owner_rejected", "screens": ["Amount: 0.25"]})
    mp.setattr(service, "submit_capture", lambda *a, **k: pytest.fail("nothing may be submitted"))
    from xrpl.models.transactions.transaction import Transaction
    tx = Transaction.from_xrpl(_tx(rec, "0.25"))
    r = service._owner_approves_payment(rec, tx, tx.amount, Decimal("0.2"), False, None)
    assert r["refused"] == "owner_rejected" and r["sent_transactions"] == 0 and r["approval"]["screens"] == ["Amount: 0.25"]


def test_done_sweeps_when_the_wallet_says_so(svc):
    service, rec, mp = svc
    swept = []
    mp.setattr(service, "reclaim", lambda dep_id: swept.append(dep_id) or {"ok": True, "returned": "0.6"})
    deployments.update(rec["id"], sweep_when_done=True)
    out = service.done(rec["id"], service.DoneRequest(summary="ok"))
    assert swept == [rec["id"]] and out["swept"]["returned"] == "0.6"


def test_a_card_with_problems_deploys_nothing(svc):
    service, rec, mp = svc
    mp.setattr(wallet_card, "build_card", lambda s: {"ok": False, "problems": ["unknown vendor 'HubSpot'"]})
    mp.setattr(service, "deploy", lambda req: pytest.fail("must not deploy"))
    r = service.wallet_create(service.WalletRequest(sentence="x"))
    assert r["refused"] == "card_problems"
