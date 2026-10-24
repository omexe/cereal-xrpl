"""Part 4 unit tests: the x402 rail without the network (the co-signer's present mode, policy, the subagent's buy)."""
from decimal import Decimal

import pytest
from xrpl.models.transactions import Payment

from cereal import config, deployments
from cereal.ledger import rlusd

SUB = "rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR"
VENDOR = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"
INV = "C41890F950284408AE23B14886CD273C"


def accepts(asset=config.RLUSD_CURRENCY, issuer=config.RLUSD_ISSUER, amount="0.25", network="xrpl:1"):
    return {"x402Version": 2, "resource": {"url": "http://v/swell/agenda"},
            "accepts": [{"scheme": "exact", "network": network, "amount": amount, "asset": asset, "payTo": VENDOR,
                         "maxTimeoutSeconds": 600, "extra": {"issuer": issuer, "sourceTag": 20260601, "invoiceId": INV}}]}


@pytest.fixture
def svc(tmp_path, monkeypatch):
    from cereal import service
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)
    monkeypatch.setattr(service, "client", lambda: object())
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: Decimal("1"))
    d = deployments.create("t", "1", [VENDOR])
    rec = deployments.update(d["id"], status="active", subwallet=SUB)
    return service, rec, monkeypatch


def _x402_tx(rec, **over):
    from x402_xrpl.types import PaymentRequirements
    from cereal.pay import build_x402_payment
    req = PaymentRequirements.from_dict(accepts()["accepts"][0])
    d = build_x402_payment(SUB, req, rec["id"], rec["tag"]).to_xrpl()
    d.update(over)
    return d


def test_pick_rlusd_requirement_only_takes_testnet_rlusd_exact():
    from cereal.pay import pick_rlusd_requirement
    assert pick_rlusd_requirement(accepts()).pay_to == VENDOR
    assert pick_rlusd_requirement(accepts(asset="XRP")) is None
    assert pick_rlusd_requirement(accepts(asset="RLUSD")) is None, "the facilitator rejects the symbol; only 40-hex"
    assert pick_rlusd_requirement(accepts(issuer="rFAKEissuer")) is None, "a look-alike RLUSD from another issuer"
    assert pick_rlusd_requirement(accepts(network="xrpl:0")) is None, "never mainnet"


def test_x402_payment_carries_cereal_memo_first_and_binds_the_invoice():
    from cereal.ledger import decode_memos
    rec = {"id": "d_abc123", "tag": "t" * 32}
    tx = _x402_tx(rec)
    memos = decode_memos(tx)
    assert memos[0]["job"] == "d_abc123" and memos[0]["kind"] == "pay" and memos[0]["rail"] == "x402"
    assert bytes.fromhex(tx["Memos"][1]["Memo"]["MemoData"]).decode() == INV
    assert tx["SendMax"] == tx["Amount"] and tx["SourceTag"] == 20260601 and len(tx["InvoiceID"]) == 64


def test_present_mode_cosigns_without_submitting_and_records_presented(svc):
    service, rec, mp = svc
    submitted = []
    mp.setattr(service, "cosign_and_submit", lambda *a, **k: submitted.append(a) or {"ok": True})

    class Combined:
        def get_hash(self): return "ABC"
        def blob(self): return "BLOB"
    mp.setattr(service, "cosign_combine", lambda tx, w: Combined())
    mp.setattr(config, "wallet", lambda role: None)
    r = service._cosign_deployment(rec, _x402_tx(rec), present=True, resource="http://v/swell/agenda")
    assert r == {"ok": True, "presented": True, "hash": "ABC", "blob": "BLOB"}
    assert submitted == [], "x402: the vendor's facilitator submits, not cereal"
    p = deployments.get(rec["id"])["payments"][0]
    assert p["rail"] == "x402" and p["result"] == "presented" and p["resource"] == "http://v/swell/agenda"


@pytest.mark.parametrize("over,reason", [
    ({"Flags": 0x00020000}, "partial_payment_not_allowed"),
    ({"Paths": [[{"currency": "XRP"}]]}, "paths_not_allowed"),
    ({"SendMax": {"currency": config.RLUSD_CURRENCY, "issuer": config.RLUSD_ISSUER, "value": "5"}}, "send_max_not_allowed"),
    ({"SendMax": "1000000"}, "send_max_not_allowed"),
])
def test_policy_refuses_anything_but_a_plain_exact_rlusd_payment(svc, over, reason):
    service, rec, mp = svc
    mp.setattr(service, "cosign_combine", lambda *a: pytest.fail("must refuse before signing"))
    r = service._cosign_deployment(rec, _x402_tx(rec, **over), present=True)
    assert r["refused"] == reason


def test_presented_payment_is_resolved_from_the_ledger(svc):
    service, rec, mp = svc
    deployments.record_payment(rec["id"], {"to": VENDOR, "amount": "0.25", "rail": "x402", "result": "presented",
                                           "ok": None, "hash": "H1"})

    class C:
        def request(self, req):
            return type("R", (), {"result": {"validated": True, "meta": {"TransactionResult": "tesSUCCESS"}}})()
    mp.setattr(service, "client", lambda: C())
    p = service._resolve_presented(deployments.get(rec["id"]))["payments"][0]
    assert p["result"] == "tesSUCCESS" and p["ok"] is True


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.ok = status < 400

    def json(self):
        return self._body


@pytest.fixture
def sub(monkeypatch):
    from cereal import subagent
    s = subagent.Subagent.__new__(subagent.Subagent)
    s.dep_id, s.key, s.c = "d_abc123", None, None
    monkeypatch.setattr(s, "record", lambda: {"subwallet": SUB, "tag": "t" * 32})
    monkeypatch.setattr(subagent, "agent_sign", lambda tx, key, c: tx)
    return subagent, s


def test_buy_refuses_a_price_above_the_limit_before_asking_cereal(sub, monkeypatch):
    subagent, s = sub
    posts = []
    monkeypatch.setattr(subagent.requests, "get", lambda url, **k: _Resp(402, accepts(amount="2")))
    monkeypatch.setattr(subagent.requests, "post", lambda *a, **k: posts.append(a))
    r = s.buy("http://v/swell/agenda", max_rlusd="1")
    assert r["refused"] == "price_above_limit" and posts == []


def test_buy_passes_cereal_refusals_through_and_never_presents(sub, monkeypatch):
    subagent, s = sub
    gets = []
    monkeypatch.setattr(subagent.requests, "get", lambda url, **k: gets.append(k.get("headers")) or _Resp(402, accepts()))
    monkeypatch.setattr(subagent.requests, "post", lambda *a, **k: _Resp(200, {"refused": "vendor_not_credentialed",
                                                                              "vendor": {"status": "revoked"}}))
    r = s.buy("http://v/swell/agenda")
    assert r["refused"] == "vendor_not_credentialed" and r["vendor"]["status"] == "revoked"
    assert gets == [None], "no payment header was ever sent to the vendor"


def test_buy_retries_once_after_409_when_the_ledger_shows_it_settled(sub, monkeypatch):
    import base64, json
    subagent, s = sub
    settled = base64.b64encode(json.dumps({"success": True, "transaction": "H"}).encode()).decode()
    seq = [_Resp(402, accepts()), _Resp(409, {"error": "settlement_status_unknown"}),
           _Resp(200, {"data": {"x": 1}}, {"PAYMENT-RESPONSE": settled})]
    monkeypatch.setattr(subagent.requests, "get", lambda url, **k: seq.pop(0))
    monkeypatch.setattr(subagent.requests, "post", lambda *a, **k: _Resp(200, {"ok": True, "hash": "H", "blob": "00"}))
    monkeypatch.setattr(subagent, "_validated", lambda c, h, wait_s=30: "tesSUCCESS")
    r = s.buy("http://v/swell/agenda")
    assert r["ok"] and r["retried_after_409"] and r["data"] == {"data": {"x": 1}}
