"""Sites named in a wallet sentence become the wallet's vendors (docs/SITES.md): free sites need no payment, paid
sites are paid at their own address (public if cereal-credentialed, private to the signed-in owner otherwise), and a
site cereal cannot use is a problem on the card, never silently dropped."""
from decimal import Decimal

import pytest

from cereal import config, wallet_card

D, C = "rsV4UZG7Qsxz1QfEwRehmAc3UkkWfXaF3Z", "r3NdoyQhgKorLo54v2VGkMrMTyPHbTXszs"
OWNER = {"id": "u_1", "name": "Andrew"}


def probe(url, kind, *, pay_to=None, amount="0.1", credential=None, verdict="ok", reason=None, title=None):
    host = url.split("/")[2].split(":")[0]
    return {"ok": True, "url": url, "host": host, "kind": kind, "title": title, "credential": credential,
            "payment": {"pay_to": pay_to, "amount": amount, "description": f"Vendor X: report"} if pay_to else None,
            "verdict": verdict, "verdict_reasons": [reason] if reason else [], "reason": reason}


@pytest.fixture
def card(monkeypatch):
    from cereal import sites_probe
    probes = {
        "https://npr.org": probe("https://npr.org", "free", title="NPR"),
        "http://localhost:8004/research/report": probe("http://localhost:8004/research/report", "payable", pay_to=D, credential="none", verdict="warn"),
        "http://localhost:8003/swell/agenda": probe("http://localhost:8003/swell/agenda", "payable", pay_to=C, amount="0.15", credential="valid"),
        "http://localhost:8006/research/report": probe("http://localhost:8006/research/report", "payable", pay_to=D, verdict="block",
                                                       reason="its xrp-ledger.toml does not list the payee"),
        "https://www.gatorade.com": probe("https://www.gatorade.com", "unreachable", reason="www.gatorade.com blocks automated agents"),
    }
    monkeypatch.setattr(sites_probe, "probe", lambda url: probes[url])
    monkeypatch.setattr(wallet_card, "parse_with_claude", lambda *a, **k: None)  # the backup parser reads the sentence
    monkeypatch.setattr(config, "APPROVAL_THRESHOLD", None, raising=False)

    def build(sentence, owner=None):
        return wallet_card.build_card(sentence, known=[], **({"owner": owner} if owner else {}))
    return build


def test_a_free_site_is_a_vendor_with_no_payee_and_the_payees_are_locked(card):
    c = card("News: spend up to 1 RLUSD today, use https://npr.org. Sweep back when done.")
    assert c["ok"] and c["payees_locked"] and c["allowed_payees"] == [] and c["site_specs"] == []
    (v,) = c["vendors"]
    assert v["site"] == {"url": "https://npr.org", "kind": "free", "trust": "free", "price": None}
    assert any("npr.org is free" in n for n in c["notes"])
    assert not any("no vendors named" in n for n in c["notes"])
    assert "reads npr.org for free" in c["summary"] and "at no paid vendor" in c["summary"]


def test_an_uncredentialed_paid_site_is_private_to_the_signed_in_owner(card):
    c = card("Report: spend up to 1 RLUSD today, buy http://localhost:8004/research/report.", owner=OWNER)
    assert c["ok"] and c["allowed_payees"] == [D]
    assert c["site_specs"] == ["http://localhost:8004/research/report@0.1"] and len(c["sites"]) == 1
    assert c["vendors"][0]["site"]["trust"] == "private" and c["vendors"][0]["credential"] == "none"
    assert any("your Ledger signs every payment" in n for n in c["notes"])


def test_without_a_sign_in_an_uncredentialed_paid_site_is_a_problem(card):
    c = card("Report: spend up to 1 RLUSD today, buy http://localhost:8004/research/report.")
    assert not c["ok"] and any("sign in to use localhost" in p for p in c["problems"]) and c["allowed_payees"] == []


def test_a_credentialed_paid_site_is_public(card):
    c = card("Agenda: spend up to 1 RLUSD today from http://localhost:8003/swell/agenda")
    assert c["ok"] and c["allowed_payees"] == [C] and c["vendors"][0]["site"]["trust"] == "public"


@pytest.mark.parametrize("url, words", [
    ("http://localhost:8006/research/report", "is blocked: its xrp-ledger.toml"),
    ("https://www.gatorade.com", "blocks automated agents"),
])
def test_a_site_cereal_cannot_use_is_a_problem_never_dropped(card, url, words):
    c = card(f"Spend up to 1 RLUSD today at {url}", owner=OWNER)
    assert not c["ok"] and any(words in p for p in c["problems"])


def test_sites_that_cost_more_than_the_budget_are_a_problem(card):
    c = card("Spend up to 0.05 RLUSD today on http://localhost:8004/research/report", owner=OWNER)
    assert not c["ok"] and any("more than the 0.05 RLUSD budget" in p for p in c["problems"])


def test_a_vendor_name_read_out_of_a_url_is_not_an_unknown_vendor(card, monkeypatch):
    monkeypatch.setattr(wallet_card, "parse_with_claude", lambda *a, **k: {
        "name": "News", "budget": "1", "expires_in_hours": 24, "vendor_names": ["NPR", "https://npr.org"],
        "approval_threshold": None, "sweep_when_done": True, "parsed_by": "test"})
    monkeypatch.setattr("cereal.llm.available", lambda: True)
    c = card("News: spend up to 1 RLUSD today, use https://npr.org")
    assert c["ok"] and not any("unknown vendor" in p for p in c["problems"])


def test_the_digest_covers_the_payee_lock_and_the_site_plan(card):
    a = card("News: spend up to 1 RLUSD today, use https://npr.org")
    b = dict(a, payees_locked=False)
    assert wallet_card.card_digest(a) != wallet_card.card_digest(b)


def test_a_locked_empty_payee_list_refuses_every_payment(monkeypatch):
    """The co-signer reads `payees_locked`: a wallet that named only free sites can pay nobody."""
    from xrpl.models.amounts import IssuedCurrencyAmount
    from xrpl.models.transactions import Payment
    from cereal import deployments, service
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)
    rec = {"id": "d_1", "status": "active", "subwallet": "rPocKRfAu1fM2pZzj1TyidFaCUKLEeEHzc", "allowed_payees": [],
           "payees_locked": True, "tag": "t", "expires_at": "2999-01-01T00:00:00+00:00"}
    monkeypatch.setattr(service, "client", lambda: object())
    tx = Payment(account=rec["subwallet"], destination=C,
                 amount=IssuedCurrencyAmount(currency=config.RLUSD_CURRENCY, issuer=config.RLUSD_ISSUER, value="0.1"))
    assert service._cosign_deployment(rec, tx.to_xrpl())["refused"] == "payee_not_allowed"


@pytest.mark.parametrize("sentence, urls", [
    ("use npr.org for research", ["https://npr.org"]),
    ("read www.npr.org/news and https://xrpl.org.", ["https://xrpl.org", "https://www.npr.org/news"]),
    ("email me at a@b.com", []),
    ("only at Vendor A and Vendor C, spend 1.5 RLUSD", []),
    ("https://npr.org and npr.org", ["https://npr.org"]),
])
def test_bare_web_addresses_are_recognized_like_full_urls(sentence, urls):
    assert wallet_card.site_urls(sentence) == urls


def test_a_site_that_blocks_agents_is_listed_and_offers_its_archived_copy(card, monkeypatch):
    from cereal import sites_probe
    walled = probe("https://www.thenorthface.com", "unreachable", reason="thenorthface.com blocks automated agents with Akamai's bot check")
    walled.update(blocked_by="Akamai", archive={"url": "https://web.archive.org/web/20261001000000/https://www.thenorthface.com/",
                                                "source": "Internet Archive", "timestamp": "2026-10-01T00:00:00Z"})
    monkeypatch.setattr(sites_probe, "probe", lambda url: walled)
    c = card("jacket: budget of $2, sweep back. research https://thenorthface.com", owner=OWNER)
    assert not c["ok"] and c["vendors"][0]["site"]["trust"] == "blocked" and c["vendors"][0]["site"]["blocked_by"] == "Akamai"
    assert any("Internet Archive copy from 2026-10-01 can be read instead" in p for p in c["problems"])
    assert "thenorthface" not in c["summary"] and c["allowed_payees"] == []
