"""Chat flow and sweeper unit tests (no network): what the hivemind says and deploys, and what the sweeper sweeps."""
from datetime import datetime, timedelta, timezone

import pytest

from cereal import config, deployments


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    return monkeypatch


def test_sweeper_reclaims_expired_wallets_and_retires_old_ones(store):
    from cereal import service
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    exp = deployments.create("expired", "1", [])
    deployments.update(exp["id"], status="active", subwallet="rEXP", expires_at=past)
    live = deployments.create("live", "1", [])
    deployments.update(live["id"], status="active", subwallet="rLIVE")
    old = deployments.create("old", "1", [])
    deployments.update(old["id"], status="reclaimed", subwallet="rOLD")
    calls = []
    store.setattr(service, "reclaim", lambda d: calls.append(("reclaim", d)) or {"ok": True, "returned": "0.4"})
    store.setattr(service, "retire", lambda d: calls.append(("retire", d)) or {"ok": True, "hash": "H"})
    out = service.sweep_once()
    assert ("reclaim", exp["id"]) in calls and ("reclaim", live["id"]) not in calls, "only expired wallets are swept"
    assert ("retire", old["id"]) in calls
    assert out["swept"] == [{"deployment": exp["id"], "returned": "0.4"}]
    assert deployments.get(exp["id"])["swept_by"] == "expiry"


def test_recent_sweeps_say_why_newest_first(store):
    from cereal import service
    a = deployments.create("a", "1", [])
    deployments.update(a["id"], status="reclaimed", returned="0.05", reclaimed_at="2026-10-24T20:00:00", name="Agenda")
    b = deployments.create("b", "1", [])
    deployments.update(b["id"], status="reclaimed", returned="0.6", reclaimed_at="2026-10-24T21:00:00", swept_by="expiry")
    s = service.recent_sweeps()
    assert [x["returned"] for x in s] == ["0.6", "0.05"] and s[0]["why"] == "expired" and s[1]["wallet"] == "Agenda"


class R:
    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


def test_chat_turns_one_message_into_rules_a_subagent_a_purchase_and_a_sweep(store):
    from cereal import chat, main_agent, pricing
    card = {"ok": True, "summary": "Spend up to 1 RLUSD over 1 day, only at Vendor C.", "budget": "1",
            "allowed_payees": ["rC"], "expires_in_hours": 24, "approval_threshold": None, "name": "Research",
            "notes": [], "parsed_by": "anthropic/claude-haiku-5.5"}
    line = {"item": "agenda", "price": "0.15", "budget": "0.20", "fallbacks": [], "rejected": [
        {"vendor": "Vendor A", "reason": "not_on_your_list", "quote": {"price": "0.25"}}],
        "chosen": {"vendor": "Vendor C", "url": "http://c/swell/agenda", "payee": "rC", "quote": {"price": "0.15"}}}
    store.setattr(pricing, "plan", lambda goal, env, allowed=None: {"ok": True, "needs": ["agenda"], "total": "0.20", "lines": [line]})
    store.setattr(chat, "directory_names", lambda addrs: ["Vendor C"])
    posted, rec = [], {"status": "reclaimed", "returned": "0.05", "hashes": {"reclaim": ["SW1"]},
                       "payments": [{"ok": True, "amount": "0.15"}]}
    def post(url, json=None, **k):
        posted.append((url.rsplit("/", 1)[-1], json))
        return R(card if url.endswith("/wallets/preview") else {"ok": True, "id": "d_1", "hashes": {"fund": "F1"}})
    store.setattr(chat.requests, "post", post)
    store.setattr(chat.requests, "get", lambda url, **k: R(rec))
    store.setattr(main_agent.MainAgent, "start_subagent", lambda self, d, task, payments=2, extra=None:
                  posted.append(("start", extra)) or {"started": d})
    def wait(self, d, timeout_s=0):
        self.logs[d] = [{"event": "start", "data": {"mode": "plan", "budget": "0.20"}},
                        {"event": "buy", "data": {"ok": True, "resource": "http://c/swell/agenda", "price": "0.15", "explorer": "X"}}]
        return {"exit": 0}
    store.setattr(main_agent.MainAgent, "wait_subagent", wait)
    out = chat.run("Research: spend up to 1 RLUSD today only at Vendor C, get the agenda", say=lambda *a: None)
    deploy = next(j for name, j in posted if name == "subagents")
    assert deploy["budget"] == "0.20" and deploy["allowed_payees"] == ["rC"] and deploy["sweep_when_done"]
    assert ("start", ["--buy", "http://c/swell/agenda@0.15"]) in posted
    text = " | ".join(m["text"] for m in out["messages"])
    assert "Vendor C at 0.15 RLUSD is the cheapest vendor you allowed; skipped Vendor A (not on your list)" in text
    assert "Bought agenda for 0.15 RLUSD" in text and "Swept 0.05 RLUSD back to the main wallet" in text
    assert out["ok"] and out["returned"] == "0.05"


def test_chat_refuses_a_card_with_problems_and_deploys_nothing(store):
    from cereal import chat
    store.setattr(chat.requests, "post", lambda url, json=None, **k: R(
        {"ok": False, "summary": "…", "problems": ["unknown vendor 'HubSpot'"], "notes": []}) if url.endswith("preview")
        else pytest.fail("must not deploy"))
    out = chat.run("buy from HubSpot", say=lambda *a: None)
    assert not out["ok"] and "unknown vendor 'HubSpot'" in out["messages"][-1]["text"]
