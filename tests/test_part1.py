"""Part 1 unit tests: caps and the co-sign policy, without touching the network."""
from decimal import Decimal

import pytest
from xrpl.models.transactions import Payment
from xrpl.utils import xrp_to_drops

from cereal import config, deployments


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(config, "MAX_SUBAGENT_BUDGET", 5.0)
    monkeypatch.setattr(config, "MAX_OUTSTANDING_BUDGET", 6.0)
    monkeypatch.setattr(config, "MAX_ACTIVE_SUBAGENTS", 2)
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)  # Part 1 semantics: allowlist only


def test_per_subagent_cap():
    r = deployments.check_caps("5.01")
    assert r["refused"] == "cap_exceeded" and r["cap"] == "MAX_SUBAGENT_BUDGET"


def test_outstanding_cap_counts_live_deployments_only():
    a = deployments.create("a", "4", ["rA"])
    deployments.update(a["id"], status="active")
    assert deployments.check_caps("2.5")["cap"] == "MAX_OUTSTANDING_BUDGET"
    deployments.update(a["id"], status="reclaimed")
    assert deployments.check_caps("2.5") is None
    assert deployments.outstanding_budget() == Decimal(0)


def test_active_count_cap():
    for i in range(2):
        d = deployments.create(f"t{i}", "1", ["rA"]); deployments.update(d["id"], status="active")
    assert deployments.check_caps("1")["cap"] == "MAX_ACTIVE_SUBAGENTS"


def test_invalid_budget():
    assert deployments.check_caps("0")["refused"] == "invalid_budget"


SUB = "rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR"
PAYEE = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"
OTHER = "rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3"


def _active():
    d = deployments.create("task", "1", [PAYEE])
    return deployments.update(d["id"], status="active", subwallet=SUB)


def _tx(account=SUB, dest=PAYEE, amount=None):
    from cereal.ledger import rlusd
    return Payment(account=account, destination=dest, amount=amount or rlusd("0.25")).to_xrpl()


def test_cosign_refusals_before_any_network_call():
    from cereal.service import _cosign_deployment
    assert _cosign_deployment(None, _tx())["refused"] == "unknown_or_inactive_deployment"
    rec = _active()
    assert _cosign_deployment(rec, _tx(account=OTHER))["refused"] == "not_a_subwallet_payment"
    assert _cosign_deployment(rec, _tx(dest=OTHER))["refused"] == "payee_not_allowed"
    assert _cosign_deployment(rec, _tx(amount=xrp_to_drops(1)))["refused"] == "not_rlusd"


def test_inactive_deployment_is_refused():
    from cereal.service import _cosign_deployment
    rec = _active(); rec = deployments.update(rec["id"], status="reclaimed")
    assert _cosign_deployment(rec, _tx())["refused"] == "unknown_or_inactive_deployment"


def test_even_plan_never_exceeds_envelope():
    from cereal.main_agent import plan_even
    plan = plan_even("goal", Decimal("1"), 3)
    assert len(plan) == 3 and sum(Decimal(b) for _, b in plan) <= Decimal("1")
