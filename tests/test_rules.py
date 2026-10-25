"""A03 unit tests: editing an existing wallet's spending rules (no network)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from cereal import config, deployments, directory, rules, rule_intent
import json


def answer(**changes):
    return dict(spend=None, expires_in_hours=None, approval_threshold=None,
                clear_approval_threshold=False, sweep_when_done=None, merchants=[], problems=[],
                needs_add_funds=False) | changes


A = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"
B = "rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3"
C = "r3NdoyQhgKorLo54v2VGkMrMTyPHbTXszs"
SUB = "rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR"
TREASURY = "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh"
KNOWN = [{"name": "Vendor A", "address": A, "credential": {"status": "valid"}},
         {"name": "Vendor B", "address": B, "credential": {"status": "revoked"}},
         {"name": "Vendor C", "address": C, "credential": {"status": "valid"}}]
STATUS = {A: {"status": "valid"}, C: {"status": "valid"},
          B: {"status": "revoked", "revocation": {"reason": "overcharge", "hash": "REV"}}}


# ---- the plan and apply, against a fake ledger ---------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    from cereal import service
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(config, "APPROVAL_THRESHOLD", None)
    monkeypatch.setattr(config, "address", lambda role: {"TREASURY": TREASURY}[role])
    monkeypatch.setattr(config, "wallet", lambda role: f"wallet:{role}")
    monkeypatch.setattr(rules.keystore, "load", lambda dep_id: f"subagent:{dep_id}")
    monkeypatch.setattr(service, "client", lambda: object())
    answers = {
        "Ask me above 0.1. Remove Vendor C. Keep funds when done.": answer(
            approval_threshold="0.1", sweep_when_done=False,
            merchants=[{"operation": "remove", "names": ["Vendor C"]}]),
        "only at Vendor Z": answer(merchants=[{"operation": "only", "names": ["Vendor Z"]}]),
        "also allow Vendor C": answer(merchants=[{"operation": "add", "names": ["Vendor C"]}]),
    }
    monkeypatch.setattr(rule_intent.llm, "extract", lambda system, user, *args: answers[json.loads(user)["request"]])
    ledger = {"balance": Decimal("0.6"), "sent": []}
    monkeypatch.setattr(rules, "rlusd_balance", lambda c, a: ledger["balance"])
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: ledger["balance"])
    monkeypatch.setattr(rules.vendors, "check", lambda c, addr, vendor_class="data": STATUS.get(addr, {"status": "none"}))
    monkeypatch.setattr(directory, "list_vendors", lambda c=None: KNOWN)

    def submit(tx, signers, c, **kw):
        ledger["sent"].append((tx, signers))
        if ledger.get("fail"):
            return {"ok": False, "result": ledger["fail"], "hash": None, "explorer": None, "validated": False}
        ledger["balance"] -= Decimal(tx.amount.value)
        return {"ok": True, "result": "tesSUCCESS", "hash": "RETURNHASH", "validated": True}
    monkeypatch.setattr(rules, "multisign_submit", submit)
    d = deployments.create("Rules test", "0.6", [A, C], 12)
    rec = deployments.update(d["id"], status="active", subwallet=SUB, approval_threshold="0.2", sweep_when_done=True,
                             name="Rules test")
    return rec, ledger


def test_preview_lists_changes_and_sends_nothing(env):
    rec, ledger = env
    p = rules.preview(rec["id"], {"approval_threshold": "0.1", "merchants": [A]})
    assert p["ok"] and p["problems"] == []
    assert p["changes"] == ["Approval threshold 0.2 → 0.1 RLUSD", "Merchants Vendor A and Vendor C → Vendor A"]
    assert p["rules"]["allowed_payees"] == [A] and p["rules"]["approval_threshold"] == "0.1"
    assert "updates" not in p and ledger["sent"] == []
    assert deployments.get(rec["id"])["approval_threshold"] == "0.2"  # nothing persisted


def test_apply_persists_and_records_history(env):
    rec, ledger = env
    out = rules.apply(rec["id"], {"sentence": "Ask me above 0.1. Remove Vendor C. Keep funds when done."})
    assert out["ok"] and ledger["sent"] == []
    after = deployments.get(rec["id"])
    assert after["approval_threshold"] == "0.1" and after["allowed_payees"] == [A] and after["sweep_when_done"] is False
    assert after["budget"] == "0.6" and len(after["rules_history"]) == 1
    assert after["rules_history"][0]["changes"] == out["changes"] and len(out["changes"]) == 3
    assert out["wallet"]["approval_threshold"] == "0.1" and out["wallet"]["balance"] == "0.6"


def test_merchants_need_a_valid_credential(env):
    rec, _ = env
    p = rules.preview(rec["id"], {"merchants": [A, B]})
    assert not p["ok"] and "Vendor B is not trusted (revoked: overcharge)" in p["problems"][0]
    p = rules.preview(rec["id"], {"sentence": "only at Vendor Z"})
    assert not p["ok"] and p["problems"] == ["unknown vendor “Vendor Z”: not in cereal's directory"]
    p = rules.preview(rec["id"], {"merchants": []})
    assert not p["ok"] and "empty merchant list" in p["problems"][0]
    assert rules.apply(rec["id"], {"merchants": [A, B]})["refused"] == "rules_problems"
    assert deployments.get(rec["id"])["allowed_payees"] == [A, C]


def test_swapping_among_credentialed_vendors_is_allowed(env):
    rec, _ = env
    deployments.update(rec["id"], allowed_payees=[A])
    out = rules.apply(rec["id"], {"merchants": [C]})
    assert out["ok"] and deployments.get(rec["id"])["allowed_payees"] == [C]


def test_lowering_the_limit_returns_the_excess_on_ledger(env):
    rec, ledger = env
    p = rules.preview(rec["id"], {"spend": "0.4"})
    assert p["ok"] and p["returns"] == "0.2" and ledger["sent"] == []
    assert p["changes"] == ["Spend limit 0.6 → 0.4 RLUSD; 0.2 RLUSD returns to the main wallet now"]
    out = rules.apply(rec["id"], {"spend": "0.4"})
    assert out["ok"] and out["returned"] == "0.2" and out["hashes"] == {"return": "RETURNHASH"}
    assert out["explorer"].endswith("/transactions/RETURNHASH")
    [(tx, signers)] = ledger["sent"]
    assert tx.account == SUB and tx.destination == TREASURY and tx.amount.value == "0.2"
    assert tx.amount.currency == config.RLUSD_CURRENCY and tx.source_tag == config.SOURCE_TAG
    from cereal.ledger import decode_memos
    assert decode_memos(tx.to_xrpl())[0] == {"tag": rec["tag"], "job": rec["id"], "kind": "return"}
    assert signers == [f"subagent:{rec['id']}", "wallet:CEREAL_COSIGN"]
    after = deployments.get(rec["id"])
    assert after["budget"] == "0.4" and after["hashes"]["returns"] == ["RETURNHASH"]
    assert after["rules_history"][0]["returned"] == "0.2" and out["rules"]["balance"] == "0.4"


def test_lowering_keeps_what_was_spent_and_pending(env):
    rec, ledger = env
    deployments.record_payment(rec["id"], {"to": A, "amount": "0.25", "ok": True, "result": "tesSUCCESS", "hash": "P1"})
    deployments.record_payment(rec["id"], {"to": C, "amount": "0.15", "ok": None, "result": "co-signed", "hash": None})
    ledger["balance"] = Decimal("0.35")  # 0.6 - 0.25 validated; the pending 0.15 has not left yet
    p = rules.preview(rec["id"], {"spend": "0.3"})
    assert not p["ok"] and "below what this wallet already spent or committed" in p["problems"][0]
    p = rules.preview(rec["id"], {"spend": "0.5"})
    assert p["ok"] and p["returns"] == "0.1"  # keeps 0.5 - 0.25 = 0.25, enough for the pending 0.15
    assert any("are not recalled" in n for n in p["notes"])


def test_raising_the_limit_is_refused(env):
    rec, ledger = env
    p = rules.preview(rec["id"], {"spend": "2"})
    assert not p["ok"] and p["problems"][0].startswith("Only Add funds can raise a wallet's budget")
    out = rules.apply(rec["id"], {"spend": "2"})
    assert out["refused"] == "use_add_funds" and out["sent_transactions"] == 0
    assert ledger["sent"] == [] and deployments.get(rec["id"])["budget"] == "0.6"


def test_a_failed_return_changes_nothing(env):
    rec, ledger = env
    ledger["fail"] = "tecPATH_PARTIAL"
    out = rules.apply(rec["id"], {"spend": "0.4", "approval_threshold": "0.1"})
    assert out["refused"] == "return_failed" and out["result"] == "tecPATH_PARTIAL"
    after = deployments.get(rec["id"])
    assert after["budget"] == "0.6" and after["approval_threshold"] == "0.2" and not after.get("rules_history")


def test_an_unknown_return_outcome_claims_nothing(env, monkeypatch):
    rec, _ = env

    def dropped(*a, **k):
        raise ConnectionError("node went away")
    monkeypatch.setattr(rules, "multisign_submit", dropped)
    out = rules.apply(rec["id"], {"spend": "0.4"})
    assert out["refused"] == "return_unknown" and "nothing is returned twice" in out["problems"][0]
    assert deployments.get(rec["id"])["budget"] == "0.6"


def test_only_active_wallets_can_be_edited(env):
    rec, ledger = env
    deployments.update(rec["id"], status="reclaimed")
    assert rules.preview(rec["id"], {"approval_threshold": "0.1"})["refused"] == "not_active"
    assert rules.apply(rec["id"], {"spend": "0.1"})["refused"] == "not_active"
    assert ledger["sent"] == [] and deployments.get(rec["id"])["approval_threshold"] == "0.2"


def test_expiry_and_threshold_limits(env):
    rec, _ = env
    assert "longer than 7 days" in rules.preview(rec["id"], {"expires_in_hours": 169})["problems"][0]
    assert "in the future" in rules.preview(rec["id"], {"expires_in_hours": 0})["problems"][0]
    assert "0 or more" in rules.preview(rec["id"], {"approval_threshold": "-1"})["problems"][0]
    out = rules.apply(rec["id"], {"expires_in_hours": 48, "approval_threshold": None})
    assert out["ok"] and out["changes"][0] == "Approval threshold 0.2 RLUSD → none"
    exp = datetime.fromisoformat(deployments.get(rec["id"])["expires_at"])
    assert abs(exp - (datetime.now(timezone.utc) + timedelta(hours=48))) < timedelta(minutes=1)
    assert deployments.get(rec["id"])["approval_threshold"] is None


def test_no_change_and_mixed_input_are_problems(env):
    rec, _ = env
    assert "nothing to change" in rules.preview(rec["id"], {"approval_threshold": "0.20"})["problems"][0]
    assert "not both" in rules.preview(rec["id"], {"sentence": "ask me above 0.1", "spend": "0.4"})["problems"][0]


def test_routes_reject_unknown_fields_and_wallets(env):
    from fastapi.testclient import TestClient
    from cereal import service
    rec, _ = env
    http = TestClient(service.app)
    assert http.post(f"/subagents/{rec['id']}/rules/preview", json={"budget": "0.4"}).status_code == 422
    assert http.post("/subagents/d_nope/rules", json={"spend": "0.4"}).status_code == 404
    r = http.post(f"/subagents/{rec['id']}/rules/preview", json={"approval_threshold": 0.1}).json()
    assert r["ok"] and r["changes"] == ["Approval threshold 0.2 → 0.1 RLUSD"]
    r = http.post(f"/subagents/{rec['id']}/rules", json={"approval_threshold": None}).json()
    assert r["ok"] and deployments.get(rec["id"])["approval_threshold"] is None


def test_add_never_narrows_any_credentialed_vendor(env):
    rec, _ = env
    deployments.update(rec["id"], allowed_payees=[])
    p = rules.preview(rec["id"], {"sentence": "also allow Vendor C"})
    assert not p["ok"] and "already pays any credentialed vendor" in p["problems"][0]
    deployments.update(rec["id"], allowed_payees=[A])
    p = rules.preview(rec["id"], {"sentence": "also allow Vendor C"})
    assert p["ok"] and p["rules"]["allowed_payees"] == [A, C]


def test_with_credentials_off_the_list_is_the_whole_policy(env, monkeypatch):
    rec, _ = env
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)
    monkeypatch.setattr(rules.vendors, "check", lambda *a, **k: pytest.fail("the co-signer would not check either"))
    assert rules.preview(rec["id"], {"merchants": [B]})["ok"]


def test_returns_add_up_and_a_reclaim_meanwhile_is_refused(env, monkeypatch):
    rec, ledger = env
    assert rules.apply(rec["id"], {"spend": "0.5"})["returned"] == "0.1"
    assert rules.apply(rec["id"], {"spend": "0.4"})["returned"] == "0.1"
    after = deployments.get(rec["id"])
    assert after["returned_by_rules"] == "0.2" and after["hashes"]["returns"] == ["RETURNHASH", "RETURNHASH"]
    real_get = deployments.get
    calls = []

    def reclaimed_after_planning(dep_id):  # the 2nd read in apply sees the sweeper's reclaim
        calls.append(dep_id)
        r = real_get(dep_id)
        return {**r, "status": "reclaimed"} if len(calls) > 1 else r
    monkeypatch.setattr(deployments, "get", reclaimed_after_planning)
    assert rules.apply(rec["id"], {"approval_threshold": "0.1"})["refused"] == "not_active"
    assert real_get(rec["id"])["approval_threshold"] == "0.2"


def test_preview_applies_reviewed_ai_fields_without_reinterpretation(env, monkeypatch):
    rec, ledger = env
    calls = []
    def model(system, user, *args):
        calls.append(json.loads(user))
        return answer(approval_threshold="0.1", merchants=[{"operation": "remove", "names": ["Vendor C"]}])
    monkeypatch.setattr(rule_intent.llm, "extract", model)
    p = rules.preview(rec["id"], {"sentence": "Halve the approval amount and drop the last merchant."})
    assert p["ok"] and p["resolved_change"] == {"approval_threshold": "0.1", "merchants": [A]}
    assert calls[0]["current_rules"]["approval_threshold"] == "0.2"
    assert ledger["sent"] == []
    out = rules.apply(rec["id"], p["resolved_change"])
    assert out["ok"] and len(calls) == 1
    assert deployments.get(rec["id"])["allowed_payees"] == [A]


def test_ai_failure_or_ambiguity_never_applies_partial_edits(env, monkeypatch):
    rec, ledger = env
    for output in [None, {"spend": "0.3"}, answer(spend="0.3", problems=["Which merchant should be removed?"])]:
        monkeypatch.setattr(rule_intent.llm, "extract", lambda *args: output)
        out = rules.apply(rec["id"], {"sentence": "Halve the budget and remove that vendor."})
        assert out["refused"] == "rules_problems"
        assert ledger["sent"] == [] and deployments.get(rec["id"])["budget"] == "0.6"


def test_ai_proposal_still_checks_budget_and_credentials(env, monkeypatch):
    rec, ledger = env
    monkeypatch.setattr(rule_intent.llm, "extract", lambda *args: answer(spend="2"))
    assert rules.apply(rec["id"], {"sentence": "Double the budget."})["refused"] == "use_add_funds"
    monkeypatch.setattr(rule_intent.llm, "extract", lambda *args: answer(merchants=[{"operation": "only", "names": ["Vendor B"]}]))
    out = rules.apply(rec["id"], {"sentence": "Switch to Vendor B."})
    assert out["refused"] == "rules_problems" and "not trusted" in out["problems"][0]
    assert ledger["sent"] == []
