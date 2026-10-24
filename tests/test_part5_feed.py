"""Part 5 unit tests: the security log, event reporting, the export and the plan preview (no network)."""
from decimal import Decimal

import pytest

from cereal import books, config, deployments, directory, events

A, B = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay", "rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(directory, "list_vendors", lambda c=None: [{"name": "Vendor A", "address": A}])
    rej = deployments.create("extra subagent", "1", [])
    deployments.update(rej["id"], status="rejected", approval={"result": "owner_rejected", "screens": ["Amount: 1"]})
    d = deployments.create("agenda", "0.20", [A])
    deployments.update(d["id"], status="reclaimed", name="Market Sizing", folder="Market Research",
                       plan={"item": "agenda", "rejected": [{"vendor": "Vendor B", "price": "0.05",
                                                             "reason": "vendor_revoked", "evidence": "3FF46EE4"}]})
    deployments.record_refusal(d["id"], {"payee": B, "amount": "0.05", "refused": "vendor_not_credentialed",
                                         "vendor": {"status": "revoked", "revocation": {"hash": "3FF46EE4"}}, "at": "2026-10-24T22:00:01"})
    deployments.record_event(d["id"], {"kind": "stolen_keys_drain", "result": "tecPATH_PARTIAL", "hash": "27054551",
                                       "verified": True, "at": "2026-10-24T22:00:02"})
    deployments.record_event(d["id"], {"kind": "hijack_alone", "result": "tefBAD_QUORUM", "hash": None,
                                       "verified": None, "at": "2026-10-24T22:00:03"})
    deployments.record_payment(d["id"], {"to": A, "amount": "0.25", "rail": "direct", "ok": True, "result": "tesSUCCESS",
                                         "hash": "1FF73366", "approved_by": "ledger", "approval": {"threshold": "0.2"},
                                         "explorer": "https://testnet.xrpl.org/transactions/1FF73366", "at": "2026-10-24T22:00:04"})
    deployments.record_payment(d["id"], {"to": A, "amount": "0.15", "rail": "x402", "ok": True, "result": "tesSUCCESS",
                                         "hash": "EDE22D06", "resource": "http://v/swell/agenda", "at": "2026-10-24T22:00:05"})
    return d["id"]


def test_the_feed_says_who_stopped_each_attempt_and_shows_proof(store):
    by_kind = {e["kind"]: e for e in events.feed()}
    assert by_kind["budget_rejected"]["by"] == "owner" and by_kind["budget_rejected"]["outcome"] == "nothing sent"
    assert by_kind["payment_refused"]["by"] == "cereal" and by_kind["payment_refused"]["proof"].endswith("3FF46EE4")
    assert by_kind["vendor_skipped"]["by"] == "main agent" and "revoked" in by_kind["vendor_skipped"]["why"]
    assert by_kind["stolen_keys_drain"]["by"] == "ledger" and by_kind["stolen_keys_drain"]["outcome"].startswith("capped")
    assert by_kind["hijack_alone"]["why"] == "one signature isn't enough to move this wallet's money"
    assert by_kind["large_payment_approved"]["outcome"] == "signed by the owner's Ledger"


def test_reported_events_are_checked_against_the_ledger(store, monkeypatch):
    from cereal import service
    class C:
        def request(self, req):
            return type("R", (), {"result": {"validated": True, "meta": {"TransactionResult": "tecPATH_PARTIAL"}}})()
    monkeypatch.setattr(service, "client", lambda: C())
    ok = service.report_event(store, service.EventReport(kind="stolen_keys_drain", result="tecPATH_PARTIAL", hash="H1"))
    lie = service.report_event(store, service.EventReport(kind="stolen_keys_drain", result="tesSUCCESS", hash="H1"))
    assert ok["verified"] is True and lie["verified"] is False, "a claimed result that the ledger contradicts is flagged"
    assert service.report_event(store, service.EventReport(kind="free_money", result="x"))["refused"] == "unknown_event_kind"


def test_export_rows_totals_and_csv(store):
    rs = books.rows()
    assert [r["amount"] for r in rs] == ["0.25", "0.15"]
    assert rs[0]["signed_by"] == "subagent + owner's Ledger" and rs[1]["signed_by"] == "subagent + cereal"
    assert rs[0]["wallet"] == "Market Sizing" and rs[0]["folder"] == "Market Research" and rs[0]["vendor"] == "Vendor A"
    t = books.totals(rs)
    assert t["rlusd"] == "0.40" and t["by_rail"] == {"direct": "0.25", "x402": "0.15"}
    csv_text = books.to_csv(rs)
    assert csv_text.splitlines()[0].startswith("date,folder,wallet,deployment") and "1FF73366" in csv_text


def test_plan_preview_returns_the_plan_and_its_summary(monkeypatch):
    from cereal import pricing, service
    monkeypatch.setattr(pricing, "plan", lambda goal, env: {"ok": True, "goal": goal, "envelope": str(env), "total": "0.50",
                                                            "kept_in_main_wallet": "1.50", "lines": [], "vendors_seen": []})
    out = service.plan_preview("Pull the Swell agenda", "2")
    assert out["total"] == "0.50" and out["summary"][0].startswith("plan for: Pull the Swell agenda")
