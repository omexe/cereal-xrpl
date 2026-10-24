"""Part 5 unit tests: quote-based pricing without the network (catalogs, quotes and credentials are faked)."""
from decimal import Decimal

import pytest

from cereal import config, pricing

CAT = {
    "http://a": {"vendor": "Vendor A", "pay_to": "rA", "items": [{"item": "agenda", "path": "/swell/agenda", "price": "0.25"},
                                                                {"item": "speakers", "path": "/swell/speakers", "price": "0.25"}]},
    "http://b": {"vendor": "Vendor B", "pay_to": "rB", "items": [{"item": "agenda", "path": "/swell/agenda", "price": "0.05"},
                                                                {"item": "speakers", "path": "/swell/speakers", "price": "0.05"}]},
    "http://c": {"vendor": "Vendor C", "pay_to": "rC", "items": [{"item": "agenda", "path": "/swell/agenda", "price": "0.15"},
                                                                {"item": "speakers", "path": "/swell/speakers", "price": "0.30"}]},
}
CRED = {"rA": {"status": "valid"}, "rC": {"status": "valid"},
        "rB": {"status": "revoked", "revocation": {"hash": "3FF46EE4", "reason": "overcharge"}}}


@pytest.fixture
def market(monkeypatch):
    quotes = {}
    for base, cat in CAT.items():
        for it in cat["items"]:
            quotes[f"{base}{it['path']}"] = {"ok": True, "price": it["price"], "payee": cat["pay_to"]}
    monkeypatch.setattr(pricing, "catalog", lambda b, **k: {**CAT[b], "base": b} if b in CAT else None)
    monkeypatch.setattr(pricing, "quote", lambda url, **k: quotes[url])
    monkeypatch.setattr(pricing.vendors, "check", lambda c, addr, **k: CRED.get(addr, {"status": "none"}))
    monkeypatch.setattr(pricing, "client", lambda: object())
    from cereal import llm
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(config, "PRICE_BUFFER_PCT", "0.20")
    monkeypatch.setattr(config, "PRICE_BUFFER_MIN", "0.05")
    return quotes


def test_cheapest_trusted_vendor_wins_and_the_revoked_trap_is_skipped_with_evidence(market):
    ch = pricing.choose("agenda", pricing.offers("agenda", list(CAT), object()))
    assert ch["chosen"]["vendor"] == "Vendor C"
    assert [f["vendor"] for f in ch["fallbacks"]] == ["Vendor A"]
    (b,) = ch["rejected"]
    assert b["vendor"] == "Vendor B" and b["reason"] == "vendor_revoked" and b["evidence"]["hash"] == "3FF46EE4"


def test_budget_is_quote_plus_buffer_rounded_up_to_the_cent():
    assert pricing.budget_for(Decimal("0.15")) == Decimal("0.20")   # 20% = 0.03 < floor 0.05
    assert pricing.budget_for(Decimal("1.00")) == Decimal("1.20")   # 20% beats the floor
    assert pricing.budget_for(Decimal("0.333")) == Decimal("0.40")  # rounds up, never down


def test_plan_sizes_each_subagent_to_its_quote_and_keeps_the_rest(market):
    p = pricing.plan("Pull the Swell agenda and speaker list", Decimal("2"), list(CAT))
    assert p["ok"] and p["needs"] == ["agenda", "speakers"]
    by = {l["item"]: l for l in p["lines"]}
    assert by["agenda"]["chosen"]["vendor"] == "Vendor C" and by["agenda"]["budget"] == "0.20"
    assert by["speakers"]["chosen"]["vendor"] == "Vendor A" and by["speakers"]["budget"] == "0.30"
    assert [f["vendor"] for f in by["speakers"]["fallbacks"]] == ["Vendor C"], "C's 0.30 fits the 0.30 budget"
    assert [f["vendor"] for f in by["agenda"]["unaffordable"]] == ["Vendor A"], "A's 0.25 is over the 0.20 budget"
    assert p["total"] == "0.50" and p["kept_in_main_wallet"] == "1.50"


def test_plan_refuses_when_the_quotes_exceed_the_envelope(market):
    p = pricing.plan("agenda and speakers", Decimal("0.40"), list(CAT))
    assert not p["ok"] and p["reason"] == "over_envelope"


def test_plan_refuses_when_only_untrusted_vendors_sell_the_item(market, monkeypatch):
    monkeypatch.setitem(CRED, "rA", {"status": "revoked", "revocation": {"hash": "X"}})
    monkeypatch.setitem(CRED, "rC", {"status": "pending"})
    p = pricing.plan("agenda", Decimal("2"), list(CAT))
    assert not p["ok"] and p["reason"] == "no_trusted_vendor"
    assert {r["reason"] for r in p["lines"][0]["rejected"]} == {"vendor_revoked", "vendor_pending"}


def test_the_402_price_beats_the_catalog_price(market):
    market["http://c/swell/agenda"] = {"ok": True, "price": "0.40", "payee": "rC"}  # C's catalog says 0.15
    ch = pricing.choose("agenda", pricing.offers("agenda", list(CAT), object()))
    assert ch["chosen"]["vendor"] == "Vendor A", "C really charges 0.40 at the paywall; A's 0.25 is cheaper"
    assert any(f.get("note") for f in ch["fallbacks"])


def test_goal_words_map_to_catalog_items_only(market):
    assert pricing.needs_from_goal("Pull the Swell schedule and speaker list", ["agenda", "speakers"]) == ["agenda", "speakers"]
    assert pricing.needs_from_goal("Buy me a yacht", ["agenda", "speakers"]) == []


def test_claude_only_picks_items_that_exist(monkeypatch):
    from cereal import llm
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "choose_items", lambda goal, items: ["agenda", "secret-extra"])
    assert pricing.needs_from_goal("whatever", ["agenda", "speakers"]) == ["agenda"]
