"""Sites unit 1 offline tests: safe_get's SSRF guard and limits, probe's kinds, checks and verdict rules.

No network: HTTP goes through a fake transport adapter, DNS through a fake getaddrinfo, the ledger through a fake
client, credentials through a faked vendors.check. Nothing here pays or signs.
"""
from __future__ import annotations

import base64
import io
import ipaddress
import json
import socket
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict
from xrpl.core.addresscodec import is_valid_classic_address
from xrpl.models.requests import AccountInfo, AccountLines, AccountTx
from xrpl.models.response import Response as XrplResponse, ResponseStatus

from cereal import config, sites_probe as sp

RLUSD = config.RLUSD_CURRENCY
ISSUER = config.RLUSD_ISSUER
VENDOR_D = "rsV4UZG7Qsxz1QfEwRehmAc3UkkWfXaF3Z"   # honest, uncredentialed
VENDOR_E = "rPocKRfAu1fM2pZzj1TyidFaCUKLEeEHzc"   # Vendor F's payee
VENDOR_C = "r3NdoyQhgKorLo54v2VGkMrMTyPHbTXszs"   # credentialed
VENDOR_B = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"   # revoked
GHOST = "rrrrrrrrrrrrrrrrrrrrrhoLvTp"              # valid address, no account
assert all(map(is_valid_classic_address, (VENDOR_D, VENDOR_E, VENDOR_C, VENDOR_B, GHOST)))

PUBLIC_IP = "93.184.215.14"
NOW = datetime.now(timezone.utc)
OLD = NOW - timedelta(days=30)


def _hex(s: str) -> str:
    return s.encode().hex().upper()


# ---- fakes ---------------------------------------------------------------------------------------------------------

class FakeWeb(BaseAdapter):
    """routes: prepared URL → (status, headers, body) or an exception to raise. Unknown URLs answer 404."""

    def __init__(self):
        super().__init__()
        self.routes: dict = {}
        self.calls: list[requests.PreparedRequest] = []

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        self.calls.append(request)
        route = self.routes.get(request.url, (404, {"content-type": "text/plain"}, b"not found"))
        if isinstance(route, Exception):
            raise route
        status, headers, body = route
        r = requests.Response()
        raw = io.BytesIO(body) if isinstance(body, bytes) else body  # or a stream object, e.g. Drip
        r.status_code, r.headers, r.raw = status, CaseInsensitiveDict(headers), raw
        r.url, r.request, r.reason = request.url, request, "fake"
        return r

    def close(self):
        pass

    def urls(self) -> list[str]:
        return [c.url for c in self.calls]


class FakeLedger:
    """accounts: address → {"Domain"?, "line"?: dict | None, "first"?: datetime | None}. Missing address = actNotFound.
    fail: request types that raise (a dead RPC whose error text carries a secret URL)."""

    def __init__(self, accounts: dict, fail: tuple = ()):
        self.accounts, self.fail, self.calls = accounts, fail, []

    def request(self, req):
        self.calls.append(type(req).__name__)
        if self.fail and isinstance(req, self.fail):
            raise requests.exceptions.ConnectionError("https://secret.quiknode.pro/APIKEY123/ is unreachable")
        acct = self.accounts.get(req.account)
        if acct is None:
            return XrplResponse(status=ResponseStatus.ERROR, result={"error": "actNotFound"})
        if isinstance(req, AccountInfo):
            data = {"Account": req.account, "Balance": "10000000"}
            if acct.get("Domain"):
                data["Domain"] = _hex(acct["Domain"])
            return XrplResponse(status=ResponseStatus.SUCCESS, result={"account_data": data})
        if isinstance(req, AccountLines):
            line = acct.get("line", {"account": ISSUER, "currency": RLUSD, "balance": "0", "limit": "1000000"})
            return XrplResponse(status=ResponseStatus.SUCCESS, result={"lines": [line] if line else []})
        if isinstance(req, AccountTx):
            first = acct.get("first", OLD)
            txs = [{"close_time_iso": first.strftime("%Y-%m-%dT%H:%M:%SZ"), "tx_json": {}}] if first else []
            return XrplResponse(status=ResponseStatus.SUCCESS, result={"transactions": txs})
        raise AssertionError(f"unexpected ledger request {req}")


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()

    def session():
        s = requests.Session()
        s.trust_env = False
        s.mount("http://", fake)
        s.mount("https://", fake)
        return s
    monkeypatch.setattr(sp, "_session", session)
    return fake


class FakeDNS(dict):
    """host → [ip, ...]; unknown hosts fail to resolve; IP literals resolve to themselves. .asked = every lookup."""

    def __init__(self):
        super().__init__({"example.com": [PUBLIC_IP]})
        self.asked: list[str] = []

    def getaddrinfo(self, host, port, *a, **k):
        self.asked.append(host)
        try:
            ips = [str(ipaddress.ip_address(host))]
        except ValueError:
            if host not in self:
                raise socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided") from None
            ips = self[host]
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in ips]


@pytest.fixture
def dns(monkeypatch):
    fake = FakeDNS()
    monkeypatch.setattr(sp.socket, "getaddrinfo", fake.getaddrinfo)
    return fake


@pytest.fixture
def ledger(monkeypatch):
    """A ledger where Vendors D/E/C/B exist with RLUSD lines; D and E are new; D/E name localhost as their Domain."""
    accounts = {
        VENDOR_D: {"Domain": "localhost", "first": NOW - timedelta(hours=2)},
        VENDOR_E: {"Domain": "localhost", "first": NOW - timedelta(hours=2)},
        VENDOR_C: {},
        VENDOR_B: {},
    }
    fake = FakeLedger(accounts)
    creds = {VENDOR_C: {"status": "valid"},
             VENDOR_B: {"status": "revoked", "revocation": {"hash": "3FF46EE4AB", "reason": "overcharge"}}}
    monkeypatch.setattr(sp, "client", lambda: fake)
    monkeypatch.setattr(sp.vendors, "check", lambda c, addr, **k: creds.get(addr, {"status": "none"}))
    monkeypatch.setattr(config, "SITE_PRICE_CAP", "1")
    fake.creds = creds
    return fake


def x402(pay_to: str, amount: str = "0.10", *, url: str = "http://localhost:8004/research/report", header=True,
         body=True, network="xrpl:1", asset=RLUSD, issuer=ISSUER, invoice: str | None = "INV0001", scheme="exact"):
    """A v2 402 as x402_xrpl's middleware sends it: the document in PAYMENT-REQUIRED and in the body."""
    extra = {"issuer": issuer, "sourceTag": 20260601}
    if invoice:
        extra["invoiceId"] = invoice
    doc = {"x402Version": 2, "resource": {"url": url, "description": "Vendor D: report (sample data)"},
           "accepts": [{"scheme": scheme, "network": network, "amount": amount, "asset": asset, "payTo": pay_to,
                        "maxTimeoutSeconds": 600, "extra": extra}],
           "error": "PAYMENT-SIGNATURE header is required", "extensions": {}}
    headers = {"content-type": "application/json"}
    if header:
        headers["PAYMENT-REQUIRED"] = base64.b64encode(json.dumps(doc).encode()).decode()
    return 402, headers, json.dumps(doc).encode() if body else b""


def toml(*addresses: str):
    text = "".join(f'[[ACCOUNTS]]\naddress = "{a}"\ndesc = "payments"\n' for a in addresses)
    return 200, {"content-type": "text/plain; charset=utf-8"}, text.encode()


def html_page(title: str, status: int = 200, headers: dict | None = None):
    return status, {"content-type": "text/html; charset=utf-8", **(headers or {})}, \
        f"<!doctype html><html><head><title>{title}</title></head><body>hi</body></html>".encode()


D = "http://localhost:8004"


def by_name(result: dict) -> dict:
    return {c["name"]: c for c in result["checks"]}


# ---- kinds ---------------------------------------------------------------------------------------------------------

def test_free_page_is_read_with_its_title(web, dns, ledger):
    web.routes[f"{D}/free/brief"] = html_page("Vendor D: brief &amp; notes (free)")
    r = sp.probe(f"{D}/free/brief")
    assert r == {**r, "ok": True, "kind": "free", "status": 200, "title": "Vendor D: brief & notes (free)",
                 "url": f"{D}/free/brief", "origin": D, "host": "localhost", "payment": None, "accepts": [],
                 "reason": None, "credential": None, "checks": [], "verdict": "ok", "verdict_reasons": [],
                 "trust_hint": "free"}
    assert ledger.calls == [], "a free page needs no ledger read"


def test_free_json_has_no_title_and_real_sites_get_default_port_origins(web, dns, ledger):
    web.routes["https://example.com/"] = (200, {"content-type": "application/json"}, b'{"a": 1}')
    r = sp.probe("https://example.com")
    assert r["kind"] == "free" and r["title"] is None
    assert r["origin"] == "https://example.com" and r["host"] == "example.com"


def test_an_address_without_a_scheme_means_https(web, dns, ledger):
    web.routes["https://example.com/"] = html_page("Example Domain")
    r = sp.probe("  example.com  ")
    assert r["kind"] == "free" and r["title"] == "Example Domain" and r["url"] == "https://example.com/"


def test_honest_uncredentialed_site_is_payable_private_and_warns_only_because_it_is_new(web, dns, ledger):
    web.routes[f"{D}/research/report"] = x402(VENDOR_D)
    web.routes[f"{D}/.well-known/xrp-ledger.toml"] = toml(VENDOR_D)
    r = sp.probe(f"{D}/research/report")
    assert r["ok"] and r["kind"] == "payable" and r["status"] == 402 and r["reason"] is None
    assert r["payment"] == {"network": "xrpl:1", "asset": RLUSD, "issuer": ISSUER, "amount": "0.1",
                            "pay_to": VENDOR_D, "resource": f"{D}/research/report",
                            "description": "Vendor D: report (sample data)", "invoice_id": "INV0001"}
    assert r["accepts"] == [{"network": "xrpl:1", "asset": RLUSD, "amount": "0.1", "scheme": "exact",
                             "label": "RLUSD on XRPL testnet (xrpl:1)"}]
    assert [c["name"] for c in r["checks"]] == ["asset", "price", "payee_exists", "payee_rlusd", "domain_proof",
                                                 "payee_history", "credential"]
    c = by_name(r)
    assert c["price"] == {"name": "price", "ok": True, "detail": "0.1 RLUSD (cap 1)"}
    assert c["payee_exists"]["ok"] and c["payee_rlusd"]["ok"] and c["domain_proof"]["ok"] is True
    assert c["payee_history"]["ok"] is False and "created 2 hours ago" in c["payee_history"]["detail"]
    assert c["credential"]["ok"] is False and "private only" in c["credential"]["detail"]
    assert r["credential"] == "none"
    assert r["verdict"] == "warn" and r["trust_hint"] == "private"
    assert r["verdict_reasons"] == [c["payee_history"]["detail"]], "no credential is not itself a warning"
    assert r["verdict_reasons"][0].startswith("The address is new: created 2 hours ago")


def test_an_old_honest_site_with_everything_proven_is_ok(web, dns, ledger):
    ledger.accounts[VENDOR_D]["first"] = OLD
    web.routes[f"{D}/research/report"] = x402(VENDOR_D)
    web.routes[f"{D}/.well-known/xrp-ledger.toml"] = toml(VENDOR_D)
    r = sp.probe(f"{D}/research/report")
    assert r["verdict"] == "ok" and r["verdict_reasons"] == [] and r["trust_hint"] == "private"
    assert by_name(r)["payee_history"]["ok"] is True


def test_credentialed_payee_is_public(web, dns, ledger):
    web.routes["http://localhost:8003/swell/agenda"] = x402(VENDOR_C, "0.15", url="http://localhost:8003/swell/agenda")
    r = sp.probe("http://localhost:8003/swell/agenda")
    assert r["kind"] == "payable" and r["credential"] == "valid" and by_name(r)["credential"]["ok"] is True
    assert r["trust_hint"] == "public"
    # no toml and no Domain: cereal cannot link the address to the site, which warns but does not block
    assert by_name(r)["domain_proof"]["ok"] is None and r["verdict"] == "warn"


def test_revoked_payee_is_blocked_with_the_evidence(web, dns, ledger):
    web.routes["http://localhost:8002/swell/agenda"] = x402(VENDOR_B, "0.05", url="http://localhost:8002/swell/agenda")
    r = sp.probe("http://localhost:8002/swell/agenda")
    assert r["credential"] == "revoked" and r["verdict"] == "block" and r["trust_hint"] == "blocked"
    detail = by_name(r)["credential"]["detail"]
    assert "revoked" in detail and "overcharge" in detail and "3FF46EE4AB" in detail
    assert r["verdict_reasons"][0] == detail


def test_usdc_only_paywall_is_unpayable_and_says_what_it_wants(web, dns, ledger):
    body = {"x402Version": 2, "error": "payment required", "accepts": [{
        "scheme": "exact", "network": "eip155:84532", "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        "amount": "100000", "payTo": "0x000000000000000000000000000000000000dEaD", "maxTimeoutSeconds": 60,
        "extra": {"name": "USDC", "version": "2"}}], "resource": {"url": "/usdc/report"}}
    web.routes[f"{D}/usdc/report"] = (402, {"content-type": "application/json"}, json.dumps(body).encode())
    r = sp.probe(f"{D}/usdc/report")
    assert r["ok"] and r["kind"] == "unpayable" and r["payment"] is None and r["checks"] == []
    assert "USDC on Base Sepolia (eip155:84532)" in r["reason"]
    assert r["accepts"][0]["label"] == "USDC on Base Sepolia (eip155:84532)" and r["accepts"][0]["amount"] == "100000"
    assert r["verdict"] == "block" and r["verdict_reasons"] == [r["reason"]] and r["trust_hint"] == "none"
    assert ledger.calls == []


@pytest.mark.parametrize("kw, words", [
    ({"issuer": "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"}, "names issuer rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"),
    ({"scheme": "upto"}, "upto scheme"),
    ({"invoice": None}, "no invoiceId"),
])
def test_an_rlusd_option_cereal_still_cannot_pay_is_explained(web, dns, ledger, kw, words):
    web.routes[f"{D}/research/report"] = x402(VENDOR_D, **kw)
    r = sp.probe(f"{D}/research/report")
    assert r["kind"] == "unpayable" and words in r["reason"]


def test_xrp_and_mainnet_options_are_unpayable(web, dns, ledger):
    web.routes[f"{D}/research/report"] = x402(VENDOR_D, network="xrpl:0")
    r = sp.probe(f"{D}/research/report")
    assert r["kind"] == "unpayable" and "XRPL mainnet (xrpl:0)" in r["reason"]
    web.routes[f"{D}/research/report"] = x402(VENDOR_D, asset="XRP")
    assert "XRP on XRPL testnet (xrpl:1)" in sp.probe(f"{D}/research/report")["reason"]


def test_a_402_without_x402_options_is_unpayable(web, dns, ledger):
    web.routes[f"{D}/x"] = (402, {"content-type": "text/html"}, b"<html>subscribe!</html>")
    r = sp.probe(f"{D}/x")
    assert r["kind"] == "unpayable" and "no x402 payment options" in r["reason"]


def test_v2_header_only_402_is_payable(web, dns, ledger):
    web.routes[f"{D}/research/report"] = x402(VENDOR_D, body=False)
    r = sp.probe(f"{D}/research/report")
    assert r["kind"] == "payable" and r["payment"]["pay_to"] == VENDOR_D


def test_v2_body_only_402_is_payable(web, dns, ledger):
    web.routes[f"{D}/research/report"] = x402(VENDOR_D, header=False)
    assert sp.probe(f"{D}/research/report")["kind"] == "payable"


def test_v1_body_with_max_amount_required_is_payable(web, dns, ledger):
    body = {"x402Version": 1, "error": "X-PAYMENT header is required", "accepts": [
        {"scheme": "exact", "network": "eip155:84532", "maxAmountRequired": "10000", "asset": "0xabc",
         "payTo": "0xdead", "maxTimeoutSeconds": 60, "resource": f"{D}/v1", "description": "usdc"},
        {"scheme": "exact", "network": "xrpl:1", "maxAmountRequired": "0.250", "asset": RLUSD, "payTo": VENDOR_D,
         "maxTimeoutSeconds": 60, "resource": f"{D}/v1", "description": "v1 report", "mimeType": "application/json",
         "extra": {"issuer": ISSUER, "invoiceId": "V1INV"}}]}
    web.routes[f"{D}/v1"] = (402, {"content-type": "application/json"}, json.dumps(body).encode())
    r = sp.probe(f"{D}/v1")
    assert r["kind"] == "payable"
    assert r["payment"]["amount"] == "0.25" and r["payment"]["resource"] == f"{D}/v1"
    assert r["payment"]["description"] == "v1 report" and r["payment"]["invoice_id"] == "V1INV"
    assert [a["network"] for a in r["accepts"]] == ["eip155:84532", "xrpl:1"]


def test_an_option_whose_extra_is_not_an_object_is_skipped_not_a_crash(web, dns, ledger):
    status, headers, body = x402(VENDOR_D, header=False)
    doc = json.loads(body)
    doc["accepts"].insert(0, {**doc["accepts"][0], "extra": "abc"})
    web.routes[f"{D}/research/report"] = (402, headers, json.dumps(doc).encode())
    r = sp.probe(f"{D}/research/report")
    assert r["kind"] == "payable" and r["payment"]["invoice_id"] == "INV0001" and len(r["accepts"]) == 2
    doc["accepts"] = doc["accepts"][:1]
    web.routes[f"{D}/research/report"] = (402, headers, json.dumps(doc).encode())
    assert sp.probe(f"{D}/research/report")["kind"] == "unpayable"


def test_deeply_nested_json_in_a_402_is_unpayable_not_a_crash(web, dns, ledger):
    nested = b"[" * 200_000
    web.routes[f"{D}/x"] = (402, {"content-type": "application/json",
                                  "PAYMENT-REQUIRED": base64.b64encode(b"[" * 100_000).decode()}, nested)
    r = sp.probe(f"{D}/x")
    assert r["ok"] and r["kind"] == "unpayable"


def test_a_deeply_nested_toml_is_no_proof_not_a_crash(web, dns, ledger):
    r = _site(web, toml_route=(200, {}, b"a=" + b"[" * 30_000))
    assert r["ok"] and by_name(r)["domain_proof"]["ok"] is None
    assert "not valid TOML" in by_name(r)["domain_proof"]["detail"]


def test_a_huge_exponent_amount_stays_short(web, dns, ledger):
    r = _site(web, amount="1e999999", toml_route=toml(VENDOR_D))
    assert len(json.dumps(r)) < 10_000
    assert r["payment"]["amount"] == "1e999999" and by_name(r)["price"]["ok"] is False and r["verdict"] == "block"


def test_a_page_of_unclosed_title_tags_is_fast(web, dns, ledger):
    web.routes["https://example.com/"] = (200, {"content-type": "text/html"}, b"<title>" * 70_000)
    started = time.monotonic()
    r = sp.probe("https://example.com/")
    assert r["kind"] == "free" and r["title"] is None and time.monotonic() - started < 2


def test_a_title_is_found_and_bounded(web, dns, ledger):
    web.routes["https://example.com/"] = html_page("  Spaced\n  out   " + "x" * 500)
    t = sp.probe("https://example.com/")["title"]
    assert t.startswith("Spaced out xxx") and len(t) == 200 and t.endswith("…")


@pytest.mark.parametrize("status, headers, body, words", [
    (401, {}, b"login", "401: it needs a login"),
    (403, {}, b"forbidden", "403"),
    (404, {}, b"nope", "404"),
    (429, {}, b"slow down", "429"),
    (500, {}, b"boom", "500: a server error"),
    (503, {"cf-mitigated": "challenge"}, b"Just a moment...", "captcha"),
    (403, {}, b"<div class='g-recaptcha'>please solve this captcha</div>", "captcha"),
])
def test_other_answers_are_unreachable_with_why(web, dns, ledger, status, headers, body, words):
    web.routes["https://example.com/page"] = (status, {"content-type": "text/html", **headers}, body)
    r = sp.probe("https://example.com/page")
    assert r["ok"] and r["kind"] == "unreachable" and r["status"] == status and words in r["reason"]
    assert r["verdict"] == "block" and r["verdict_reasons"] == [r["reason"]] and r["trust_hint"] == "none"


def test_a_200_cloudflare_challenge_is_unreachable(web, dns, ledger):
    web.routes["https://example.com/"] = html_page("Just a moment...", headers={"cf-mitigated": "challenge"})
    assert sp.probe("https://example.com/")["kind"] == "unreachable"


@pytest.mark.parametrize("exc, words", [
    (requests.exceptions.ConnectTimeout("timed out"), "did not answer within"),
    (requests.exceptions.ReadTimeout("read timed out"), "did not answer within"),
    (requests.exceptions.SSLError("bad cert"), "TLS certificate"),
    (requests.exceptions.ConnectionError("refused"), "Could not connect"),
])
def test_network_failures_are_unreachable(web, dns, ledger, exc, words):
    web.routes["https://example.com/"] = exc
    r = sp.probe("https://example.com/")
    assert r["kind"] == "unreachable" and r["status"] is None and words in r["reason"]


def test_dns_failure_is_unreachable(web, dns, ledger):
    r = sp.probe("https://no-such-host.invalid/x")
    assert r["kind"] == "unreachable" and "DNS lookup failed" in r["reason"] and web.calls == []


# ---- refusals and the SSRF guard -----------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [None, "", "   ", 123, ["http://x"], "http://", "http://exa mple.com/",
                                 "http://localhost:99999/", "http://[::1/", "https://" + "a" * 3000 + ".com"])
def test_malformed_input_is_an_invalid_url_refusal(web, dns, ledger, url):
    r = sp.probe(url)
    assert r["ok"] is False and r["refused"] == "invalid_url" and r["reason"]
    assert web.calls == []


@pytest.mark.parametrize("url, words", [
    ("http://127.0.0.1:8001/main", "loopback"),
    ("http://169.254.169.254/latest/meta-data", "link-local"),
    ("http://10.0.0.5/admin", "private"),
    ("http://192.168.1.1/", "private"),
    ("http://[::1]:8001/main", "loopback"),
    ("http://[::ffff:127.0.0.1]/", "loopback"),
    ("http://0.0.0.0:8001/", "unspecified"),
    ("http://100.64.0.1/", "non-public"),
    ("http://224.0.0.1/", "multicast"),
    ("http://localhost:8001/main", "loopback"),          # not an allowed origin: the demo service stays private
    ("file:///etc/passwd", "only opens http"),
    ("ftp://example.com/x", "only opens http"),
    ("javascript:alert(1)", "only opens http"),
    ("http://user:pw@example.com/", "user name or password"),
])
def test_private_local_and_non_web_addresses_are_unsafe(web, dns, ledger, url, words):
    dns["localhost"] = ["127.0.0.1", "::1"]
    r = sp.probe(url)
    assert r["ok"] is False and r["refused"] == "unsafe_url" and words in r["reason"], r
    assert web.calls == [], "nothing is fetched"


def test_a_name_that_resolves_to_any_private_address_is_unsafe(web, dns, ledger):
    dns["rebind.example"] = [PUBLIC_IP, "10.1.2.3"]
    r = sp.probe("https://rebind.example/")
    assert r["refused"] == "unsafe_url" and "10.1.2.3" in r["reason"] and web.calls == []


def test_allowed_origins_are_fetched_without_the_address_check(web, dns, ledger):
    dns["localhost"] = ["127.0.0.1"]
    web.routes[f"{D}/free/a"] = html_page("ok")
    assert sp.probe(f"{D}/free/a")["kind"] == "free"
    assert "localhost" not in dns.asked, "an allowed origin is not resolved or checked"


def test_a_redirect_to_localhost_is_refused_before_it_is_followed(web, dns, ledger):
    dns["localhost"] = ["127.0.0.1"]
    web.routes["https://example.com/go"] = (302, {"location": "http://localhost:8001/main"}, b"")
    r = sp.probe("https://example.com/go")
    assert r["refused"] == "unsafe_url" and "loopback" in r["reason"]
    assert web.urls() == ["https://example.com/go"]


def test_a_redirect_to_metadata_by_ip_is_refused(web, dns, ledger):
    web.routes["https://example.com/go"] = (301, {"location": "http://169.254.169.254/latest/meta-data"}, b"")
    r = sp.probe("https://example.com/go")
    assert r["refused"] == "unsafe_url" and "link-local" in r["reason"]


def test_a_redirect_to_file_is_refused(web, dns, ledger):
    web.routes["https://example.com/go"] = (302, {"location": "file:///etc/passwd"}, b"")
    r = sp.probe("https://example.com/go")
    assert r["refused"] == "unsafe_url" and "only opens http" in r["reason"]


def test_an_allowed_origin_cannot_redirect_to_a_private_one(web, dns, ledger):
    dns["localhost"] = ["127.0.0.1"]
    web.routes[f"{D}/hop"] = (307, {"location": "http://localhost:8001/main"}, b"")
    r = sp.probe(f"{D}/hop")
    assert r["refused"] == "unsafe_url" and web.urls() == [f"{D}/hop"]


def test_public_redirects_are_followed_and_the_final_page_is_what_is_probed(web, dns, ledger):
    web.routes["http://example.com/"] = (301, {"location": "https://example.com/"}, b"")
    web.routes["https://example.com/"] = (302, {"location": "/home"}, b"")
    web.routes["https://example.com/home"] = html_page("Home")
    r = sp.probe("http://example.com/")
    assert r["kind"] == "free" and r["title"] == "Home" and r["url"] == "https://example.com/home"
    assert r["origin"] == "https://example.com"


def test_more_than_three_redirects_is_refused_by_safe_get_and_unreachable_for_probe(web, dns, ledger):
    for i in range(5):
        web.routes[f"https://example.com/{i}"] = (302, {"location": f"/{i + 1}"}, b"")
    with pytest.raises(sp.UnsafeURL, match="more than 3"):
        sp.safe_get("https://example.com/0")
    assert len(web.calls) == 4
    r = sp.probe("https://example.com/0")
    assert r["ok"] and r["kind"] == "unreachable" and "more than 3" in r["reason"]


def test_a_redirect_with_an_unreadable_location_is_unreachable(web, dns, ledger):
    web.routes["https://example.com/go"] = (302, {"location": "https://example.com:99999/x"}, b"")
    r = sp.probe("https://example.com/go")
    assert r["kind"] == "unreachable" and "cannot read" in r["reason"]


def test_unicode_hosts_are_checked_under_the_name_requests_connects_to(web, dns, ledger):
    """IDNA 2003 (getaddrinfo) maps ß to ss; requests uses UTS46 (xn--strae-oqa). The guard must resolve the latter."""
    dns["strasse.example"] = [PUBLIC_IP]
    dns["xn--strae-oqa.example"] = ["169.254.169.254"]
    r = sp.probe("https://straße.example/")
    assert r["refused"] == "unsafe_url" and "169.254.169.254" in r["reason"] and web.calls == []
    assert "xn--strae-oqa.example" in dns.asked and "strasse.example" not in dns.asked


def test_a_bare_local_merchant_address_means_its_http_origin(web, dns, ledger):
    web.routes[f"{D}/free/brief"] = html_page("Brief")
    r = sp.probe("localhost:8004/free/brief")
    assert r["kind"] == "free" and r["url"] == f"{D}/free/brief"
    dns["localhost"] = ["127.0.0.1"]
    assert sp.probe("localhost:8001/main")["refused"] == "unsafe_url", "a bare non-merchant port stays refused"


def test_a_long_unicode_path_that_requests_percent_encodes_still_probes(web, dns, ledger):
    url = "https://example.com/" + "é" * 1000
    encoded = requests.Request("GET", url).prepare().url
    assert len(encoded) > sp.MAX_URL_LENGTH
    web.routes[encoded] = html_page("Long")
    r = sp.probe(url)
    assert r["kind"] == "free" and r["title"] == "Long" and r["host"] == "example.com"
    assert r["url"] == encoded and sp.safe_get(r["url"]).status_code == 200, "the stored URL can be fetched again"


def test_safe_get_raises_unsafe_url_itself(web, dns):
    with pytest.raises(sp.UnsafeURL, match="loopback"):
        sp.safe_get("http://127.0.0.1:8001/main")
    with pytest.raises(sp.UnsafeURL, match="only opens http"):
        sp.safe_get("file:///etc/passwd")
    with pytest.raises(sp.UnsafeURL):
        sp.safe_get("http://")


def test_safe_get_sends_its_user_agent_and_drops_credentials_on_cross_origin_redirects(web, dns):
    dns["other.example"] = [PUBLIC_IP]
    web.routes["https://example.com/a"] = (302, {"location": "https://example.com/b"}, b"")
    web.routes["https://example.com/b"] = (302, {"location": "https://other.example/c"}, b"")
    web.routes["https://other.example/c"] = (200, {"content-type": "text/plain"}, b"done")
    r = sp.safe_get("https://example.com/a", headers={"Authorization": "Bearer t", "User-Agent": "spoof",
                                                       "Accept": "text/html"})
    assert r.content == b"done" and len(r.history) == 2 and r.url == "https://other.example/c"
    a, b, c = web.calls
    assert a.headers["User-Agent"] == "cereal-sites/1" and b.headers["User-Agent"] == "cereal-sites/1"
    assert a.headers["Authorization"] == "Bearer t" and b.headers["Authorization"] == "Bearer t"
    assert "Authorization" not in c.headers and c.headers["Accept"] == "text/html"


def test_safe_get_stops_reading_at_max_bytes(web, dns):
    web.routes["https://example.com/big"] = (200, {"content-type": "text/plain"}, b"x" * 100_000)
    r = sp.safe_get("https://example.com/big", max_bytes=1000)
    assert len(r.content) == 1000 and r.truncated is True
    web.routes["https://example.com/exact"] = (200, {"content-type": "text/plain"}, b"y" * 1000)
    r = sp.safe_get("https://example.com/exact", max_bytes=1000)
    assert len(r.content) == 1000 and r.truncated is False


class Drip(io.RawIOBase):
    """A body that never ends: one byte every 50 ms (a slowloris site)."""

    def readable(self):
        return True

    def readinto(self, b):
        time.sleep(0.05)
        b[:1] = b"z"
        return 1


def test_safe_get_has_a_total_deadline(web, dns):
    web.routes["https://example.com/drip"] = (200, {"content-type": "text/plain"}, Drip())
    started = time.monotonic()
    with pytest.raises(requests.exceptions.Timeout):
        sp.safe_get("https://example.com/drip", timeout=0.3)
    assert time.monotonic() - started < 2


def test_a_dripping_site_is_unreachable(web, dns, ledger, monkeypatch):
    monkeypatch.setattr(sp, "PROBE_TIMEOUT", 0.3)
    web.routes["https://example.com/drip"] = (200, {"content-type": "text/plain"}, Drip())
    r = sp.probe("https://example.com/drip")
    assert r["kind"] == "unreachable" and "did not answer within 0.3 seconds" in r["reason"]


def test_safe_get_ignores_proxies_and_netrc_from_the_environment():
    assert sp._session().trust_env is False


# ---- each check's outcomes -----------------------------------------------------------------------------------------

def _site(web, pay_to=VENDOR_D, amount="0.10", toml_route=None):
    web.routes[f"{D}/research/report"] = x402(pay_to, amount)
    if toml_route is not None:
        web.routes[f"{D}/.well-known/xrp-ledger.toml"] = toml_route
    return sp.probe(f"{D}/research/report")


def test_price_above_the_cap_blocks_and_the_cap_itself_passes(web, dns, ledger):
    r = _site(web, amount="2.50", toml_route=toml(VENDOR_D))
    assert by_name(r)["price"]["ok"] is False and r["verdict"] == "block" and r["trust_hint"] == "blocked"
    assert "2.5 RLUSD, is above the 1 RLUSD cap" in r["verdict_reasons"][0]
    r = _site(web, amount="1", toml_route=toml(VENDOR_D))
    assert by_name(r)["price"] == {"name": "price", "ok": True, "detail": "1 RLUSD (cap 1)"}


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "abc"])
def test_a_price_that_is_not_positive_blocks(web, dns, ledger, amount):
    r = _site(web, amount=amount, toml_route=toml(VENDOR_D))
    assert by_name(r)["price"]["ok"] is False and r["verdict"] == "block"


def test_a_payee_that_does_not_exist_blocks(web, dns, ledger):
    r = _site(web, pay_to=GHOST)
    c = by_name(r)
    assert c["payee_exists"]["ok"] is False and "does not exist" in c["payee_exists"]["detail"]
    assert c["payee_rlusd"]["ok"] is False and c["payee_history"]["ok"] is False
    assert r["verdict"] == "block" and r["trust_hint"] == "blocked"
    assert "AccountLines" not in ledger.calls, "a missing account is not asked for trust lines"


def test_an_invalid_payee_address_blocks_without_asking_the_ledger(web, dns, ledger):
    r = _site(web, pay_to="rNotAnAddress")
    assert by_name(r)["payee_exists"]["ok"] is False and "not a valid XRPL address" in by_name(r)["payee_exists"]["detail"]
    assert r["verdict"] == "block" and ledger.calls == []


@pytest.mark.parametrize("line, words", [
    (None, "no RLUSD trust line"),
    ({"account": ISSUER, "currency": RLUSD, "balance": "0", "limit": "0"}, "full"),
    ({"account": ISSUER, "currency": RLUSD, "balance": "99.95", "limit": "100"}, "full"),
    ({"account": ISSUER, "currency": RLUSD, "balance": "0", "limit": "100", "freeze_peer": True}, "froze"),
    ({"account": "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay", "currency": RLUSD, "balance": "0", "limit": "9"}, "no RLUSD"),
])
def test_a_payee_that_cannot_receive_rlusd_blocks(web, dns, ledger, line, words):
    ledger.accounts[VENDOR_D]["line"] = line
    r = _site(web, toml_route=toml(VENDOR_D))
    assert by_name(r)["payee_rlusd"]["ok"] is False and words in by_name(r)["payee_rlusd"]["detail"]
    assert r["verdict"] == "block"


def test_domain_proof_payment_redirected_by_the_toml_blocks(web, dns, ledger):
    """Vendor F: pays E's address, but its toml lists D's."""
    web.routes["http://localhost:8006/research/report"] = x402(VENDOR_E, url="http://localhost:8006/research/report")
    web.routes["http://localhost:8006/.well-known/xrp-ledger.toml"] = toml(VENDOR_D)
    r = sp.probe("http://localhost:8006/research/report")
    c = by_name(r)["domain_proof"]
    assert c["ok"] is False and VENDOR_D in c["detail"] and f"but not {VENDOR_E}" in c["detail"]
    assert r["verdict"] == "block" and r["trust_hint"] == "blocked" and r["verdict_reasons"][0] == c["detail"]


def test_domain_proof_an_account_naming_another_host_blocks(web, dns, ledger):
    ledger.accounts[VENDOR_D]["Domain"] = "evil.example"
    r = _site(web, toml_route=toml(VENDOR_D))
    c = by_name(r)["domain_proof"]
    assert c["ok"] is False and "belongs to evil.example, not localhost" in c["detail"] and r["verdict"] == "block"


@pytest.mark.parametrize("domain, toml_route, words", [
    (None, None, "There is no xrp-ledger.toml"),
    ("localhost", None, "does not confirm it"),
    (None, toml(VENDOR_D), "names no domain"),
    ("localhost", (200, {"content-type": "text/html"}, b"<html>catch-all SPA</html>"), "not valid TOML"),
    ("localhost", (200, {}, b'title = "no accounts here"\n'), "lists no accounts"),
    ("localhost", (500, {}, b"down"), "There is no xrp-ledger.toml"),
])
def test_domain_proof_that_cannot_be_made_warns(web, dns, ledger, domain, toml_route, words):
    ledger.accounts[VENDOR_D]["Domain"] = domain
    ledger.accounts[VENDOR_D]["first"] = OLD
    r = _site(web, toml_route=toml_route)
    c = by_name(r)["domain_proof"]
    assert c["ok"] is None and words in c["detail"]
    assert r["verdict"] == "warn" and r["verdict_reasons"] == [c["detail"]] and r["trust_hint"] == "private"


def test_domain_proof_toml_is_fetched_through_the_guard(web, dns, ledger, monkeypatch):
    """A site whose toml redirects to a private address gets no proof (and cereal never fetches it)."""
    dns["localhost"] = ["127.0.0.1"]
    web.routes[f"{D}/.well-known/xrp-ledger.toml"] = (302, {"location": "http://10.0.0.7/x.toml"}, b"")
    r = _site(web)
    assert by_name(r)["domain_proof"]["ok"] is None and "Could not fetch" in by_name(r)["domain_proof"]["detail"]
    assert "http://10.0.0.7/x.toml" not in web.urls()


def test_payee_history_with_no_transactions_warns(web, dns, ledger):
    ledger.accounts[VENDOR_D]["first"] = None
    r = _site(web, toml_route=toml(VENDOR_D))
    assert by_name(r)["payee_history"] == {"name": "payee_history", "ok": False,
                                           "detail": f"{VENDOR_D} has no transactions on record."}
    assert r["verdict"] == "warn"


@pytest.mark.parametrize("fail", [(AccountInfo,), (AccountLines,), (AccountTx,), (AccountInfo, AccountLines, AccountTx)])
def test_ledger_errors_become_null_checks_never_crashes_or_leaked_urls(web, dns, ledger, fail):
    ledger.fail = fail
    r = _site(web, toml_route=toml(VENDOR_D))
    assert r["ok"] and r["kind"] == "payable"
    nulls = {c["name"] for c in r["checks"] if c["ok"] is None}
    if AccountInfo in fail:
        assert {"payee_exists", "payee_rlusd", "domain_proof", "payee_history"} <= nulls
    if AccountLines in fail:
        assert "payee_rlusd" in nulls
    if AccountTx in fail:
        assert "payee_history" in nulls
    assert r["verdict"] == "warn" and r["trust_hint"] == "private"
    assert "APIKEY123" not in json.dumps(r) and "quiknode" not in json.dumps(r)


def test_a_credential_read_error_warns_and_is_never_public(web, dns, ledger, monkeypatch):
    def boom(c, addr, **k):
        raise RuntimeError("CREDENTIAL_ISSUER_SEED missing in .env")
    monkeypatch.setattr(sp.vendors, "check", boom)
    web.routes["http://localhost:8003/swell/agenda"] = x402(VENDOR_C, url="http://localhost:8003/swell/agenda")
    r = sp.probe("http://localhost:8003/swell/agenda")
    assert by_name(r)["credential"]["ok"] is None and r["credential"] is None
    assert r["verdict"] == "warn" and r["trust_hint"] == "private"
    assert "SEED" not in json.dumps(r)


@pytest.mark.parametrize("status, words", [("pending", "not accepted"), ("expired", "expired")])
def test_pending_or_expired_credentials_are_private_only_not_failures(web, dns, ledger, status, words):
    ledger.creds[VENDOR_D] = {"status": status}
    ledger.accounts[VENDOR_D]["first"] = OLD
    r = _site(web, toml_route=toml(VENDOR_D))
    assert by_name(r)["credential"]["ok"] is False and words in by_name(r)["credential"]["detail"]
    assert r["verdict"] == "ok" and r["trust_hint"] == "private" and r["credential"] == status


def test_a_valid_credential_does_not_override_a_block(web, dns, ledger):
    web.routes["http://localhost:8003/swell/agenda"] = x402(VENDOR_C, "5", url="http://localhost:8003/swell/agenda")
    r = sp.probe("http://localhost:8003/swell/agenda")
    assert r["credential"] == "valid" and r["verdict"] == "block" and r["trust_hint"] == "blocked"


# ---- the verdict rules ---------------------------------------------------------------------------------------------

def _c(name, ok, detail=None):
    return {"name": name, "ok": ok, "detail": detail or f"{name}:{ok}"}


def test_verdict_rules():
    v = sp._verdict
    allok = [_c(n, True) for n in ("asset", "price", "payee_exists", "payee_rlusd", "domain_proof", "payee_history")]
    assert v(allok + [_c("credential", True)], "valid") == ("ok", [])
    assert v(allok + [_c("credential", False)], "none") == ("ok", []), "no credential: private only, not a warning"
    assert v(allok[:-1] + [_c("payee_history", False), _c("credential", False)], "none") == ("warn", ["payee_history:False"])
    assert v(allok[:4] + [_c("domain_proof", None)] + allok[5:], "none") == ("warn", ["domain_proof:None"])
    assert v(allok + [_c("credential", None)], None) == ("warn", ["credential:None"])
    assert v(allok + [_c("credential", False)], "revoked") == ("block", ["credential:False"])
    for name in ("price", "payee_exists", "payee_rlusd", "domain_proof"):
        checks = [c if c["name"] != name else _c(name, False) for c in allok] + [_c("credential", False)]
        assert v(checks, "none") == ("block", [f"{name}:False"])
    mixed = [_c("price", False), _c("payee_history", False), _c("domain_proof", None), _c("credential", False)]
    assert v(mixed, "revoked") == ("block", ["price:False", "credential:False", "payee_history:False", "domain_proof:None"])


# ---- the route -----------------------------------------------------------------------------------------------------

@pytest.fixture
def http(web, dns, ledger):
    from fastapi.testclient import TestClient
    from cereal import service
    return TestClient(service.app)


def test_route_returns_the_probe(http, web):
    web.routes[f"{D}/free/brief"] = html_page("Brief")
    r = http.post("/sites/probe", json={"url": f"{D}/free/brief"})
    assert r.status_code == 200 and r.json()["kind"] == "free" and r.json()["title"] == "Brief"


def test_route_accepts_a_form_encoded_json_body_like_curl_d(http, web):
    web.routes[f"{D}/free/brief"] = html_page("Brief")
    r = http.post("/sites/probe", content=json.dumps({"url": f"{D}/free/brief"}),
                  headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and r.json()["kind"] == "free"


@pytest.mark.parametrize("kw", [{"json": {}}, {"json": {"url": 5}}, {"json": ["x"]}, {"content": b"not json"},
                                {"content": b""}, {"json": {"url": None}}])
def test_route_turns_bad_input_into_a_refusal_not_an_http_error(http, kw):
    r = http.post("/sites/probe", **kw)
    assert r.status_code == 200 and r.json() == {**r.json(), "ok": False, "refused": "invalid_url"}


def test_route_refuses_unsafe_urls(http, web):
    r = http.post("/sites/probe", json={"url": "http://169.254.169.254/latest/meta-data"})
    assert r.status_code == 200 and r.json()["refused"] == "unsafe_url" and web.calls == []
