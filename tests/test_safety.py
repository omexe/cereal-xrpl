"""Service safety (checklist R01-R04), offline: the issuer check, atomic caps, idempotent deploys and safe record writes.

The ledger is mocked; every call that would touch it is recorded in `sent`, so a test can prove nothing was sent.
Locks live in the test's tmp dir, so these tests never contend with live cereal services on the same machine.
"""
import json
import os
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.transactions import Payment

from cereal import config, deployments, device, keystore, subwallets, xlock
from cereal.ledger import rlusd

ROOT = Path(__file__).resolve().parents[1]
MAIN = "rGP3CdfnKSSz4BYPNTjKiNGzM98xDxbEfj"
DEV = "rn1FZHRNBPX8g2Y5Xzhx1LonhmSheFYMAq"
SUBAGENT = "rDm4QaxZY47F9dKf9tN43Dz73NPXMbZw9R"
SUB = "rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR"
PAYEE = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"
FAKE_ISSUER = "rapyJNHMJW1C6BiVvaTXKTjWMZqJnaWXR3"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(xlock, "LOCK_DIR", tmp_path)
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    return tmp_path


@pytest.fixture
def svc(store, monkeypatch):
    """The service with every ledger read faked and every ledger write recorded."""
    from cereal import service
    monkeypatch.setattr(service, "_main_wallet", xlock.ProcessLock("treasury"))  # lives in tmp (LOCK_DIR above)
    monkeypatch.setattr(config, "DEVICE_FUNDING", False)
    monkeypatch.setattr(config, "DEVICE_DECISION", "approve")
    monkeypatch.setattr(config, "LEDGER_ADDRESS", DEV)
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", True)
    monkeypatch.setattr(config, "MAX_SUBAGENT_BUDGET", 5.0)
    monkeypatch.setattr(config, "MAX_OUTSTANDING_BUDGET", 10.0)
    monkeypatch.setattr(config, "MAX_ACTIVE_SUBAGENTS", 5)
    monkeypatch.setattr(config, "address", lambda role: MAIN if role == "TREASURY" else "rCOSIGN")
    monkeypatch.setattr(config, "wallet", lambda role: object())
    sent = {"create": [], "fund": [], "sign": [], "submit": []}
    state = SimpleNamespace(delay=0.0, create_ok=True, create_raises=None, seen=[])
    monkeypatch.setattr(service, "client", lambda: object())
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: Decimal("100"))
    monkeypatch.setattr(service, "account_info", lambda c, a: {"Balance": str(200 * 10**6), "Sequence": 500})
    monkeypatch.setattr(service, "prepare", lambda tx, c, **kw: tx)
    monkeypatch.setattr(subwallets, "activation_xrp", lambda c: Decimal("1.9"))
    monkeypatch.setattr(keystore, "new_subagent_key", lambda dep_id: SUBAGENT)

    def fake_create(dep_id, tag, budget, sub_key, c, main=None, sub=None):
        on_record = deployments.get(dep_id)  # what a crash right now would leave behind
        assert on_record["subwallet"] == sub.classic_address, "the address is recorded before activation is sent"
        state.seen.append(on_record)
        time.sleep(state.delay)  # a slow ledger widens every race window
        sent["create"].append(dep_id)
        if state.create_raises:
            raise state.create_raises
        return {"ok": state.create_ok, "address": sub.classic_address, "error": None if state.create_ok else "tecX",
                "hashes": {"activate": "ACT_" + dep_id, "lock": ["L_" + dep_id]}}

    def fake_fund(treasury, addr, budget, dep_id, tag, c):
        sent["fund"].append(dep_id)
        return {"ok": True, "hash": "FUND_" + dep_id, "validated": True}

    monkeypatch.setattr(subwallets, "create", fake_create)
    monkeypatch.setattr(service, "fund_burner", fake_fund)
    monkeypatch.setattr(device, "available", lambda: True)
    monkeypatch.setattr(device, "submit_signed", lambda signed, c, **kw: sent["submit"].append(signed) or
                        {"ok": True, "hash": "DEVFUND", "signed_on": "ledger"})
    return SimpleNamespace(service=service, sent=sent, state=state, mp=monkeypatch)


def _req(svc, **kw):
    return svc.service.DeployRequest(**{"task": "t", "budget": "1", "allowed_payees": [PAYEE], **kw})


def _parallel(fn, n):
    """Run fn(i) in n threads released together; return the results in order."""
    barrier, out, errors = threading.Barrier(n), [None] * n, []

    def work(i):
        barrier.wait()
        try:
            out[i] = fn(i)
        except BaseException as e:  # surfaced below, never swallowed
            errors.append(e)
    threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors
    return out


# ---- R01: the co-signer enforces the configured RLUSD issuer ----

def _active_record():
    d = deployments.create("task", "1", [PAYEE])
    return deployments.update(d["id"], status="active", subwallet=SUB)


def _tx(issuer):
    amt = IssuedCurrencyAmount(currency=config.RLUSD_CURRENCY, issuer=issuer, value="0.25")
    return Payment(account=SUB, destination=PAYEE, amount=amt).to_xrpl()


def _no_signing(monkeypatch):
    from cereal import service
    for name in ("cosign_and_submit", "cosign_combine", "submit_capture"):
        monkeypatch.setattr(service, name, lambda *a, **k: pytest.fail("signed a payment it should have refused"))
    monkeypatch.setattr(device, "sign", lambda *a, **k: pytest.fail("asked the device to sign a refused payment"))


@pytest.mark.parametrize("present", [False, True])
def test_rlusd_code_from_another_issuer_is_refused_before_signing(store, monkeypatch, present):
    from cereal import service
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: pytest.fail("read a balance for a refused payment"))
    _no_signing(monkeypatch)
    r = service._cosign_deployment(_active_record(), _tx(FAKE_ISSUER), present=present)
    assert r["ok"] is False and r["refused"] == "wrong_issuer"
    assert r["issuer"] == FAKE_ISSUER and r["expected"] == config.RLUSD_ISSUER


def test_wrong_issuer_through_the_endpoint_is_recorded_as_a_refusal(store, monkeypatch):
    from cereal import service
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)
    _no_signing(monkeypatch)
    rec = _active_record()
    r = service.cosign(service.CosignRequest(deployment_id=rec["id"], tx=_tx(FAKE_ISSUER)))
    assert r["refused"] == "wrong_issuer"
    (refusal,) = deployments.get(rec["id"])["refusals"]
    assert refusal["refused"] == "wrong_issuer" and refusal["issuer"] == FAKE_ISSUER and refusal["amount"] == "0.25"


def test_the_configured_issuer_passes_the_issuer_check(store, monkeypatch):
    from cereal import service
    monkeypatch.setattr(config, "REQUIRE_VENDOR_CREDENTIAL", False)
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: Decimal("1"))
    _no_signing(monkeypatch)
    assert _tx(config.RLUSD_ISSUER)["Amount"] == rlusd("0.25").to_dict()
    # gets past the issuer check and stops at the next one (no memo) before anything is signed
    assert service._cosign_deployment(_active_record(), _tx(config.RLUSD_ISSUER))["refused"] == "memo_mismatch"


# ---- R02: caps are checked and reserved atomically ----

def test_concurrent_deploys_cannot_pass_a_stale_active_count(svc):
    svc.mp.setattr(config, "MAX_ACTIVE_SUBAGENTS", 2)
    svc.state.delay = 0.2
    out = _parallel(lambda i: svc.service.deploy(_req(svc)), 3)
    ok = [r for r in out if r.get("ok")]
    refused = [r for r in out if r.get("refused")]
    assert len(ok) == 2 and len(refused) == 1
    assert refused[0]["refused"] == "cap_exceeded" and refused[0]["cap"] == "MAX_ACTIVE_SUBAGENTS"
    assert len(svc.sent["create"]) == 2 and len(svc.sent["fund"]) == 2, "no transaction for the refused deploy"
    assert len(deployments.all_()) == 2


def test_concurrent_deploys_cannot_pass_a_stale_outstanding_budget(svc):
    svc.mp.setattr(config, "MAX_OUTSTANDING_BUDGET", 1.0)
    svc.state.delay = 0.2
    out = _parallel(lambda i: svc.service.deploy(_req(svc, budget="0.5")), 3)
    refused = [r for r in out if r.get("refused")]
    assert sum(1 for r in out if r.get("ok")) == 2 and len(refused) == 1
    assert refused[0]["cap"] == "MAX_OUTSTANDING_BUDGET" and refused[0]["outstanding"] == "1.0"
    assert len(svc.sent["create"]) == 2 and len(svc.sent["fund"]) == 2
    assert deployments.outstanding_budget() == Decimal("1.0")


def test_the_check_inside_the_main_wallet_lock_is_authoritative(svc):
    """Every request passes a stale early check (as concurrent ones can); the locked reservation still refuses."""
    svc.mp.setattr(config, "MAX_ACTIVE_SUBAGENTS", 2)
    svc.mp.setattr(deployments, "check_caps", lambda budget: None)
    svc.state.delay = 0.1
    out = _parallel(lambda i: svc.service.deploy(_req(svc)), 4)
    assert sum(1 for r in out if r.get("ok")) == 2
    assert [r["cap"] for r in out if r.get("refused")] == ["MAX_ACTIVE_SUBAGENTS"] * 2
    assert len(svc.sent["create"]) == 2 and len(svc.sent["fund"]) == 2


def test_reserve_creates_the_record_only_within_caps(store, monkeypatch):
    monkeypatch.setattr(config, "MAX_ACTIVE_SUBAGENTS", 1)
    rec = deployments.reserve("t", "1", [PAYEE], request_id="r1", name="Market Sizing", folder=None)
    assert rec["status"] == "deploying" and rec["request_id"] == "r1" and rec["name"] == "Market Sizing"
    assert "folder" not in rec, "None fields are not written"
    assert deployments.reserve("t", "1", [PAYEE])["cap"] == "MAX_ACTIVE_SUBAGENTS"
    assert deployments.reserve("t", "1", [PAYEE], request_id="r1")["refused"] == "duplicate_request"
    assert len(deployments.all_()) == 1


@pytest.mark.parametrize("budget", ["0", "-1", "abc", "NaN", "Infinity"])
def test_invalid_budgets_are_refusals_not_errors(store, budget):
    r = deployments.check_caps(budget)
    assert r["refused"] in ("invalid_budget", "cap_exceeded")


# ---- R03: idempotent deploys ----

def test_a_repeated_request_id_returns_the_original_deployment_and_sends_nothing(svc):
    first = svc.service.deploy(_req(svc, request_id="click-1"))
    again = svc.service.deploy(_req(svc, request_id="click-1"))
    assert first["ok"] and "replayed" not in first
    assert again["ok"] and again["replayed"] is True and again["id"] == first["id"]
    assert again["hashes"] == first["hashes"]
    assert svc.sent["create"] == [first["id"]] and svc.sent["fund"] == [first["id"]]
    assert len(deployments.all_()) == 1 and deployments.get(first["id"])["request_id"] == "click-1"


def test_without_a_request_id_each_deploy_is_new(svc):
    a, b = svc.service.deploy(_req(svc)), svc.service.deploy(_req(svc))
    assert a["id"] != b["id"] and len(svc.sent["fund"]) == 2


def test_a_device_rejection_is_replayed_not_asked_again(svc):
    svc.mp.setattr(config, "DEVICE_FUNDING", True)

    def reject(tx, decision=None):
        svc.sent["sign"].append(decision)
        return {"ok": False, "result": "owner_rejected", "screens": ["Amount: 1"]}
    svc.mp.setattr(device, "sign", reject)
    first = svc.service.deploy(_req(svc, request_id="r-reject", speculos_decision="reject"))
    again = svc.service.deploy(_req(svc, request_id="r-reject", speculos_decision="reject"))
    assert first["refused"] == "owner_rejected" and first["sent_transactions"] == 0
    assert again == {**first, "replayed": True}
    assert len(svc.sent["sign"]) == 1 and svc.sent["create"] == [] and svc.sent["submit"] == []
    assert deployments.get(first["deployment"])["status"] == "rejected"


def test_a_failed_lock_is_replayed_not_retried(svc):
    svc.state.create_ok = False
    first = svc.service.deploy(_req(svc, request_id="r-fail"))
    svc.state.create_ok = True  # the ledger would accept a retry now: the replay must still not send one
    again = svc.service.deploy(_req(svc, request_id="r-fail"))
    assert first["refused"] == "subwallet_failed" and again == {**first, "replayed": True}
    assert len(svc.sent["create"]) == 1 and svc.sent["fund"] == []
    assert deployments.get(first["deployment"])["status"] == "failed"


def test_an_error_before_the_ledger_undoes_the_reservation_and_a_retry_starts_afresh(svc):
    svc.mp.setattr(config, "MAX_ACTIVE_SUBAGENTS", 1)

    def broken(dep_id):
        raise OSError("disk full")
    svc.mp.setattr(keystore, "new_subagent_key", broken)
    first = svc.service.deploy(_req(svc, request_id="r-err"))
    assert first["refused"] == "deploy_error" and first["sent_transactions"] == 0 and first["error"] == "OSError"
    assert "deployment" not in first and deployments.all_() == [], "nothing reached the ledger: no record, no slot"
    assert svc.sent == {"create": [], "fund": [], "sign": [], "submit": []}
    svc.mp.setattr(keystore, "new_subagent_key", lambda dep_id: SUBAGENT)  # the fault is gone: the same id deploys
    again = svc.service.deploy(_req(svc, request_id="r-err"))
    assert again["ok"] and "replayed" not in again and svc.sent["fund"] == [again["id"]]


def test_an_error_after_the_ledger_is_kept_on_the_record_and_never_deployed_again(svc):
    svc.mp.setattr(config, "MAX_ACTIVE_SUBAGENTS", 1)
    svc.state.create_raises = TimeoutError("node went away mid-lock")
    first = svc.service.deploy(_req(svc, request_id="r-mid"))
    assert first["refused"] == "deploy_interrupted" and first["status"] == "deploying"
    assert first["subwallet"] == svc.state.seen[0]["subwallet"] and first["error"] == "TimeoutError"
    svc.state.create_raises = None
    assert svc.service.deploy(_req(svc, request_id="r-mid")) == {**first, "replayed": True}
    assert len(svc.sent["create"]) == 1 and svc.sent["fund"] == []
    rec = deployments.get(first["deployment"])
    assert rec["status"] == "deploying" and rec["outcome"] == first, "it may hold funds: it keeps its cap slot"
    assert svc.service.deploy(_req(svc))["cap"] == "MAX_ACTIVE_SUBAGENTS"


def test_a_funded_wallet_is_never_left_deploying_by_a_failed_record_write(svc):
    real, failures = deployments.update, []

    def flaky(dep_id, **fields):
        if fields.get("status") == "active" and not failures:
            failures.append(1)
            raise OSError("disk hiccup")
        return real(dep_id, **fields)
    svc.mp.setattr(deployments, "update", flaky)
    r = svc.service.deploy(_req(svc, request_id="r-flaky"))
    assert failures and r["ok"] and r["status"] == "active" and deployments.get(r["id"])["status"] == "active"
    assert len(svc.sent["fund"]) == 1


def test_the_request_id_is_on_the_record_from_its_first_write(svc):
    out = svc.service.deploy(_req(svc, request_id="r-first"))
    (seen,) = svc.state.seen
    assert seen["request_id"] == "r-first" and seen["status"] == "deploying" and seen["id"] == out["id"]
    assert seen["deploy_request"] == {"task": "t", "budget": "1", "allowed_payees": [PAYEE], "vendor_class": "data",
                                      "expires_in_hours": 24, "approval_threshold": None, "sweep_when_done": False}


def test_concurrent_twins_never_make_a_second_deployment(svc):
    svc.state.delay = 0.3
    out = _parallel(lambda i: svc.service.deploy(_req(svc, request_id="double-click")), 3)
    first = [r for r in out if r.get("ok") and not r.get("replayed")]
    assert len(first) == 1, out
    for r in out:  # a twin is refused in_progress at once, or (if it queued before the record existed) replays it
        assert r is first[0] or r.get("refused") == "in_progress" or r.get("replayed") is True
        assert (r.get("id") or r.get("deployment")) == first[0]["id"]
    assert len(svc.sent["create"]) == 1 and len(svc.sent["fund"]) == 1
    assert svc.service.deploy(_req(svc, request_id="double-click"))["replayed"] is True


def test_a_twin_is_refused_in_progress_without_waiting_for_the_first(svc):
    svc.state.delay = 0.5
    first = threading.Thread(target=lambda: svc.service.deploy(_req(svc, request_id="r-slow")))
    first.start()
    while not svc.state.seen:  # the first deploy is now inside subwallets.create, holding the main-wallet lock
        time.sleep(0.01)
    t = time.monotonic()
    r = svc.service.deploy(_req(svc, request_id="r-slow"))
    assert time.monotonic() - t < 0.3, "the twin waited for the first deploy"
    assert r["refused"] == "in_progress" and r["deployment"] == svc.state.seen[0]["id"]
    first.join(10)
    assert len(svc.sent["create"]) == 1


def test_an_interrupted_deploy_is_refused_in_progress_and_never_redeployed(svc):
    stuck = deployments.reserve("t", "1", [PAYEE], request_id="r-crash")  # a deploy that died mid-way
    deployments.update(stuck["id"], subwallet=SUB)
    deployments.merge_hashes(stuck["id"], activate="ACT_SENT")
    r = svc.service.deploy(_req(svc, request_id="r-crash"))
    assert r["refused"] == "in_progress" and r["deployment"] == stuck["id"] and r["replayed"] is True
    assert r["hashes"] == {"activate": "ACT_SENT"} and r["subwallet"] == SUB
    assert svc.sent == {"create": [], "fund": [], "sign": [], "submit": []}


def test_a_request_id_reused_for_different_terms_is_refused(svc):
    first = svc.service.deploy(_req(svc, request_id="r-1"))
    r = svc.service.deploy(_req(svc, request_id="r-1", budget="2"))
    assert r["refused"] == "request_id_reused" and r["deployment"] == first["id"] and r["differs"] == ["budget"]
    assert r["sent_transactions"] == 0 and len(svc.sent["fund"]) == 1
    assert svc.service.deploy(_req(svc, request_id="r-1", expires_in_hours=2))["differs"] == ["expires_in_hours"]
    assert svc.service.deploy(_req(svc, request_id="r-1", sweep_when_done=True))["differs"] == ["sweep_when_done"]
    # the same budget written differently is the same request
    assert svc.service.deploy(_req(svc, request_id="r-1", budget="1.0"))["replayed"] is True


def test_a_repeat_is_compared_with_the_request_as_sent_not_the_wallet_now(svc):
    first = svc.service.deploy(_req(svc, request_id="r-topup"))
    deployments.update(first["id"], budget="3", allowed_payees=[PAYEE, SUB])  # a later top-up and rules edit
    again = svc.service.deploy(_req(svc, request_id="r-topup"))
    assert again["ok"] and again["replayed"] is True and again["id"] == first["id"]


def test_a_conflicting_repeat_does_not_wait_for_the_main_wallet_lock(svc):
    stuck = deployments.reserve("t", "1", [PAYEE], request_id="r-busy",
                                deploy_request=svc.service._request_terms(_req(svc, request_id="r-busy")))
    out = []
    with svc.service._main_wallet:  # the first request is still deploying and holds the lock
        t = threading.Thread(target=lambda: out.append(svc.service.deploy(_req(svc, request_id="r-busy", budget="2"))))
        t.start(); t.join(5)
        assert out, "a conflicting repeat waited on the main-wallet lock"
    assert out[0]["refused"] == "request_id_reused" and out[0]["deployment"] == stuck["id"]


# ---- R03 through POST /wallets: one mechanism, the request_id deploy() writes with the record ----

VENDOR_C = "r3NdoyQhgKorLo54v2VGkMrMTyPHbTXszs"
SENTENCE = "Create test: spend up to 0.5 RLUSD today, only at Vendor A and Vendor C. Sweep back when done."


@pytest.fixture
def wallets(svc):
    from cereal import directory, llm, wallet_card
    svc.mp.setattr(llm, "available", lambda: False)
    svc.mp.setattr(config, "APPROVAL_THRESHOLD", None)
    svc.mp.setattr(directory, "list_vendors", lambda c=None: [
        {"name": "Vendor A", "address": PAYEE, "credential": {"status": "valid"}},
        {"name": "Vendor C", "address": VENDOR_C, "credential": {"status": "valid"}}])
    wallet_card.in_progress.clear()
    yield svc
    wallet_card.in_progress.clear()


def test_wallet_create_passes_its_request_id_to_deploy(wallets):
    s = wallets.service
    first = s.wallet_create(s.WalletRequest(sentence=SENTENCE, request_id="w-1"))
    assert first["ok"] and wallets.state.seen[0]["request_id"] == "w-1", "on the record from deploy's first write"
    again = s.wallet_create(s.WalletRequest(sentence=SENTENCE, request_id="w-1"))
    assert again["ok"] and again["replayed"] is True and again["id"] == first["id"]
    assert wallets.sent["create"] == [first["id"]] and wallets.sent["fund"] == [first["id"]]


def test_a_wallet_twin_during_the_deploy_is_refused_in_progress(wallets):
    s = wallets.service
    wallets.state.delay = 0.4
    out = _parallel(lambda i: s.wallet_create(s.WalletRequest(sentence=SENTENCE, request_id="w-twin")), 2)
    assert sorted(r.get("refused") or "ok" for r in out) == ["in_progress", "ok"]
    assert len(wallets.sent["create"]) == 1 and len(wallets.sent["fund"]) == 1


def test_after_a_restart_mid_deploy_a_wallet_retry_creates_nothing(wallets):
    s = wallets.service
    stuck = deployments.reserve("t", "0.5", [PAYEE, VENDOR_C], request_id="w-crash", sentence=SENTENCE)
    r = s.wallet_create(s.WalletRequest(sentence=SENTENCE, request_id="w-crash"))
    assert r["refused"] == "in_progress" and r["deployment"] == stuck["id"]
    assert wallets.sent == {"create": [], "fund": [], "sign": [], "submit": []}


def test_an_oversized_request_id_is_refused(svc):
    assert svc.service.deploy(_req(svc, request_id="x" * 129))["refused"] == "invalid_request_id"
    assert deployments.all_() == []


# ---- R04: atomic, cross-process-safe record writes ----

def test_concurrent_updates_from_threads_never_overwrite_each_other(store):
    rec = deployments.create("t", "1", [PAYEE])
    dep, n = rec["id"], 15

    def work(i):
        for k in range(n):
            h = f"H{i}-{k}"
            deployments.record_payment(dep, {"hash": h, "result": "presented"})
            deployments.record_event(dep, {"kind": "prove_lock", "n": h})
            deployments.record_refusal(dep, {"refused": "over_budget", "n": h})
            deployments.update_payment(dep, h, result="tesSUCCESS", ok=True)
            deployments.merge_hashes(dep, **{f"t{i}": h})
    _parallel(work, 6)
    final = deployments.get(dep)
    assert len(final["payments"]) == len(final["events"]) == len(final["refusals"]) == 6 * n
    assert all(p["result"] == "tesSUCCESS" for p in final["payments"])
    assert final["hashes"] == {f"t{i}": f"H{i}-{n - 1}" for i in range(6)}


def test_readers_never_see_a_partial_file(store):
    rec = deployments.create("t", "1", [PAYEE])
    stop, seen, errors = threading.Event(), [], []

    def read():
        while not stop.is_set():
            try:
                seen.append(len(deployments.get(rec["id"])["payments"]))
            except Exception as e:  # a torn write shows up as a JSONDecodeError here
                errors.append(e)
    reader = threading.Thread(target=read)
    reader.start()
    for k in range(60):
        deployments.record_payment(rec["id"], {"hash": f"H{k}", "blob": "00" * 500})
    stop.set(); reader.join(10)
    assert not errors and seen == sorted(seen)


def test_a_failed_write_leaves_the_store_whole(store, monkeypatch):
    rec = deployments.create("t", "1", [PAYEE])
    before = config.DEPLOYMENTS_FILE.read_text()

    def crash(src, dst):
        raise OSError("power cut before the rename")
    monkeypatch.setattr(deployments.os, "replace", crash)
    with pytest.raises(OSError):
        deployments.update(rec["id"], status="active")
    assert config.DEPLOYMENTS_FILE.read_text() == before
    assert [p.name for p in store.iterdir() if p.name.startswith("deployments")] == ["deployments.json"]


def test_a_new_store_follows_the_umask(store):
    old = os.umask(0o077)
    try:
        deployments.create("t", "1", [PAYEE])
    finally:
        os.umask(old)
    assert config.DEPLOYMENTS_FILE.stat().st_mode & 0o777 == 0o600


def test_the_store_lock_is_reentrant_within_a_thread(store):
    rec = deployments.create("t", "1", [PAYEE])
    done = threading.Event()

    def nested():
        with deployments._lock:
            with deployments._lock:
                deployments.update(rec["id"], status="active")  # takes _lock a third time
            deployments.record_payment(rec["id"], {"hash": "H"})
        done.set()
    t = threading.Thread(target=nested, daemon=True)
    t.start(); t.join(5)
    assert done.is_set(), "a nested hold of deployments._lock deadlocked"
    assert deployments.get(rec["id"])["status"] == "active"
    with deployments._lock:  # and it is free again for the next holder
        pass


def test_writes_keep_the_store_mode_and_leave_no_temp_files(store):
    rec = deployments.create("t", "1", [PAYEE])
    os.chmod(config.DEPLOYMENTS_FILE, 0o640)
    deployments.update(rec["id"], status="active")
    assert config.DEPLOYMENTS_FILE.stat().st_mode & 0o777 == 0o640
    assert [p.name for p in store.iterdir() if p.name.startswith("deployments")] == ["deployments.json"]


CHILD = """
import os, sys
from cereal import deployments
dep, n = sys.argv[1], int(sys.argv[2])
print("ready", flush=True)
sys.stdin.readline()  # go
if dep == "reserve":
    r = deployments.reserve("t", "1", ["rA"])
    print(r.get("refused") or "reserved", flush=True)
else:
    print("writing", flush=True)
    for k in range(n):
        deployments.record_payment(dep, {"hash": f"P{os.getpid()}-{k}"})
        deployments.record_event(dep, {"kind": "prove_lock", "n": k})
"""


def _children(store, args, count, extra_env=None):
    """Child processes on the same store and lock dir, each imported and waiting; `go` releases them together."""
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1", "CEREAL_DEPLOYMENTS_FILE": str(config.DEPLOYMENTS_FILE),
           "CEREAL_LOCK_DIR": str(store), **(extra_env or {})}
    procs = [subprocess.Popen([sys.executable, "-c", CHILD, *args], cwd=ROOT, env=env, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True) for _ in range(count)]
    for p in procs:
        assert p.stdout.readline().strip() == "ready"

    def go():
        for p in procs:
            p.stdin.write("\n"); p.stdin.flush()
    return procs, go


def test_concurrent_updates_from_processes_never_overwrite_each_other(store):
    rec = deployments.create("t", "1", [PAYEE])
    procs, go = _children(store, [rec["id"], "15"], 3)
    go()
    for k in range(15):  # this process writes at the same time, through the same file lock
        deployments.record_payment(rec["id"], {"hash": f"parent-{k}"})
    for p in procs:
        p.wait(60)
        assert p.returncode == 0
    final = json.loads(config.DEPLOYMENTS_FILE.read_text())[rec["id"]]
    assert len(final["payments"]) == 4 * 15 and len(final["events"]) == 3 * 15
    assert len({p["hash"] for p in final["payments"]}) == 4 * 15


def test_concurrent_reservations_from_processes_respect_the_caps(store):
    procs, go = _children(store, ["reserve", "0"], 4,
                          {"MAX_ACTIVE_SUBAGENTS": "2", "MAX_OUTSTANDING_BUDGET": "10", "MAX_SUBAGENT_BUDGET": "5"})
    go()
    outs = []
    for p in procs:
        out, _ = p.communicate(timeout=60)
        assert p.returncode == 0
        outs.append(out.strip())
    assert sorted(outs) == ["cap_exceeded", "cap_exceeded", "reserved", "reserved"]
    assert len(deployments.all_()) == 2


def test_holding_the_store_lock_blocks_writers_in_other_processes(store):
    """Callers' own read-check-write (`with deployments._lock:`) is atomic across processes, not just threads."""
    rec = deployments.create("t", "1", [PAYEE])
    (child,), go = _children(store, [rec["id"], "1"], 1)
    with deployments._lock:
        go()
        assert child.stdout.readline().strip() == "writing"  # the child is now trying to write
        time.sleep(0.5)
        assert deployments.get(rec["id"])["payments"] == [], "a writer in another process got in"
    child.wait(30)
    assert child.returncode == 0 and len(deployments.get(rec["id"])["payments"]) == 1



def test_legacy_cosign_refuses_wrong_issuer(monkeypatch):
    """R01 for the legacy single-job co-signer (POST /cosign with job_id): the RLUSD code from another issuer is refused
    before any balance read or signature."""
    from xrpl.models.amounts import IssuedCurrencyAmount
    from xrpl.models.transactions import Payment
    from xrpl.wallet import Wallet
    from cereal import config, cosign as legacy
    burner, vendor, fake_issuer = Wallet.create(), Wallet.create(), Wallet.create()
    monkeypatch.setattr(legacy.jobs, "get", lambda job_id: {"burner": burner.classic_address, "status": "active",
                                                            "expires_at": "2999-01-01T00:00:00+00:00"})
    monkeypatch.setattr(legacy, "client", lambda: object())
    monkeypatch.setattr(legacy.vendors, "check", lambda *a, **k: {"status": "valid"})

    def no_balance_read(*a, **k):
        raise AssertionError("the balance must not be read for a wrong-issuer payment")
    monkeypatch.setattr(legacy, "rlusd_balance", no_balance_read)
    monkeypatch.setattr(legacy, "cosign_and_submit", no_balance_read)
    tx = Payment(account=burner.classic_address, destination=vendor.classic_address,
                 amount=IssuedCurrencyAmount(currency=config.RLUSD_CURRENCY, issuer=fake_issuer.classic_address, value="0.1"))
    out = legacy.cosign(legacy.CosignRequest(job_id="j1", tx=tx.to_xrpl()))
    assert out["ok"] is False and out["refused"] == "wrong_issuer"
    assert out["issuer"] == fake_issuer.classic_address and out["expected"] == config.RLUSD_ISSUER
