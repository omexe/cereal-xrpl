"""AI boundary: strict proposals, minimal context, and no deterministic fallback."""
import json

import pytest

from cereal import rule_intent


def answer(**changes):
    return dict(spend=None, expires_in_hours=None, approval_threshold=None,
                clear_approval_threshold=False, sweep_when_done=None, merchants=[], problems=[],
                needs_add_funds=False) | changes


def test_partial_edit_preserves_unspecified_fields_and_whitelists_context(monkeypatch):
    captured = []
    def model(system, user, schema, name):
        captured.append(json.loads(user))
        assert schema["additionalProperties"] is False
        return answer(approval_threshold="0.10")
    monkeypatch.setattr(rule_intent.llm, "extract", model)
    out = rule_intent.interpret("Halve the approval threshold", "Research", {
        "budget": "0.6", "approval_threshold": "0.2", "seed": "do-not-send"},
        [{"name": "Vendor A", "address": "rA", "private": "do-not-send"}])
    assert out["fields"] == {"approval_threshold": "0.10"} and not out["problems"]
    assert "do-not-send" not in json.dumps(captured)
    assert captured[0]["vendors"] == [{"name": "Vendor A", "address": "rA"}]


@pytest.mark.parametrize("proposal", [None, {}, answer(spend=0.3), answer(sweep_when_done="false"),
                                      answer(expires_in_hours=float("inf")), answer(unexpected="instruction"),
                                      answer(merchants=[{"operation": "execute", "names": ["A"]}])])
def test_bad_model_answers_block_the_change(monkeypatch, proposal):
    monkeypatch.setattr(rule_intent.llm, "extract", lambda *args: proposal)
    out = rule_intent.interpret("spend up to 0.3", "Test", {}, [])
    assert out["problems"] and not out["fields"]


def test_threshold_can_only_be_cleared_explicitly(monkeypatch):
    monkeypatch.setattr(rule_intent.llm, "extract", lambda *args: answer(clear_approval_threshold=True))
    assert rule_intent.interpret("Stop asking", "Test", {}, [])["fields"] == {"approval_threshold": None}
    monkeypatch.setattr(rule_intent.llm, "extract", lambda *args: answer(clear_approval_threshold=True, approval_threshold="2"))
    assert rule_intent.interpret("Stop asking", "Test", {}, [])["problems"]


def test_demo_endpoint_proposes_partial_edits_without_persisting(monkeypatch):
    from fastapi.testclient import TestClient
    from cereal.service import app
    http = TestClient(app)
    current = {"spend": 20, "days": 2, "merchants": ["HubSpot", "Apollo"], "approval": 5, "sweep": True}
    monkeypatch.setattr(rule_intent.llm, "extract", lambda *args: answer(approval_threshold="2.5"))
    out = http.post('/demo/rules/preview', json={"sentence": "Halve the approval threshold", "name": "Demo", "current": current}).json()
    assert out["ok"] and out["constraints"] == {**current, "approval": 2.5}
    monkeypatch.setattr(rule_intent.llm, "extract", lambda *args: None)
    out = http.post('/demo/rules/preview', json={"sentence": "spend up to 10", "name": "Demo", "current": current}).json()
    assert not out["ok"] and out["constraints"] is None
