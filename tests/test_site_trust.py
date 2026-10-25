"""Sites, unit 2 (offline): sessions, each user's private site list, the wallet-list filter, the signing rule for
private and blocked sites, and the delivery check. The probe and the ledger are faked; signing uses throwaway keys so
the combined transaction's signers can be checked: a private site's payment is the subagent + the owner's Ledger,
never cereal.
"""
import hashlib
import json
import stat
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from xrpl.core.binarycodec import decode, encode
from xrpl.models.transactions.transaction import Transaction
from xrpl.transaction import sign
from xrpl.wallet import Wallet

from cereal import config, deployments, device, events, owners, site_registry, sites_probe, vendors

D = "rsV4UZG7Qsxz1QfEwRehmAc3UkkWfXaF3Z"   # Vendor D: honest, not credentialed
E = "rPocKRfAu1fM2pZzj1TyidFaCUKLEeEHzc"   # Vendor E: takes payment, then 500
A = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"   # a credentialed vendor
B = "rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3"   # a revoked vendor
AGENT, DEVICE = Wallet.create(), Wallet.create()  # throwaway keys: the subagent's and the "owner's Ledger"
SUB = Wallet.create().classic_address


def probe_for(url, kind="payable", pay_to=D, credential="none", verdict="warn", price="0.1", **over):
    host = url.split("//", 1)[-1].split("/", 1)[0].split(":")[0]
    payment = None if kind != "payable" else {
        "network": "xrpl:1", "asset": config.RLUSD_CURRENCY, "issuer": config.RLUSD_ISSUER, "amount": price,
        "pay_to": pay_to, "resource": url, "description": "test", "invoice_id": None}
    return {"ok": True, "url": url, "origin": url.rsplit("/", 2)[0], "host": host, "kind": kind,
            "status": 402 if kind == "payable" else 200, "title": None, "payment": payment, "accepts": [],
            "reason": None, "credential": credential if kind == "payable" else None, "checks": [],
            "verdict": verdict, "verdict_reasons": ["The address is new."] if verdict == "warn" else [],
            "trust_hint": "private", **over}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    return tmp_path


@pytest.fixture
def api(store, monkeypatch):
    from cereal import service
    monkeypatch.setattr(service, "client", lambda: object())
    probes = {}
    monkeypatch.setattr(sites_probe, "probe", lambda url: probes.get(url) or probe_for(url))
    client = TestClient(service.app)
    client.probes = probes
    return client


def session(api, name):
    r = api.post("/session", json={"name": name}).json()
    assert r["ok"], r
    return r["user"], {"Authorization": f"Bearer {r['token']}"}


# ---- sessions ----

def test_a_session_returns_its_token_once_and_stores_only_its_hash(api, store):
    r = api.post("/session", json={"name": "  Alice  "}).json()
    assert r["ok"] and r["user"]["name"] == "Alice" and r["user"]["id"].startswith("u_") and len(r["token"]) >= 40
    path = store / "deployments.users.json"
    text = path.read_text()
    assert r["token"] not in text, "the token itself is never stored"
    assert hashlib.sha256(r["token"].encode()).hexdigest() in text
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    me = api.get("/session", headers={"Authorization": f"Bearer {r['token']}"}).json()
    assert me == {"ok": True, "user": r["user"]}, "GET /session never shows the token again"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"},
                                     {"Authorization": "Bearer "}])
def test_no_or_a_wrong_token_is_401(api, headers):
    session(api, "Alice")
    assert api.get("/session", headers=headers).status_code == 401


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, "tab\there", None])
def test_names_are_1_to_40_printable_characters(api, name):
    r = api.post("/session", json={"name": name}).json()
    assert r["ok"] is False and r["refused"] == "invalid_name"
    assert api.post("/session", json={"name": "x" * 40}).json()["ok"]


def test_each_session_is_a_distinct_user(api):
    (a, ha), (b, hb) = session(api, "Alice"), session(api, "Alice")
    assert a["id"] != b["id"]
    assert owners.user_for_token(ha["Authorization"].split()[1]) == a
    assert owners.user_for_token(hb["Authorization"].split()[1]) == b


# ---- the site list: tiers, dedupe, privacy ----

def test_trust_tiers_follow_the_probe(api):
    _, h = session(api, "Alice")
    api.probes.update({
        "http://localhost:8004/research/report": probe_for("http://localhost:8004/research/report"),
        "http://localhost:8000/swell/agenda": probe_for("http://localhost:8000/swell/agenda", pay_to=A,
                                                        credential="valid", verdict="ok"),
        "https://example.com/": probe_for("https://example.com/", kind="free", verdict="ok"),
    })
    tiers = {u: api.post("/sites", json={"url": u}, headers=h).json()["site"]["trust"] for u in api.probes}
    assert tiers == {"http://localhost:8004/research/report": "private", "http://localhost:8000/swell/agenda": "public",
                     "https://example.com/": "free"}
    listed = api.get("/sites", headers=h).json()
    assert {s["trust"] for s in listed} == {"private", "public", "free"}
    site = next(s for s in listed if s["trust"] == "private")
    assert site["id"].startswith("s_") and site["owner"].startswith("u_") and site["name"] == "localhost"
    assert site["blocked_reason"] is None and site["wallets"] == [] and site["added_at"] and site["probed_at"]
    assert site["payment"]["pay_to"] == D and site["kind"] == "payable" and "ok" not in site


def test_a_blocking_verdict_is_stored_blocked_and_refused_with_the_site(api):
    _, h = session(api, "Alice")
    url = "http://localhost:8006/research/report"
    api.probes[url] = probe_for(url, pay_to=E, verdict="block", trust_hint="blocked",
                                verdict_reasons=["The site's xrp-ledger.toml does not list this address."],
                                checks=[{"name": "domain_proof", "ok": False, "detail": "toml lists another address"}])
    r = api.post("/sites", json={"url": url}, headers=h).json()
    assert r["ok"] is False and r["refused"] == "site_blocked"
    assert r["site"]["trust"] == "blocked" and "toml" in r["site"]["blocked_reason"]
    assert r["site"]["blocked_evidence"]["checks"][0]["name"] == "domain_proof"
    assert [s["trust"] for s in api.get("/sites", headers=h).json()] == ["blocked"], "kept so the owner sees why"


@pytest.mark.parametrize("kind", ["unreachable", "unpayable"])
def test_unreachable_and_unpayable_sites_are_refused_and_not_stored(api, kind):
    _, h = session(api, "Alice")
    api.probes["https://x.test/"] = probe_for("https://x.test/", kind=kind, reason="401 sign-in wall")
    r = api.post("/sites", json={"url": "https://x.test/"}, headers=h).json()
    assert r["ok"] is False and r["refused"] == "not_accessible" and r["kind"] == kind
    assert api.get("/sites", headers=h).json() == []


def test_a_probe_refusal_passes_through_and_nothing_is_stored(api, monkeypatch):
    _, h = session(api, "Alice")
    monkeypatch.setattr(sites_probe, "probe", lambda url: {"ok": False, "refused": "unsafe_url", "reason": "private"})
    assert api.post("/sites", json={"url": "http://10.0.0.1/"}, headers=h).json()["refused"] == "unsafe_url"
    assert api.post("/sites", json={"url": "  "}, headers=h).json()["refused"] == "invalid_url"
    assert api.get("/sites", headers=h).json() == []


def test_adding_the_same_url_again_refreshes_it(api):
    _, h = session(api, "Alice")
    url = "http://localhost:8004/research/report"
    first = api.post("/sites", json={"url": url}, headers=h).json()["site"]
    api.probes[url] = probe_for(url, price="0.2")
    again = api.post("/sites", json={"url": url}, headers=h).json()
    assert again["refreshed"] and again["site"]["id"] == first["id"] and again["site"]["added_at"] == first["added_at"]
    assert again["site"]["payment"]["amount"] == "0.2"
    assert len(api.get("/sites", headers=h).json()) == 1


def test_another_users_sites_are_invisible_and_a_404(api):
    _, alice = session(api, "Alice")
    _, bob = session(api, "Bob")
    site = api.post("/sites", json={"url": "http://localhost:8004/research/report"}, headers=alice).json()["site"]
    assert api.get("/sites", headers=bob).json() == []
    assert api.post(f"/sites/{site['id']}/remove", headers=bob).status_code == 404
    assert len(api.get("/sites", headers=alice).json()) == 1, "Bob's attempt removed nothing"
    assert api.post(f"/sites/{site['id']}/remove", headers=alice).json() == {"ok": True}
    assert api.get("/sites", headers=alice).json() == []
    assert api.post(f"/sites/{site['id']}/remove", headers=alice).status_code == 404


@pytest.mark.parametrize("method,path", [("get", "/sites"), ("post", "/sites"), ("post", "/sites/s_abc/remove")])
def test_every_sites_route_needs_a_session(api, method, path):
    r = getattr(api, method)(path, **({"json": {"url": "https://example.com/"}} if method == "post" else {}))
    assert r.status_code == 401


# ---- blocks and trust_for ----

def test_block_blocks_every_site_of_that_owner_paying_the_address_and_nobody_elses(store):
    site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))
    site_registry.add("u_alice", probe_for("http://localhost:8004/research/other"))
    site_registry.add("u_alice", probe_for("http://localhost:8005/research/report", pay_to=E))
    site_registry.add("u_bob", probe_for("http://localhost:8004/research/report"))
    changed = site_registry.block("u_alice", D, "paid_not_delivered", {"hash": "H"})
    assert len(changed) == 2 and all(s["trust"] == "blocked" for s in changed)
    assert site_registry.trust_for("u_alice", D) == "blocked"
    assert site_registry.trust_for("u_alice", E) == "private"
    assert site_registry.trust_for("u_bob", D) == "private", "one owner's evidence never touches another's list"
    assert site_registry.trust_for(None, D) is None and site_registry.trust_for("u_carol", D) is None
    blocked = next(s for s in site_registry.list_for("u_alice") if s["trust"] == "blocked")
    assert blocked["blocked_reason"] == "paid_not_delivered"
    assert blocked["blocked_evidence"] == {"payee": D, "hash": "H"} and blocked["blocked_by"] == "paid_not_delivered"


def test_evidence_outlives_a_re_add_and_a_new_url_paying_the_same_address(store):
    url = "http://localhost:8005/research/report"
    site_registry.add("u_alice", probe_for(url, pay_to=E))
    site_registry.block("u_alice", E, "paid_not_delivered", {"hash": "H"})
    again = site_registry.add("u_alice", probe_for(url, pay_to=E))
    assert again["refused"] == "site_blocked" and again["site"]["blocked_evidence"]["hash"] == "H"
    other = site_registry.add("u_alice", probe_for("http://localhost:8005/other", pay_to=E))
    assert other["refused"] == "site_blocked" and other["site"]["blocked_reason"] == "paid_not_delivered"
    assert site_registry.trust_for("u_alice", E) == "blocked"


def test_evidence_outlives_a_new_pay_to_on_the_same_url(store):
    url = "http://localhost:8005/research/report"
    site_registry.add("u_alice", probe_for(url, pay_to=E))
    site_registry.block("u_alice", E, "paid_not_delivered", {"hash": "H"})
    moved = site_registry.add("u_alice", probe_for(url, pay_to=D))  # the site now asks to be paid somewhere else
    assert moved["refused"] == "site_blocked" and moved["site"]["payment"]["pay_to"] == D
    assert site_registry.trust_for("u_alice", E) == "blocked", "the address that took the money stays blocked"
    assert site_registry.trust_for("u_alice", D) == "blocked", "and so does the URL's new address"


def test_removing_an_evidence_blocked_site_hides_it_but_keeps_the_evidence(store):
    url = "http://localhost:8005/research/report"
    sid = site_registry.add("u_alice", probe_for(url, pay_to=E))["site"]["id"]
    site_registry.block("u_alice", E, "paid_not_delivered", {"hash": "H"})
    assert site_registry.remove("u_alice", sid)
    assert site_registry.list_for("u_alice") == [] and site_registry.get("u_alice", sid) is None
    assert not site_registry.remove("u_alice", sid) and site_registry.update("u_alice", sid, wallets=[]) is None
    assert site_registry.trust_for("u_alice", E) == "blocked"
    back = site_registry.add("u_alice", probe_for(url, pay_to=E))
    assert back["refused"] == "site_blocked" and back["site"]["id"] == sid and "removed_at" not in back["site"]
    assert [s["id"] for s in site_registry.list_for("u_alice")] == [sid]
    plain = site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))["site"]["id"]
    assert site_registry.remove("u_alice", plain) and site_registry.trust_for("u_alice", D) is None, \
        "a site without evidence is simply removed"


def test_a_probe_block_is_about_one_url_and_is_re_evaluated(store):
    over = "http://localhost:8004/research/huge"
    site_registry.add("u_alice", probe_for(over, verdict="block", price="5", verdict_reasons=["Above the cap."]))
    assert site_registry.trust_for("u_alice", D) == "blocked", "only a blocked site pays this address"
    site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))
    assert site_registry.trust_for("u_alice", D) == "private", "the over-cap URL does not taint the address"
    fixed = site_registry.add("u_alice", probe_for(over, price="0.5"))
    assert fixed["ok"] and fixed["site"]["trust"] == "private" and fixed["site"]["blocked_reason"] is None
    site_registry.add("u_bob", probe_for("http://localhost:8000/swell/huge", pay_to=A, credential="valid",
                                         verdict="block", verdict_reasons=["Above the cap."]))
    site_registry.add("u_bob", probe_for("http://localhost:8000/swell/agenda", pay_to=A, credential="valid",
                                         verdict="ok"))
    assert site_registry.trust_for("u_bob", A) is None, "a public listing of the address is not blocked either"


def test_update_and_get_are_scoped_to_the_owner(store):
    sid = site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))["site"]["id"]
    assert site_registry.get("u_bob", sid) is None and site_registry.update("u_bob", sid, wallets=["d_x"]) is None
    s = site_registry.update("u_alice", sid, wallets=["d_1"], id="s_other", owner="u_bob")
    assert s["wallets"] == ["d_1"] and s["id"] == sid and s["owner"] == "u_alice"
    assert site_registry.get("u_alice", sid)["wallets"] == ["d_1"]


# ---- GET /subagents hides other users' wallets ----

def test_the_wallet_list_hides_wallets_owned_by_someone_else(api):
    alice, ha = session(api, "Alice")
    bob, hb = session(api, "Bob")
    shared = deployments.create("company task", "1", [A])["id"]
    mine = deployments.update(deployments.create("alice site", "0.25", [D])["id"], owner=alice["id"])["id"]
    theirs = deployments.update(deployments.create("bob site", "0.25", [D])["id"], owner=bob["id"])["id"]
    ids = lambda h: {r["id"] for r in api.get("/subagents", headers=h).json()}
    assert ids(ha) == {shared, mine}
    assert ids(hb) == {shared, theirs}
    assert ids({}) == {shared}
    assert ids({"Authorization": "Bearer forged"}) == {shared}
    assert api.get(f"/subagents/{theirs}").json()["id"] == theirs, "a subagent still reads its own record, tokenless"


# ---- the signing rule ----

@pytest.fixture
def policy(store, monkeypatch):
    """_cosign_deployment with the ledger faked. cereal's own co-sign paths and its key fail the test if touched;
    the "device" signs with a throwaway key so the combined transaction is real."""
    from cereal import service
    calls = {"device": [], "submit": [], "cosign": []}
    status = {D: "none", E: "none", A: "valid", B: "revoked"}
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", True)
    monkeypatch.setattr(config, "APPROVAL_THRESHOLD", None)
    monkeypatch.setattr(config, "DEVICE_DECISION", "approve")
    monkeypatch.setattr(service, "client", lambda: object())
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: Decimal("0.25"))
    monkeypatch.setattr(vendors, "check", lambda c, addr, **k: {"status": status.get(addr, "none"), "vendor": addr})
    monkeypatch.setattr(device, "available", lambda: True)

    def fake_device(tx, decision=None):
        calls["device"].append((tx, decision))
        if decision == "reject":
            return {"ok": False, "result": "owner_rejected", "screens": ["Reject"]}
        return {"ok": True, "signedBlob": encode(sign(tx, DEVICE, multisign=True).to_xrpl()),
                "address": DEVICE.classic_address, "screens": ["Review payment"]}
    monkeypatch.setattr(device, "sign", fake_device)
    monkeypatch.setattr(service, "submit_capture", lambda tx, c: calls["submit"].append(tx) or
                        {"ok": True, "hash": tx.get_hash(), "result": "tesSUCCESS", "validated": True})

    def cereal_key(role):
        if role == "CEREAL_COSIGN":
            calls["cosign"].append(role)

            class _Key:  # a stand-in for cereal's co-signing key (public vendors only)
                classic_address = "rCEREALcosign"
            return _Key()
        raise AssertionError(role)
    monkeypatch.setattr(config, "wallet", cereal_key)

    class _Combined:
        def get_hash(self):
            return "COSIGNED"

        def blob(self):
            return "00"
    monkeypatch.setattr(service, "cosign_combine", lambda tx, w: calls["cosign"].append("combine") or _Combined())
    monkeypatch.setattr(service, "cosign_and_submit", lambda tx, w, c: calls["cosign"].append("submit") or
                        {"ok": True, "hash": "COSIGNED"})
    return service, calls


def wallet_for(owner="u_alice", payees=(D,), **extra):
    rec = deployments.create("site purchase", "0.25", list(payees))
    return deployments.update(rec["id"], status="active", subwallet=SUB, buy_only=True, **({"owner": owner} if owner
                                                                                            else {}), **extra)


def signed_payment(rec, payee=D, value="0.01", **over):
    from cereal.pay import build_payment
    tx = build_payment(SUB, payee, value, rec["id"], rec["tag"])
    tx = Transaction.from_dict({**tx.to_dict(), "fee": "36", "sequence": 7, "last_ledger_sequence": 999, **over})
    return sign(tx, AGENT, multisign=True).to_xrpl()


def signers(blob_or_tx):
    tx = decode(blob_or_tx) if isinstance(blob_or_tx, str) else blob_or_tx.to_xrpl()
    return {s["Signer"]["Account"] for s in tx.get("Signers", [])}


def test_a_private_site_payment_goes_to_the_owners_ledger_even_at_one_cent(policy):
    service, calls = policy
    site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))
    rec = wallet_for()
    r = service._cosign_deployment(rec, signed_payment(rec, value="0.01"), present=True,
                                   resource="http://localhost:8004/research/report")
    assert r["ok"] and r["presented"] and r["approved_by"] == "ledger" and r["reason"] == "private_site"
    assert len(calls["device"]) == 1 and calls["cosign"] == [], "cereal never co-signs an uncredentialed payee"
    assert signers(r["blob"]) == {AGENT.classic_address, DEVICE.classic_address}
    (p,) = deployments.get(rec["id"])["payments"]
    assert p["approved_by"] == "ledger" and p["reason"] == "private_site" and p["approval"]["reason"] == "private_site"
    assert p["approval"]["threshold"] == "0" and p["hash"] == r["hash"] and p["result"] == "presented"
    assert p["resource"] == "http://localhost:8004/research/report"
    (e,) = [e for e in events.feed() if e["deployment"] == rec["id"]]
    assert e["kind"] == "private_site_approved" and e["outcome"] == "signed by the owner's Ledger"


def test_a_direct_private_payment_is_submitted_with_the_ledgers_signature_not_cereals(policy):
    service, calls = policy
    site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))
    rec = deployments.update(wallet_for()["id"], buy_only=None)
    r = service._cosign_deployment(rec, signed_payment(rec))
    assert r["ok"] and r["approved_by"] == "ledger" and r["reason"] == "private_site"
    (sent,) = calls["submit"]
    assert signers(sent) == {AGENT.classic_address, DEVICE.classic_address} and calls["cosign"] == []


def test_a_blocked_site_is_refused_before_any_signature(policy):
    service, calls = policy
    site_registry.add("u_alice", probe_for("http://localhost:8005/research/report", pay_to=E))
    site_registry.block("u_alice", E, "paid_not_delivered", {"hash": "H"})
    rec = wallet_for(payees=(E,))
    r = service._cosign_deployment(rec, signed_payment(rec, payee=E), present=True)
    assert r["ok"] is False and r["refused"] == "site_blocked" and r["payee"] == E
    assert calls == {"device": [], "submit": [], "cosign": []}


def test_a_public_payee_is_unchanged_cereal_cosigns_below_the_threshold(policy):
    service, calls = policy
    rec = wallet_for(payees=(A,))
    r = service._cosign_deployment(rec, signed_payment(rec, payee=A), present=True)
    assert r == {"ok": True, "presented": True, "hash": "COSIGNED", "blob": "00"}
    assert calls["device"] == [] and "combine" in calls["cosign"]
    assert "reason" not in deployments.get(rec["id"])["payments"][0]


def test_an_owners_evidence_blocks_even_a_credentialed_payee_for_that_owner_only(policy):
    service, calls = policy
    site_registry.add("u_alice", probe_for("http://localhost:8000/swell/agenda", pay_to=A, credential="valid"))
    site_registry.block("u_alice", A, "paid_not_delivered", {"hash": "H"})
    alice = wallet_for(payees=(A,))
    r = service._cosign_deployment(alice, signed_payment(alice, payee=A), present=True)
    assert r["refused"] == "site_blocked" and calls == {"device": [], "submit": [], "cosign": []}
    for other in (wallet_for(owner="u_bob", payees=(A,)), wallet_for(owner=None, payees=(A,))):
        assert service._cosign_deployment(other, signed_payment(other, payee=A), present=True)["ok"], \
            "another owner's (or an unowned) wallet still pays a credentialed vendor"


@pytest.mark.parametrize("owner_lists_it", [True, False])
def test_a_revoked_payee_is_refused_even_on_the_owners_private_list(policy, owner_lists_it):
    service, calls = policy
    if owner_lists_it:
        site_registry.add("u_alice", probe_for("http://localhost:8002/swell/agenda", pay_to=B))
    rec = wallet_for(payees=(B,))
    r = service._cosign_deployment(rec, signed_payment(rec, payee=B), present=True)
    assert r["refused"] == "vendor_not_credentialed" and r["vendor"]["status"] == "revoked"
    assert calls == {"device": [], "submit": [], "cosign": []}


@pytest.mark.parametrize("owner", [None, "u_bob"])
def test_an_uncredentialed_payee_not_on_the_wallet_owners_list_is_refused(policy, owner):
    service, calls = policy
    site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))  # Alice's, not this wallet's
    rec = wallet_for(owner=owner)
    r = service._cosign_deployment(rec, signed_payment(rec), present=True)
    assert r["refused"] == "vendor_not_credentialed"
    assert calls == {"device": [], "submit": [], "cosign": []}


@pytest.mark.parametrize("case,refused", [
    ("not_allowed", "payee_not_allowed"), ("over_budget", "over_budget"), ("expired", "expired"),
    ("memo", "memo_mismatch"), ("issuer", "wrong_issuer"), ("partial", "partial_payment_not_allowed"),
    ("direct", "not_a_planned_purchase"),
])
def test_every_other_check_still_applies_to_a_private_site(policy, case, refused):
    service, calls = policy
    site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))
    rec = wallet_for(payees=(E,) if case == "not_allowed" else (D,))
    present = True
    rlusd_at = lambda issuer: {"currency": config.RLUSD_CURRENCY, "issuer": issuer, "value": "0.01"}
    if case == "over_budget":
        tx = signed_payment(rec, value="0.30")
    elif case == "expired":
        rec = deployments.update(rec["id"], expires_at="2020-01-01T00:00:00+00:00")
        tx = signed_payment(rec)
    elif case == "memo":
        tx = signed_payment({**rec, "id": "d_other"})
    elif case == "issuer":
        tx = signed_payment(rec, amount=rlusd_at(B))
    elif case == "partial":
        tx = signed_payment(rec, flags=0x00020000, send_max=rlusd_at(config.RLUSD_ISSUER))
    elif case == "direct":
        tx, present = signed_payment(rec), False
    else:
        tx = signed_payment(rec)
    r = service._cosign_deployment(rec, tx, present=present)
    assert r["ok"] is False and r["refused"] == refused
    assert calls == {"device": [], "submit": [], "cosign": []}


def test_the_owner_saying_no_on_the_ledger_sends_nothing(policy):
    service, calls = policy
    site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))
    rec = wallet_for(speculos_payment_decision="reject")
    r = service.cosign(service.CosignRequest(deployment_id=rec["id"], tx=signed_payment(rec), present=True))
    assert r["refused"] == "owner_rejected" and r["approval"]["reason"] == "private_site" and r["sent_transactions"] == 0
    after = deployments.get(rec["id"])
    assert after["payments"] == [] and after["refusals"][0]["refused"] == "owner_rejected"
    assert calls["cosign"] == [] and calls["submit"] == []


# ---- the delivery check ----

class _Ledger:
    def __init__(self, result="tesSUCCESS"):
        self.result = result

    def request(self, req):
        return type("R", (), {"result": {"validated": True, "meta": {"TransactionResult": self.result}}})()


def _paid_wallet(owner="u_alice", payee=E, h="HASH1"):
    rec = wallet_for(owner=owner, payees=(payee,))
    deployments.record_payment(rec["id"], {"to": payee, "amount": "0.1", "rail": "x402", "ok": True,
                                           "result": "tesSUCCESS", "hash": h, "approved_by": "ledger",
                                           "reason": "private_site", "resource": "http://localhost:8005/research/report"})
    return rec


def test_paid_not_delivered_blocks_the_owners_sites_paying_that_address(store, monkeypatch):
    from cereal import service
    monkeypatch.setattr(service, "client", lambda: _Ledger())
    sid = site_registry.add("u_alice", probe_for("http://localhost:8005/research/report", pay_to=E))["site"]["id"]
    bob_sid = site_registry.add("u_bob", probe_for("http://localhost:8005/research/report", pay_to=E))["site"]["id"]
    rec = _paid_wallet()
    r = service.report_event(rec["id"], service.EventReport(kind="paid_not_delivered", result="tesSUCCESS",
                                                            hash="HASH1", detail={"payee": "rSomeoneElse"}))
    assert r["ok"] and r["verified"] is True and r["blocked_sites"] == [sid] and r["payee"] == E
    site = site_registry.get("u_alice", sid)
    assert site["trust"] == "blocked" and site["blocked_reason"] == "paid_not_delivered"
    assert site["blocked_evidence"]["hash"] == "HASH1" and site["blocked_evidence"]["resource"].endswith("/report")
    assert site_registry.get("u_bob", bob_sid)["trust"] == "private"
    assert deployments.get(rec["id"])["payments"][0]["delivered"] is False
    (e,) = [e for e in events.feed() if e["kind"] == "paid_not_delivered"]
    assert e["by"] == "cereal" and e["proof"].endswith("/transactions/HASH1") and "1 site(s) blocked" in e["outcome"]
    assert e["why"] == events.PLAIN["paid_not_delivered"]


def test_a_report_can_only_block_an_address_the_wallet_really_paid(store, monkeypatch):
    from cereal import service
    monkeypatch.setattr(service, "client", lambda: _Ledger())
    sid = site_registry.add("u_alice", probe_for("http://localhost:8004/research/report"))["site"]["id"]
    rec = _paid_wallet()
    r = service.report_event(rec["id"], service.EventReport(kind="paid_not_delivered", result="tesSUCCESS",
                                                            hash="NOT_OURS", detail={"payee": D}))
    assert r["ok"] and r["blocked_sites"] == [] and site_registry.get("u_alice", sid)["trust"] == "private"
    assert deployments.get(rec["id"])["events"][0]["kind"] == "paid_not_delivered", "still recorded"


@pytest.mark.parametrize("ledger_says,claimed", [("tecPATH_PARTIAL", "tesSUCCESS"), ("tecPATH_PARTIAL", "tecPATH_PARTIAL"),
                                                 (None, "tesSUCCESS")])
def test_a_report_the_ledger_does_not_show_settled_blocks_nothing(store, monkeypatch, ledger_says, claimed):
    from cereal import service

    class Down:
        def request(self, req):
            raise ConnectionError("rpc down")
    monkeypatch.setattr(service, "client", lambda: _Ledger(ledger_says) if ledger_says else Down())
    sid = site_registry.add("u_alice", probe_for("http://localhost:8005/research/report", pay_to=E))["site"]["id"]
    rec = _paid_wallet()
    r = service.report_event(rec["id"], service.EventReport(kind="paid_not_delivered", result=claimed, hash="HASH1"))
    assert r["ok"] and r["blocked_sites"] == [] and "not show this payment settled" in r["note"]
    assert site_registry.get("u_alice", sid)["trust"] == "private"
    assert "delivered" not in deployments.get(rec["id"])["payments"][0]
    (e,) = [e for e in events.feed() if e["kind"] == "paid_not_delivered"]
    assert not e["what"].startswith("paid "), "the log never claims a payment the ledger did not confirm"


def test_a_wallet_without_an_owner_records_the_event_and_blocks_nothing(store, monkeypatch):
    from cereal import service
    monkeypatch.setattr(service, "client", lambda: _Ledger())
    sid = site_registry.add("u_alice", probe_for("http://localhost:8005/research/report", pay_to=E))["site"]["id"]
    rec = _paid_wallet(owner=None)
    r = service.report_event(rec["id"], service.EventReport(kind="paid_not_delivered", result="tesSUCCESS",
                                                            hash="HASH1"))
    assert r["ok"] and r["blocked_sites"] == [] and site_registry.get("u_alice", sid)["trust"] == "private"


@pytest.mark.parametrize("status,reported", [(500, True), (402, True), (200, False)])
def test_buy_reports_paid_not_delivered_with_the_validated_hash(monkeypatch, status, reported):
    from cereal import subagent
    s = subagent.Subagent.__new__(subagent.Subagent)
    s.dep_id, s.key, s.c = "d_abc123", None, None
    monkeypatch.setattr(s, "record", lambda: {"subwallet": SUB, "tag": "t" * 32})
    monkeypatch.setattr(subagent, "agent_sign", lambda tx, key, c: tx)
    body = {"x402Version": 2, "resource": {"url": "http://localhost:8005/research/report"},
            "accepts": [{"scheme": "exact", "network": "xrpl:1", "amount": "0.1", "asset": config.RLUSD_CURRENCY,
                         "payTo": E, "maxTimeoutSeconds": 600,
                         "extra": {"issuer": config.RLUSD_ISSUER, "sourceTag": 20260601,
                                   "invoiceId": "C41890F950284408AE23B14886CD273C"}}]}

    class R:
        def __init__(self, status, b=None):
            self.status_code, self._b, self.headers, self.ok = status, b or {}, {}, status < 400
            self.text = json.dumps(self._b)

        def json(self):
            return self._b
    seq = [R(402, body), R(status, {"error": "boom"})]  # a 200 here has no PAYMENT-RESPONSE header
    posts, redirects = [], []
    monkeypatch.setattr(subagent.requests, "get", lambda url, **k: redirects.append(k.get("allow_redirects")) or
                        seq.pop(0))
    monkeypatch.setattr(subagent.requests, "post", lambda url, **k: posts.append((url, k.get("json"))) or
                        R(200, {"ok": True, "hash": "H", "blob": "00"}))
    monkeypatch.setattr(subagent, "_validated", lambda c, h, wait_s=30: "tesSUCCESS")
    out = s.buy("http://localhost:8005/research/report")
    assert out["ok"] is False and out["refused"] == "paid_not_served" and out["hash"] == "H"
    assert redirects == [False, False], "a user-given site is never followed through a redirect"
    reports = [(u, j) for u, j in posts if u.endswith("/events")]
    if not reported:
        assert reports == [], "a 200 that answered is not reported as undelivered"
        return
    ((url, sent),) = reports
    assert url.endswith("/subagents/d_abc123/events")
    assert sent["kind"] == "paid_not_delivered" and sent["result"] == "tesSUCCESS" and sent["hash"] == "H"
    assert sent["detail"]["resource"] == "http://localhost:8005/research/report" and sent["detail"]["status"] == status
