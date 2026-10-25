"""R07 + R03 (no network): creation is bound to the card the owner reviewed, and POST /wallets is idempotent."""
import threading

import pytest

from cereal import config, deployments, directory, wallet_card

KNOWN = [{"name": "Vendor A", "address": "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay", "credential": {"status": "valid"}},
         {"name": "Vendor B", "address": "rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3", "credential": {"status": "revoked"}},
         {"name": "Vendor C", "address": "r3NdoyQhgKorLo54v2VGkMrMTyPHbTXszs", "credential": {"status": "valid"}}]
SENTENCE = "Create test: spend up to 0.5 RLUSD today, only at Vendor A and Vendor C. Ask me above 0.2. Sweep back when done."


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    from cereal import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(config, "APPROVAL_THRESHOLD", None)
    monkeypatch.setattr(config, "MAX_SUBAGENT_BUDGET", 5.0)
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(directory, "list_vendors", lambda c=None: [dict(v, credential=dict(v["credential"])) for v in KNOWN])
    wallet_card.in_progress.clear()
    wallet_card._readings.clear()


@pytest.fixture
def svc(monkeypatch):
    """The service with deploy() replaced: it records a deployment like the real one and counts every call."""
    from cereal import service
    calls = []

    def fake_deploy(req):
        calls.append(req)
        rec = deployments.create(req.task, req.budget, req.allowed_payees, req.expires_in_hours)
        rec = deployments.update(rec["id"], sentence=req.sentence, folder=req.folder, name=req.name,
                                 status="active", subwallet="rSUB", hashes={"fund": "F" * 64})
        return {"ok": True, **rec, "balance": req.budget}

    monkeypatch.setattr(service, "deploy", fake_deploy)
    monkeypatch.setattr(service, "_with_balance", lambda rec: {**rec, "balance": rec["budget"]})
    return service, calls, monkeypatch


# ---- R07: the digest ----

def test_the_digest_is_stable_and_ignores_order_and_wording():
    a = wallet_card.build_card(SENTENCE, KNOWN)
    b = wallet_card.build_card(SENTENCE, KNOWN)
    assert a["ok"] and len(a["digest"]) == 64 and a["digest"] == b["digest"]
    swapped = wallet_card.build_card(SENTENCE.replace("Vendor A and Vendor C", "Vendor C and Vendor A"), KNOWN)
    assert swapped["digest"] == a["digest"]  # same allowlist, other order
    assert wallet_card.card_digest({**a, "budget": "0.50", "notes": ["x"], "parsed_by": "claude", "summary": "y"}) == a["digest"]


@pytest.mark.parametrize("change", [
    {"budget": "0.6"}, {"name": "Other"}, {"expires_in_hours": 24.0}, {"approval_threshold": "0.3"},
    {"approval_threshold": None}, {"sweep_when_done": False}, {"allowed_payees": [KNOWN[0]["address"]]},
])
def test_every_enforced_field_changes_the_digest(change):
    card = wallet_card.build_card(SENTENCE, KNOWN)
    assert wallet_card.card_digest({**card, **change}) != card["digest"]


def test_a_vendor_credential_change_changes_the_digest():
    before = wallet_card.build_card(SENTENCE, KNOWN)
    revoked = [dict(v, credential={"status": "revoked"}) if v["name"] == "Vendor C" else v for v in KNOWN]
    after = wallet_card.build_card(SENTENCE, revoked)
    assert not after["ok"] and after["digest"] != before["digest"]


# ---- R07: creation is bound to the reviewed card ----

def test_a_matching_digest_creates_the_wallet(svc):
    service, calls, _ = svc
    card = service.wallet_preview(service.WalletRequest(sentence=SENTENCE))
    out = service.wallet_create(service.WalletRequest(sentence=SENTENCE, card_digest=card["digest"]))
    assert out["ok"] and len(calls) == 1 and out["card"]["digest"] == card["digest"]
    assert deployments.get(out["id"])["card_digest"] == card["digest"]


def test_a_changed_card_is_refused_and_nothing_is_sent(svc):
    service, calls, mp = svc
    reviewed = service.wallet_preview(service.WalletRequest(sentence=SENTENCE))
    # Vendor C's credential was revoked between the review and the click
    mp.setattr(directory, "list_vendors", lambda c=None: [dict(v, credential={"status": "revoked"}) if v["name"] == "Vendor C"
                                                          else v for v in KNOWN])
    out = service.wallet_create(service.WalletRequest(sentence=SENTENCE, card_digest=reviewed["digest"]))
    assert out["refused"] == "card_changed" and out["sent_transactions"] == 0 and calls == []
    assert out["card"]["digest"] != reviewed["digest"] and not out["card"]["ok"]
    assert any("Vendor C is not trusted (revoked)" in p for p in out["card"]["problems"])
    assert deployments.all_() == []


def test_the_reviewed_reading_is_deployed_not_a_second_model_reading(svc):
    service, calls, mp = svc
    reviewed = service.wallet_preview(service.WalletRequest(sentence=SENTENCE))
    real = wallet_card.parse_fallback
    mp.setattr(wallet_card, "parse_fallback", lambda s: {**real(s), "budget": "5"})  # a model reading it otherwise now
    out = service.wallet_create(service.WalletRequest(sentence=SENTENCE, card_digest=reviewed["digest"]))
    assert out["ok"] and calls[0].budget == "0.5" and out["card"]["digest"] == reviewed["digest"]


def test_a_different_parser_reading_is_refused_when_the_reviewed_one_is_gone(svc):
    service, calls, mp = svc
    reviewed = service.wallet_preview(service.WalletRequest(sentence=SENTENCE))
    wallet_card._readings.clear()  # the service restarted between the review and the click
    real = wallet_card.parse_fallback
    mp.setattr(wallet_card, "parse_fallback", lambda s: {**real(s), "budget": "5"})
    out = service.wallet_create(service.WalletRequest(sentence=SENTENCE, card_digest=reviewed["digest"]))
    assert out["refused"] == "card_changed" and out["card"]["budget"] == "5" and calls == []
    # confirming the new card deploys exactly that card, even if the parser would now read it differently again
    mp.setattr(wallet_card, "parse_fallback", lambda s: {**real(s), "budget": "4"})
    again = service.wallet_create(service.WalletRequest(sentence=SENTENCE, card_digest=out["card"]["digest"]))
    assert again["ok"] and calls[0].budget == "5"


def test_without_a_digest_creation_behaves_as_before(svc):
    service, calls, _ = svc
    out = service.wallet_create(service.WalletRequest(sentence=SENTENCE, folder="Market Research"))
    assert out["ok"] and len(calls) == 1 and calls[0].budget == "0.5" and calls[0].folder == "Market Research"
    bad = service.wallet_create(service.WalletRequest(sentence="spend 0.5 RLUSD today only at Vendor B"))
    assert bad["refused"] == "card_problems" and len(calls) == 1


# ---- R03: idempotent POST /wallets ----

def test_a_repeated_request_returns_the_original_wallet(svc):
    service, calls, _ = svc
    req = service.WalletRequest(sentence=SENTENCE, request_id="req-1")
    first = service.wallet_create(req)
    again = service.wallet_create(req)
    assert first["ok"] and again["ok"] and again["id"] == first["id"] and again["replayed"] is True
    assert "replayed" not in first and len(calls) == 1 and len(deployments.all_()) == 1
    assert deployments.get(first["id"])["request_id"] == "req-1"
    assert again["card"]["digest"] == first["card"]["digest"]
    other = service.wallet_create(service.WalletRequest(sentence=SENTENCE, request_id="req-2"))
    assert other["id"] != first["id"] and len(calls) == 2  # a new request is a new wallet


def test_a_refusal_that_left_a_record_is_replayed_not_redeployed(svc):
    service, calls, mp = svc

    def rejected(req):
        calls.append(req)
        rec = deployments.create(req.task, req.budget, req.allowed_payees, req.expires_in_hours)
        deployments.update(rec["id"], sentence=req.sentence, status="rejected")
        return service._refuse("owner_rejected", deployment=rec["id"], screens=["Amount 0.5"], sent_transactions=0)

    mp.setattr(service, "deploy", rejected)
    req = service.WalletRequest(sentence=SENTENCE, request_id="req-r", speculos_decision="reject")
    first = service.wallet_create(req)
    again = service.wallet_create(req)
    assert first["refused"] == again["refused"] == "owner_rejected"
    assert again["deployment"] == first["deployment"] and again["replayed"] is True and len(calls) == 1
    rec = deployments.get(first["deployment"])
    assert rec["request_id"] == "req-r" and rec["status"] == "rejected" and rec["create_refusal"]["refused"] == "owner_rejected"


def test_a_refusal_before_any_record_is_evaluated_again(svc):
    service, calls, mp = svc
    answers = [service._refuse("device_unavailable", speculos="http://127.0.0.1:5000")]
    real = service.deploy
    mp.setattr(service, "deploy", lambda req: answers.pop(0) if answers else real(req))
    req = service.WalletRequest(sentence=SENTENCE, request_id="req-d")
    assert service.wallet_create(req)["refused"] == "device_unavailable"
    assert not wallet_card.in_progress  # released: the retry is not refused in_progress
    out = service.wallet_create(req)
    assert out["ok"] and len(calls) == 1


def test_a_concurrent_twin_is_refused_in_progress(svc):
    service, calls, mp = svc
    entered, release = threading.Event(), threading.Event()
    real = service.deploy

    def slow(req):
        entered.set()
        assert release.wait(5)
        return real(req)

    mp.setattr(service, "deploy", slow)
    req = service.WalletRequest(sentence=SENTENCE, request_id="req-c")
    results = {}
    t = threading.Thread(target=lambda: results.setdefault("first", service.wallet_create(req)))
    t.start()
    assert entered.wait(5)
    twin = service.wallet_create(req)
    release.set(); t.join(5)
    assert twin["refused"] == "in_progress" and twin["request_id"] == "req-c"
    assert results["first"]["ok"] and len(calls) == 1 and len(deployments.all_()) == 1
    assert service.wallet_create(req)["replayed"] is True and not wallet_card.in_progress


@pytest.mark.parametrize("other", [{"sentence": SENTENCE.replace("0.5", "0.4")}, {"folder": "Elsewhere"},
                                   {"card_digest": "0" * 64}])
def test_a_request_id_reused_for_another_request_is_refused(svc, other):
    service, calls, _ = svc
    service.wallet_create(service.WalletRequest(sentence=SENTENCE, request_id="req-x"))
    out = service.wallet_create(service.WalletRequest(**{"sentence": SENTENCE, "request_id": "req-x", **other}))
    assert out["refused"] == "request_id_reused" and len(calls) == 1


def test_a_deploy_that_raises_after_its_record_exists_is_never_deployed_again(svc):
    service, calls, mp = svc

    def crashes(req):
        calls.append(req)
        rec = deployments.create(req.task, req.budget, req.allowed_payees, req.expires_in_hours)
        deployments.update(rec["id"], sentence=req.sentence)
        raise TimeoutError("speculos did not answer")

    mp.setattr(service, "deploy", crashes)
    req = service.WalletRequest(sentence=SENTENCE, request_id="req-t")
    first = service.wallet_create(req)
    assert first["refused"] == "deploy_interrupted" and first["status"] == "deploying"
    assert "TimeoutError" in first["error"] and not wallet_card.in_progress
    again = service.wallet_create(req)
    assert again["refused"] == "deploy_interrupted" and again["replayed"] is True
    assert again["deployment"] == first["deployment"] and len(calls) == 1


def test_a_deploy_that_raises_before_any_record_is_not_masked(svc):
    service, calls, mp = svc
    mp.setattr(service, "deploy", lambda req: (_ for _ in ()).throw(ConnectionError("rpc down")))
    with pytest.raises(ConnectionError):
        service.wallet_create(service.WalletRequest(sentence=SENTENCE, request_id="req-e"))
    assert not wallet_card.in_progress and deployments.all_() == []
