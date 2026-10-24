"""Model layer unit tests (OpenRouter faked; no credit spent): provider order, extraction, tool loop, safe fallback."""
import json

import pytest

from cereal import llm


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def msg(content=None, tool_calls=None):
    m = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return Resp(200, {"choices": [{"message": m}]})


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("CEREAL_LLM", "auto")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-not-a-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return monkeypatch


def test_provider_order_and_kill_switch(keys):
    assert llm.providers() == ["openrouter"]
    keys.setenv("ANTHROPIC_API_KEY", "x")
    assert llm.providers() == ["openrouter", "anthropic"]
    keys.setenv("CEREAL_LLM", "off")
    assert llm.providers() == [] and not llm.available()


def test_extract_uses_strict_json_schema_on_openrouter(keys):
    sent = []
    keys.setattr(llm.requests, "post", lambda url, json=None, **k: sent.append(json) or msg('{"items": ["agenda"]}'))
    assert llm.choose_items("the schedule", ["agenda", "speakers"]) == ["agenda"]
    rf = sent[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] and sent[0]["model"] == llm.OPENROUTER_MODEL
    assert llm.served_by == llm.OPENROUTER_MODEL


def test_extract_retries_without_structured_outputs_and_reads_fenced_json(keys):
    calls = []
    def post(url, json=None, **k):
        calls.append(json)
        if "response_format" in json:
            return Resp(400, {"error": {"message": "response_format not supported"}})
        return msg('Here you go:\n```json\n{"items": ["speakers", "made-up"]}\n```')
    keys.setattr(llm.requests, "post", post)
    assert llm.choose_items("who talks", ["agenda", "speakers"]) == ["speakers"], "only real catalog items survive"
    assert len(calls) == 2 and "JSON Schema" in calls[1]["messages"][0]["content"]


def test_extract_falls_back_to_anthropic_then_to_nothing(keys):
    keys.setenv("ANTHROPIC_API_KEY", "x")
    keys.setattr(llm.requests, "post", lambda *a, **k: Resp(503, {"error": {"message": "down"}}))
    keys.setattr(llm, "_anthropic_extract", lambda *a: {"items": ["agenda"]})
    assert llm.choose_items("x", ["agenda"]) == ["agenda"] and llm.served_by == llm.MODEL
    keys.setattr(llm, "_anthropic_extract", lambda *a: None)
    assert llm.choose_items("x", ["agenda"]) is None


def test_tool_loop_runs_tools_and_returns_the_final_text(keys):
    seq = [msg(None, [{"id": "c1", "type": "function", "function": {"name": "budget_left", "arguments": "{}"}}]),
           msg("done: 0.5 left")]
    sent = []
    import copy
    keys.setattr(llm.requests, "post", lambda url, json=None, **k: sent.append(copy.deepcopy(json)) or seq.pop(0))
    events = []
    out = llm.run_tool_loop("sys", "go", {"budget_left": ({"type": "object", "properties": {}}, lambda: {"left": "0.5"})},
                            on_event=lambda n, o: events.append((n, o)))
    assert out == "done: 0.5 left" and events == [("budget_left", {"left": "0.5"})]
    tool_msg = sent[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1" and json.loads(tool_msg["content"]) == {"left": "0.5"}


def test_a_provider_error_after_a_tool_ran_is_never_retried_elsewhere(keys):
    keys.setenv("ANTHROPIC_API_KEY", "x")
    seq = [msg(None, [{"id": "c1", "type": "function", "function": {"name": "pay", "arguments": '{"amount": "0.25"}'}}]),
           Resp(500, {"error": {"message": "boom"}})]
    keys.setattr(llm.requests, "post", lambda *a, **k: seq.pop(0))
    keys.setattr(llm, "_anthropic_loop", lambda *a, **k: pytest.fail("must not re-run a loop that already paid"))
    paid = []
    out = llm.run_tool_loop("sys", "go", {"pay": ({"type": "object"}, lambda amount: paid.append(amount) or {"ok": True})})
    assert paid == ["0.25"] and "not retried" in out


def test_a_provider_error_before_any_tool_falls_back(keys):
    keys.setenv("ANTHROPIC_API_KEY", "x")
    keys.setattr(llm.requests, "post", lambda *a, **k: Resp(401, {"error": {"message": "bad key"}}))
    keys.setattr(llm, "_anthropic_loop", lambda *a, **k: "anthropic finished")
    assert llm.run_tool_loop("sys", "go", {}) == "anthropic finished" and llm.served_by == llm.MODEL
