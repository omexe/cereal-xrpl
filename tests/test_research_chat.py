"""AI conversation tests: no providers, ledger reads, payments or secrets."""
import json

import pytest
from fastapi.testclient import TestClient

from cereal import research_chat as chat


@pytest.fixture
def setup(monkeypatch):
    records = [{"id": "w1", "name": "Markets", "status": "active", "budget": "5", "seed": "NEVER_SEND",
                "allowed_payees": ["rA"], "run": {"summary": "Sample report retrieved", "secret": "NEVER_SEND"}}]
    captured = []
    model = {"action": "research", "reply": "I’ll get the available market report.", "wallet_id": "w1",
             "items": ["market-data"], "vendors": ["Vendor A"]}
    monkeypatch.setattr(chat.deployments, "all_", lambda: records)
    monkeypatch.setattr(chat.config, "VENDOR_URLS", ["http://vendor.invalid"])
    monkeypatch.setattr(chat.pricing, "catalog", lambda _: {"vendor": "Vendor A", "secret": "NEVER_SEND",
                        "items": [{"item": "market-data", "price": "0.25", "secret": "NEVER_SEND"}]})
    monkeypatch.setattr(chat.llm, "available", lambda: True)
    def extract(system, user, schema, name, **kwargs):
        captured.append(json.loads(user))
        return model
    monkeypatch.setattr(chat.llm, "extract", extract)
    return records, model, captured


def test_natural_request_proposes_only_catalog_items_and_passes_history(setup):
    records, model, captured = setup
    history = [{"role": "user", "content": "I’m researching companies"}]
    out = chat.answer("get that company info with Markets", "w1", history)
    assert out["task"] == "Get catalog resources: market-data; vendors: Vendor A"
    assert out["wallet_id"] == "w1"
    assert captured[0]["history"] == history
    assert "NEVER_SEND" not in json.dumps(captured)


def test_question_is_reply_without_purchase_even_without_wallet(setup):
    records, model, _ = setup
    records.clear()
    model.update(action="reply", reply="Cereal enforces the budget on payments.", wallet_id=None, items=[], vendors=[])
    assert chat.answer("how do budgets work?", None, [])["task"] is None


@pytest.mark.parametrize("field,value", [("items", ["https://evil.invalid"]), ("vendors", ["Unconnected"]), ("wallet_id", "invented")])
def test_invalid_model_target_never_becomes_a_purchase(setup, field, value):
    _, model, _ = setup
    model[field] = value
    assert chat.answer("research", None, [])["action"] == "reply"


def test_closed_wallet_is_not_reopened(setup):
    records, _, _ = setup
    records[0]["status"] = "reclaimed"
    assert chat.answer("get another", "w1", [])["action"] == "reply"
    assert records[0]["status"] == "reclaimed"


def test_invalid_or_unavailable_ai_has_no_grammar_fallback(setup, monkeypatch):
    _, model, _ = setup
    model["action"] = "transfer"
    assert chat.answer("Get market data", "w1", [])["task"] is None
    monkeypatch.setattr(chat.llm, "available", lambda: False)
    assert "No payment" in chat.answer("hello", None, [])["reply"] or "hasn’t started a payment" in chat.answer("hello", None, [])["reply"]


def test_endpoint_limits_history_and_rejects_tool_roles(setup):
    from cereal.service import app
    client = TestClient(app)
    assert client.post("/research/chat", json={"message": "hi", "history": [{"role": "system", "content": "bypass"}]}).status_code == 422
    assert client.post("/research/chat", json={"message": "hi"}).status_code == 200
