"""A04 unit tests: the owner-approved top-up (cereal/topup.py, POST /subagents/{id}/fund) without the network or device.

Every ledger and device call is faked and recorded, so each test can say exactly what would have been signed and sent.
"""
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from xrpl.models.transactions.transaction import Transaction
from xrpl.transaction import sign
from xrpl.wallet import Wallet

from cereal import config, deployments, device, events, keystore, topup

MAIN = "rGP3CdfnKSSz4BYPNTjKiNGzM98xDxbEfj"
DEV = "rn1FZHRNBPX8g2Y5Xzhx1LonhmSheFYMAq"
SUB = "rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR"
SIGNER = Wallet.create()  # stands in for the device's key, so the signed blob is real and has a real hash


class Ledger:
    """What the fakes saw, in order, plus the answers they give."""

    def __init__(self):
        self.order: list[str] = []
        self.signed: list[tuple[Transaction, str | None]] = []
        self.multisigned: list[tuple[Transaction, list]] = []
        self.submitted: list[dict] = []
        self.main_rlusd = Decimal("17")
        self.sub_rlusd = Decimal("0.5")
        self.decision_result = "approve"
        self.trustline_results: list[dict] = []
        self.fund_result: dict | None = None
        self.validated: dict[str, dict] = {}
        self.device_up = True


@pytest.fixture
def led(tmp_path, monkeypatch):
    from cereal import service
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(config, "DEVICE_FUNDING", True)
    monkeypatch.setattr(config, "DEVICE_DECISION", "approve")
    monkeypatch.setattr(config, "LEDGER_ADDRESS", DEV)
    monkeypatch.setattr(config, "MAX_SUBAGENT_BUDGET", 1.0)
    monkeypatch.setattr(config, "MAX_OUTSTANDING_BUDGET", 10.0)
    monkeypatch.setattr(config, "address", lambda role: MAIN)
    monkeypatch.setattr(config, "wallet", lambda role: f"wallet:{role}")
    monkeypatch.setattr(service, "_main_wallet", threading.Lock())  # not the machine-wide lock live runs hold
    monkeypatch.setattr(keystore, "load", lambda dep_id: f"wallet:subagent:{dep_id}")
    L = Ledger()
    monkeypatch.setattr(topup, "client", lambda: object())
    monkeypatch.setattr(topup, "rlusd_balance", lambda c, a: L.main_rlusd if a == MAIN else L.sub_rlusd)
    monkeypatch.setattr(topup, "ledger_index", lambda c: 1000)

    def prepare(tx, c, **kw):
        L.order.append("prepare")
        return Transaction.from_dict({**tx.to_dict(), "sequence": 41, "fee": "24", "last_ledger_sequence": 1150})
    monkeypatch.setattr(topup, "prepare", prepare)
    monkeypatch.setattr(device, "available", lambda: L.device_up)

    def fake_sign(tx, decision=None):
        L.order.append("device_sign")
        L.signed.append((tx, decision))
        screens = ["Transaction Type: Payment", f"Destination: {tx.destination}", f"Amount: {tx.amount.value}"]
        if L.decision_result == "approve" and decision != "reject":
            blob = sign(tx, SIGNER, multisign=True)
            from xrpl.transaction import multisign
            return {"ok": True, "address": DEV, "screens": screens, "signedBlob": multisign(tx, [blob]).blob()}
        return {"ok": False, "result": "owner_rejected", "screens": screens}
    monkeypatch.setattr(device, "sign", fake_sign)

    def fake_multisign(tx, signers, c, **kw):
        L.order.append("trustset")
        L.multisigned.append((tx, signers))
        if L.trustline_results:
            return L.trustline_results.pop(0)
        return {"ok": True, "result": "tesSUCCESS", "hash": f"TL{len(L.multisigned)}", "validated": True}
    monkeypatch.setattr(topup, "multisign_submit", fake_multisign)

    def fake_submit(signed, c, **kw):
        L.order.append("submit")
        L.submitted.append(signed)
        h = Transaction.from_xrpl(__import__("xrpl").core.binarycodec.decode(signed["signedBlob"])).get_hash()
        if L.fund_result is not None:
            return {"hash": h, **L.fund_result}
        L.sub_rlusd += Decimal(str(L.signed[-1][0].amount.value))
        return {"ok": True, "result": "tesSUCCESS", "hash": h, "validated": True, "signed_on": "ledger"}
    monkeypatch.setattr(device, "submit_signed", fake_submit)
    monkeypatch.setattr(topup, "_validated", lambda c, h: L.validated.get(h))
    return L


def _wallet(budget="0.5", **fields):
    d = deployments.create("Funds test", budget, [])
    return deployments.update(d["id"], **{"status": "active", "subwallet": SUB, **fields})


def _nothing_sent(L):
    assert L.signed == [] and L.multisigned == [] and L.submitted == []


# ---- the happy path -------------------------------------------------------------------------

def test_owner_approves_then_the_limit_is_raised_then_the_payment_is_sent(led):
    rec = _wallet("0.5")
    out = topup.fund(rec["id"], "0.25", "req-1", "approve")
    assert out["ok"] and out["amount"] == "0.25" and out["budget"] == "0.75" and out["balance"] == "0.75"
    assert led.order == ["prepare", "device_sign", "trustset", "submit"], "approval first, then the limit, then money"
    pay, decision = led.signed[0]
    assert pay.account == MAIN and pay.destination == SUB and pay.amount.value == "0.25"
    assert pay.amount.currency == config.RLUSD_CURRENCY and pay.source_tag == config.SOURCE_TAG
    assert any('"kind":"topup"' in bytes.fromhex(m.memo_data).decode() for m in pay.memos)
    assert decision == "approve"
    ts, signers = led.multisigned[0]
    assert ts.transaction_type.value == "TrustSet" and ts.account == SUB and ts.limit_amount.value == "0.75"
    assert not ts.flags, "same flags as the lock's TrustSet"
    assert signers == [f"wallet:subagent:{rec['id']}", "wallet:CEREAL_COSIGN"]
    assert out["hashes"]["trustline"] == "TL1" and out["hashes"]["fund"] == out["explorer"]["fund"].rsplit("/", 1)[-1]
    assert out["approval"]["by"] == DEV and out["approval"]["result"] == "approved" and out["approval"]["screens"]
    saved = deployments.get(rec["id"])
    assert saved["budget"] == "0.75" and out["wallet"]["budget"] == "0.75"
    [t] = saved["topups"]
    assert t["amount"] == "0.25" and t["hash"] == out["hashes"]["fund"] and t["trustline_hash"] == "TL1"
    assert t["request_id"] == "req-1" and t["approval"]["screens"] and t["at"]
    assert saved["hashes"]["topup"] == [out["hashes"]["fund"]] and saved["hashes"]["topup_trustline"] == ["TL1"]


def test_a_second_top_up_appends(led):
    rec = _wallet("0.5")
    topup.fund(rec["id"], "0.1", "a")
    out = topup.fund(rec["id"], "0.15", "b")
    assert out["budget"] == "0.75" and led.multisigned[1][0].limit_amount.value == "0.75"
    saved = deployments.get(rec["id"])
    assert [t["amount"] for t in saved["topups"]] == ["0.1", "0.15"] and len(saved["hashes"]["topup"]) == 2


# ---- refusals before anything is signed -----------------------------------------------------

def test_over_the_per_wallet_cap_is_refused_and_nothing_is_sent(led):
    rec = _wallet("0.5")
    out = topup.fund(rec["id"], "10", "req")
    assert out["refused"] == "cap_exceeded" and out["cap"] == "MAX_SUBAGENT_BUDGET"
    assert out["limit"] == "1" and out["room"] == "0.5" and out["requested"] == "10"
    _nothing_sent(led)
    assert deployments.get(rec["id"])["budget"] == "0.5"


def test_over_the_outstanding_cap_is_refused(led, monkeypatch):
    monkeypatch.setattr(config, "MAX_OUTSTANDING_BUDGET", 0.6)
    rec = _wallet("0.5")
    out = topup.fund(rec["id"], "0.25")
    assert out["refused"] == "cap_exceeded" and out["cap"] == "MAX_OUTSTANDING_BUDGET"
    assert out["limit"] == "0.6" and out["outstanding"] == "0.5" and out["room"] == "0.1"
    _nothing_sent(led)


def test_exactly_up_to_the_cap_is_allowed(led):
    rec = _wallet("0.5")
    assert topup.fund(rec["id"], "0.5")["budget"] == "1"


@pytest.mark.parametrize("amount", ["0", "-1", "abc", "0.1234567", "1e-3", "", " ", "NaN", "Infinity", "0x10"])
def test_bad_amounts_are_refused(led, amount):
    rec = _wallet()
    assert topup.fund(rec["id"], amount)["refused"] == "invalid_amount"
    _nothing_sent(led)


def test_only_an_active_unexpired_wallet_can_be_funded(led):
    reclaimed = _wallet(status="reclaimed")
    assert topup.fund(reclaimed["id"], "0.1")["refused"] == "not_active"
    old = _wallet(expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    assert topup.fund(old["id"], "0.1")["refused"] == "expired"
    assert topup.fund("d_nope", "0.1") is None
    _nothing_sent(led)


def test_the_main_wallet_must_hold_the_amount(led):
    led.main_rlusd = Decimal("0.2")
    rec = _wallet()
    out = topup.fund(rec["id"], "0.25")
    assert out["refused"] == "insufficient_main_balance" and out["rlusd"] == "0.2"
    _nothing_sent(led)


def test_no_device_no_top_up(led, monkeypatch):
    rec = _wallet()
    led.device_up = False
    assert topup.fund(rec["id"], "0.25")["refused"] == "device_unavailable"
    monkeypatch.setattr(config, "DEVICE_FUNDING", False)
    assert topup.fund(rec["id"], "0.25")["refused"] == "device_required", "never a top-up from code alone"
    _nothing_sent(led)


# ---- the owner says no, or the ledger does --------------------------------------------------

def test_owner_rejection_sends_nothing_and_is_in_the_security_log(led):
    rec = _wallet()
    out = topup.fund(rec["id"], "0.25", "req", "reject")
    assert out["refused"] == "owner_rejected" and out["sent_transactions"] == 0 and out["screens"]
    assert led.signed[0][1] == "reject" and led.multisigned == [] and led.submitted == []
    saved = deployments.get(rec["id"])
    assert saved["budget"] == "0.5" and not saved.get("topups")
    [f] = saved["refusals"]
    assert f["refused"] == "owner_rejected" and f["rail"] == "topup" and f["amount"] == "0.25"
    [ev] = [e for e in events.feed() if e["deployment"] == rec["id"]]
    assert ev["by"] == "owner" and ev["code"] == "owner_rejected" and ev["outcome"] == "nothing sent"


def test_a_rules_change_waits_while_the_owner_decides(led, monkeypatch):
    from cereal import rules
    rec = _wallet()
    held = []
    sign_ = device.sign
    monkeypatch.setattr(device, "sign", lambda tx, decision=None: held.append(rules._wallet_lock(rec["id"]).locked())
                        or sign_(tx, decision))
    topup.fund(rec["id"], "0.25")
    assert held == [True], "a spend-limit edit cannot rewrite the budget mid top-up"
    assert not rules._wallet_lock(rec["id"]).locked()


def test_manual_mode_ignores_the_api_button(led, monkeypatch):
    monkeypatch.setattr(config, "DEVICE_DECISION", "manual")
    rec = _wallet()
    topup.fund(rec["id"], "0.25", None, "reject")
    assert led.signed[0][1] is None, "a human on the device decides, not the request"


def test_a_trust_line_failure_never_sends_the_payment(led):
    rec = _wallet()
    led.trustline_results = [{"ok": False, "result": "tefBAD_QUORUM", "hash": None}]
    out = topup.fund(rec["id"], "0.25", "req")
    assert out["refused"] == "trustline_failed" and out["result"] == "tefBAD_QUORUM" and out["payment_sent"] is False
    assert led.submitted == [] and deployments.get(rec["id"])["budget"] == "0.5"


def test_a_failed_payment_keeps_the_budget_and_puts_the_limit_back(led):
    rec = _wallet()
    led.fund_result = {"ok": False, "result": "tecPATH_PARTIAL", "validated": True}
    out = topup.fund(rec["id"], "0.25", "req")
    assert out["refused"] == "funding_failed" and out["result"] == "tecPATH_PARTIAL"
    assert [t.limit_amount.value for t, _ in led.multisigned] == ["0.75", "0.5"]
    assert out["trustline_restored"]["ok"] and deployments.get(rec["id"])["budget"] == "0.5"
    assert len(led.submitted) == 1, "never retried"


def test_a_payment_that_validated_as_the_window_closed_counts(led, monkeypatch):
    rec = _wallet()
    led.fund_result = {"ok": False, "result": "tesSUCCESS", "validated": False, "message": "expired before validation"}
    submit = device.submit_signed

    def submit_then_validate(signed, c, **kw):
        r = submit(signed, c, **kw)
        led.validated[r["hash"]] = {"validated": True, "meta": {"TransactionResult": "tesSUCCESS"}}
        return r
    monkeypatch.setattr(device, "submit_signed", submit_then_validate)
    out = topup.fund(rec["id"], "0.25")
    assert out["ok"] and out["budget"] == "0.75" and len(led.multisigned) == 1, "no restore: it settled"


# ---- idempotency ----------------------------------------------------------------------------

def test_the_same_request_id_returns_the_original_result_and_pays_once(led):
    rec = _wallet()
    first = topup.fund(rec["id"], "0.25", "same")
    again = topup.fund(rec["id"], "0.25", "same")
    assert again["replayed"] and again["hashes"] == first["hashes"] and again["budget"] == "0.75"
    assert len(led.signed) == 1 and len(led.submitted) == 1
    assert deployments.get(rec["id"])["budget"] == "0.75", "not 1.0"
    assert topup.fund(rec["id"], "0.250", "same")["replayed"], "the same amount, written differently"


def test_a_replay_past_the_cap_still_returns_the_original(led):
    rec = _wallet("0.5")
    topup.fund(rec["id"], "0.5", "full")
    assert topup.fund(rec["id"], "0.5", "full")["ok"], "the original result, not a cap refusal"
    assert len(led.submitted) == 1


def test_a_request_id_with_a_different_amount_is_refused(led):
    rec = _wallet()
    topup.fund(rec["id"], "0.25", "x")
    assert topup.fund(rec["id"], "0.3", "x")["refused"] == "request_id_reused"
    assert len(led.signed) == 1


def test_a_rejection_replays_without_asking_the_device_again(led):
    rec = _wallet()
    topup.fund(rec["id"], "0.25", "r", "reject")
    again = topup.fund(rec["id"], "0.25", "r", "approve")
    assert again["refused"] == "owner_rejected" and again["replayed"] and len(led.signed) == 1


class _Gate:
    """The main-wallet lock, reporting when a second caller is waiting on it."""

    def __init__(self):
        self.lock, self.callers, self.second_waiting = threading.Lock(), 0, threading.Event()

    def __enter__(self):
        self.callers += 1
        if self.callers > 1:
            self.second_waiting.set()
        self.lock.acquire()
        return self

    def __exit__(self, *exc):
        self.lock.release()


def test_a_twin_sent_while_the_first_waits_on_the_device_gets_the_same_result(led, monkeypatch):
    from cereal import service
    gate, in_device, release = _Gate(), threading.Event(), threading.Event()
    monkeypatch.setattr(service, "_main_wallet", gate)
    sign_ = device.sign

    def slow_owner(tx, decision=None):
        in_device.set()
        assert release.wait(10)
        return sign_(tx, decision)
    monkeypatch.setattr(device, "sign", slow_owner)
    rec = _wallet()
    results = {}
    first = threading.Thread(target=lambda: results.__setitem__("first", topup.fund(rec["id"], "0.25", "twin")))
    twin = threading.Thread(target=lambda: results.__setitem__("twin", topup.fund(rec["id"], "0.25", "twin")))
    first.start()
    assert in_device.wait(10)
    twin.start()
    assert gate.second_waiting.wait(10)  # the twin queues on the main-wallet lock instead of starting its own
    release.set()
    first.join(10); twin.join(10)
    assert results["first"]["ok"] and results["twin"]["replayed"]
    assert results["twin"]["hashes"] == results["first"]["hashes"] and len(led.submitted) == 1
    assert deployments.get(rec["id"])["budget"] == "0.75"


def test_an_interrupted_request_is_settled_from_the_ledger_not_resent(led):
    rec = _wallet()
    deployments.update(rec["id"], fund_requests={"crash": {
        "status": "pending", "amount": "0.25", "hash": "FUNDHASH", "trustline_hash": "TLX", "budget_after": "0.75",
        "last_ledger_sequence": 1150, "approval": {"by": DEV, "result": "approved", "screens": ["Amount: 0.25"]}}})
    out = topup.fund(rec["id"], "0.25", "crash")
    assert out["refused"] == "request_pending" and out["hash"] == "FUNDHASH", "still inside its window: wait"
    led.validated["FUNDHASH"] = {"validated": True, "meta": {"TransactionResult": "tesSUCCESS"}}
    out = topup.fund(rec["id"], "0.25", "crash")
    assert out["ok"] and out["hashes"] == {"trustline": "TLX", "fund": "FUNDHASH"} and out["budget"] == "0.75"
    _nothing_sent(led)
    assert topup.fund(rec["id"], "0.25", "crash")["replayed"]


def test_an_interrupted_request_that_expired_is_closed_and_the_limit_put_back(led):
    rec = _wallet()
    deployments.update(rec["id"], fund_requests={"old": {"status": "pending", "amount": "0.25", "hash": "H",
                                                         "budget_after": "0.75", "last_ledger_sequence": 900}})
    out = topup.fund(rec["id"], "0.25", "old")
    assert out["refused"] == "funding_failed" and out["result"] == "expired" and out["trustline_restored"]["ok"]
    assert [t.limit_amount.value for t, _ in led.multisigned] == ["0.5"], "limit == budget again"
    assert deployments.get(rec["id"])["budget"] == "0.5"
    assert led.signed == [] and led.submitted == []


def test_an_interrupted_request_is_settled_even_once_the_wallet_expired(led):
    rec = _wallet(expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    deployments.update(rec["id"], fund_requests={"late": {"status": "pending", "amount": "0.25", "hash": "LATE",
                                                          "trustline_hash": "TL", "budget_after": "0.75"}})
    led.validated["LATE"] = {"validated": True, "meta": {"TransactionResult": "tesSUCCESS"}}
    out = topup.fund(rec["id"], "0.25", "late")
    assert out["ok"] and out["budget"] == "0.75", "the validated payment is recorded, not refused as expired"


def test_settling_twice_records_the_payment_once(led):
    rec = _wallet()
    first = topup._record_success(rec["id"], "r", "0.25", "0.75", "H1", "TL1", {"by": DEV}, object())
    again = topup._record_success(rec["id"], "r", "0.25", "0.75", "H1", "TL1", {"by": DEV}, object())
    saved = deployments.get(rec["id"])
    assert first["budget"] == again["budget"] == saved["budget"] == "0.75"
    assert len(saved["topups"]) == 1 and saved["hashes"]["topup"] == ["H1"]


def test_a_request_without_an_id_still_gets_one(led):
    rec = _wallet()
    out = topup.fund(rec["id"], "0.25")
    assert out["request_id"].startswith("srv-")
    assert deployments.get(rec["id"])["fund_requests"][out["request_id"]]["status"] == "done"


def test_an_error_before_the_payment_is_a_result_not_a_500(led, monkeypatch):
    rec = _wallet()
    calls = []

    def down(tx, signers, c, **kw):
        calls.append(tx.limit_amount.value)
        raise ConnectionError("rpc down")
    monkeypatch.setattr(topup, "multisign_submit", down)
    out = topup.fund(rec["id"], "0.25", "e")
    assert out["refused"] == "topup_error" and out["payment_sent"] is False and led.submitted == []
    assert calls == ["0.75", "0.5"], "the raise may have landed, so the limit is put back"
    assert deployments.get(rec["id"])["fund_requests"]["e"]["status"] == "done"


def test_an_error_while_submitting_stays_pending_for_the_ledger_to_settle(led, monkeypatch):
    rec = _wallet()
    monkeypatch.setattr(device, "submit_signed", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("no reply")))
    out = topup.fund(rec["id"], "0.25", "p")
    assert out["refused"] == "request_pending" and out["hash"]
    assert deployments.get(rec["id"])["fund_requests"]["p"]["status"] == "pending"
    led.validated[out["hash"]] = {"validated": True, "meta": {"TransactionResult": "tesSUCCESS"}}
    settled = topup.fund(rec["id"], "0.25", "p")
    assert settled["ok"] and settled["hashes"]["fund"] == out["hash"] and len(led.signed) == 1


def test_no_limit_is_recreated_on_a_wallet_that_was_reclaimed(led):
    rec = _wallet()
    deployments.update(rec["id"], status="reclaimed")
    assert topup._restore_limit(rec["id"], object())["skipped"] == "wallet is reclaimed" and led.multisigned == []


# ---- the route ------------------------------------------------------------------------------

def test_the_route(led):
    from fastapi.testclient import TestClient
    from cereal import service
    rec = _wallet()
    http = TestClient(service.app)
    r = http.post(f"/subagents/{rec['id']}/fund", json={"amount": "0.25", "request_id": "h", "speculos_decision": "approve"})
    assert r.status_code == 200 and r.json()["budget"] == "0.75"
    assert http.post("/subagents/d_nope/fund", json={"amount": "0.25"}).status_code == 404
    assert http.post(f"/subagents/{rec['id']}/fund", json={"amount": "0.1", "speculos_decision": "maybe"}).json()["ok"]
    assert led.signed[-1][1] is None, "only approve/reject reach the emulator"
