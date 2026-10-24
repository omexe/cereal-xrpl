"""Part 2 unit tests: vendor credential policy order and vendor states, without the network."""
import json
from types import SimpleNamespace

import pytest
from xrpl.models.transactions import Payment
from xrpl.utils import str_to_hex, xrp_to_drops

from cereal import config, deployments, vendors
from cereal.ledger import rlusd

SUB = "rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR"
A = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"
B = "rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", True)


def _rec(allowed=()):
    d = deployments.create("t", "1", list(allowed))
    return deployments.update(d["id"], status="active", subwallet=SUB)


def _tx(dest=A, amount=None):
    return Payment(account=SUB, destination=dest, amount=amount or rlusd("0.25")).to_xrpl()


def _vendor(monkeypatch, status, **extra):
    monkeypatch.setattr(vendors, "check", lambda c, addr, issuer_addr=None, vendor_class="data": {"status": status, "vendor": addr, **extra})


def test_revoked_vendor_refused_with_evidence_before_allowlist(monkeypatch):
    from cereal.service import _cosign_deployment
    _vendor(monkeypatch, "revoked", revocation={"hash": "C0237EDD", "reason": "overcharge"})
    r = _cosign_deployment(_rec(allowed=[A]), _tx(dest=B))  # B is also off the allowlist: credential check comes first
    assert r["refused"] == "vendor_not_credentialed"
    assert r["vendor"]["status"] == "revoked" and r["vendor"]["revocation"]["hash"] == "C0237EDD"


@pytest.mark.parametrize("status", ["pending", "expired", "none"])
def test_non_valid_credentials_refused(monkeypatch, status):
    from cereal.service import _cosign_deployment
    _vendor(monkeypatch, status)
    assert _cosign_deployment(_rec(), _tx())["refused"] == "vendor_not_credentialed"


def test_empty_allowlist_means_any_credentialed_vendor(monkeypatch):
    from cereal.service import _cosign_deployment
    _vendor(monkeypatch, "valid")
    # gets past the credential and allowlist checks; stops at the next check (XRP is not RLUSD) before any network call
    assert _cosign_deployment(_rec(), _tx(amount=xrp_to_drops(1)))["refused"] == "not_rlusd"


def test_allowlist_still_narrows_credentialed_vendors(monkeypatch):
    from cereal.service import _cosign_deployment
    _vendor(monkeypatch, "valid")
    assert _cosign_deployment(_rec(allowed=[A]), _tx(dest=B))["refused"] == "payee_not_allowed"


def test_deploy_without_payees_refused_when_credentials_off(monkeypatch):
    from cereal.service import DeployRequest, deploy
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)
    assert deploy(DeployRequest(task="t", budget="1"))["refused"] == "no_payee_policy"


class FakeClient:
    def __init__(self, node):
        self.node = node

    def request(self, req):
        return SimpleNamespace(result={"node": self.node})


def test_check_reads_pending_and_expired(monkeypatch):
    monkeypatch.setattr(vendors, "revocation", lambda *a, **k: None)
    assert vendors.check(FakeClient({"Flags": 0}), A, issuer_addr="rI")["status"] == "pending"
    assert vendors.check(FakeClient({"Flags": vendors.LSF_ACCEPTED}), A, issuer_addr="rI")["status"] == "valid"
    assert vendors.check(FakeClient({"Flags": vendors.LSF_ACCEPTED, "Expiration": 1}), A, issuer_addr="rI")["status"] == "expired"
    monkeypatch.setattr(vendors, "account_objects", lambda *a, **k: [])
    assert vendors.check(FakeClient({}), A, issuer_addr="rI")["status"] == "none"


def _deleted(subject, reason):
    memo = {"Memo": {"MemoData": str_to_hex(json.dumps({"reason": reason})).upper()}}
    return {"tx": {"TransactionType": "CredentialDelete", "Subject": subject, "CredentialType": vendors.CTYPE_HEX.upper(),
                   "Memos": [memo]}, "hash": "DEL1", "ledger_index": 2}


def test_revocation_evidence_and_reissue(monkeypatch):
    created = {"tx": {"TransactionType": "CredentialCreate", "Subject": B, "CredentialType": vendors.CTYPE_HEX}, "hash": "NEW"}
    monkeypatch.setattr(vendors, "account_tx", lambda c, addr, limit=200: [_deleted(B, "overcharge")])
    ev = vendors.revocation(None, B, issuer_addr="rI")
    assert ev["hash"] == "DEL1" and ev["reason"] == "overcharge"
    monkeypatch.setattr(vendors, "account_tx", lambda c, addr, limit=200: [created, _deleted(B, "overcharge")])
    assert vendors.revocation(None, B, issuer_addr="rI") is None  # re-issued after the revocation
