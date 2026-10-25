"""A04: an owner-approved top-up of an existing subwallet. Never automatic: one explicit request, one Ledger approval.

The budget is the balance, so adding funds means three things stay equal: the record's budget, the subwallet's RLUSD
trust-line limit, and what the main wallet actually sent. In order, all under the main-wallet lock:

  1. the owner approves the main wallet → subwallet RLUSD Payment on the device. Nothing touches the ledger before
     this; a rejection sends nothing.
  2. the subwallet's trust-line limit is raised to exactly the new budget (TrustSet from the subwallet, multi-signed
     by the subagent key + cereal: its master key is disabled and its quorum is 2). If this fails, the payment is
     never submitted.
  3. the device-signed Payment is submitted. Only a validated tesSUCCESS raises the recorded budget.

Idempotency: a request_id is remembered on the wallet's record before the device is asked. Replaying it returns the
original result; a request a crash left unfinished is settled from the ledger by its payment hash, never re-sent.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from xrpl.core.binarycodec import decode
from xrpl.models.requests import Tx
from xrpl.models.transactions import Payment, TrustSet
from xrpl.models.transactions.transaction import Transaction

from . import config, deployments, device, keystore
from .ledger import client, explorer, job_memo, ledger_index, multisign_submit, prepare, rlusd, rlusd_balance, stamp

AMOUNT_RE = re.compile(r"^\d{1,15}(?:\.\d{1,6})?$")  # a plain decimal string, at most 6 decimal places


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def plain(d: Decimal) -> str:
    """A decimal as a plain string, no exponent, no trailing zeros: 0.750 → 0.75, 1.0 → 1, 1E+1 → 10."""
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _refuse(reason: str, **evidence) -> dict:
    from . import service
    return service._refuse(reason, **evidence)


def normalized(amount: str) -> str:
    """The amount as cereal records it ("0.250" → "0.25"); an invalid amount is returned as given."""
    a = str(amount).strip()
    return plain(Decimal(a)) if AMOUNT_RE.match(a) else a


# ---- the two transactions -------------------------------------------------------------------

def topup_payment(main_addr: str, sub_addr: str, amount: str, dep_id: str, tag: str) -> Payment:
    """The main wallet's RLUSD payment the owner approves on the device. Same fields as fund.funding_payment."""
    tx = Payment(account=main_addr, destination=sub_addr, amount=rlusd(amount))
    return stamp(tx, [job_memo(dep_id, tag, kind="topup")])


def limit_trustset(sub_addr: str, limit: str, dep_id: str, tag: str) -> Transaction:
    """The subwallet's RLUSD trust line set to exactly `limit`. Built like the lock's TrustSet (lock.lock_transactions):
    no flags, so the line keeps the state the lock gave it."""
    return stamp(TrustSet(account=sub_addr, limit_amount=rlusd(limit)), [job_memo(dep_id, tag, kind="topup")])


# ---- checks ---------------------------------------------------------------------------------

def check(rec: dict, amount: str) -> dict | None:
    """None if this top-up may be asked for, else the refusal. Reads only cereal's records (no ledger, no lock)."""
    if rec["status"] != "active" or not rec.get("subwallet"):
        return _refuse("not_active", status=rec["status"])
    if datetime.now(timezone.utc) >= datetime.fromisoformat(rec["expires_at"]):
        return _refuse("expired", expires_at=rec["expires_at"])
    if not AMOUNT_RE.match(amount) or Decimal(amount) <= 0:
        return _refuse("invalid_amount", requested=amount,
                       hint="a positive RLUSD amount as a decimal string, at most 6 decimal places")
    amt, budget = Decimal(amount), Decimal(str(rec["budget"]))
    cap = Decimal(str(config.MAX_SUBAGENT_BUDGET))
    if budget + amt > cap:
        return _refuse("cap_exceeded", cap="MAX_SUBAGENT_BUDGET", limit=plain(cap), requested=plain(amt),
                       budget=plain(budget), room=plain(max(cap - budget, Decimal(0))))
    outstanding, ocap = deployments.outstanding_budget(), Decimal(str(config.MAX_OUTSTANDING_BUDGET))
    if outstanding + amt > ocap:
        return _refuse("cap_exceeded", cap="MAX_OUTSTANDING_BUDGET", limit=plain(ocap), requested=plain(amt),
                       outstanding=plain(outstanding), room=plain(max(ocap - outstanding, Decimal(0))))
    return None


# ---- idempotency ----------------------------------------------------------------------------

def _requests(dep_id: str) -> dict:
    return dict((deployments.get(dep_id) or {}).get("fund_requests") or {})


def _remember(dep_id: str, rid: str | None, **fields) -> None:
    """Merge fields into this request's entry. Only called under the main-wallet lock, so entries never race."""
    if not rid:
        return
    reqs = _requests(dep_id)
    reqs[rid] = {**reqs.get(rid, {}), **fields}
    deployments.update(dep_id, fund_requests=reqs)


def _finish(dep_id: str, rid: str | None, out: dict) -> dict:
    """Store the final result for replays (without the wallet snapshot, which goes stale) and return it."""
    _remember(dep_id, rid, status="done", result={k: v for k, v in out.items() if k != "wallet"}, finished_at=_now())
    return out


def replay(dep_id: str, rid: str | None, amount: str, c=None, *, settle: bool = False) -> dict | None:
    """The original result for a request_id seen before, or None to go ahead.

    Outside the lock (settle=False) only a finished request answers; one in flight waits for the lock instead. Under
    the lock (settle=True) a request still marked pending was interrupted (the process died mid-way): it is settled
    from the ledger, never sent again."""
    if not rid:
        return None
    prev = _requests(dep_id).get(rid)
    if not prev:
        return None
    if prev.get("amount") != amount:
        return _refuse("request_id_reused", request_id=rid, amount=prev.get("amount"), requested=amount)
    if prev.get("status") == "done":
        return {**prev["result"], "replayed": True}
    if not settle:
        return None
    return _settle_interrupted(dep_id, rid, prev, c or client())


def _validated(c, tx_hash: str) -> dict | None:
    try:
        r = c.request(Tx(transaction=tx_hash)).result
    except Exception:
        return None
    return r if r.get("validated") else None


def _restore_limit(dep_id: str, c) -> dict:
    """After a raise whose payment never arrived: the subwallet's limit back to the budget it still has (the lock's
    invariant, limit == budget). Only on an active wallet: on a reclaimed one the line is gone and must stay gone."""
    rec = deployments.get(dep_id) or {}
    if rec.get("status") != "active" or not rec.get("subwallet"):
        return {"ok": False, "skipped": f"wallet is {rec.get('status')}"}
    try:
        r = multisign_submit(limit_trustset(rec["subwallet"], plain(Decimal(str(rec["budget"]))), dep_id, rec["tag"]),
                             [keystore.load(dep_id), config.wallet("CEREAL_COSIGN")], c)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    return {k: r.get(k) for k in ("ok", "result", "hash")}


def _settle_interrupted(dep_id: str, rid: str, prev: dict, c) -> dict:
    h = prev.get("hash")
    if not h:  # interrupted before the device signed: no signed payment ever existed
        return _finish(dep_id, rid, _refuse("interrupted", request_id=rid, sent_transactions=0,
                                            note="interrupted before the owner's approval; nothing was sent"))
    r = _validated(c, h)
    if r:
        res = r.get("meta", {}).get("TransactionResult")
        if res == "tesSUCCESS":
            return _finish(dep_id, rid, _record_success(dep_id, rid, prev["amount"], prev["budget_after"], h,
                                                        prev.get("trustline_hash"), prev.get("approval") or {}, c))
        return _finish(dep_id, rid, _refuse("funding_failed", request_id=rid, result=res, hash=h, explorer=explorer(h),
                                            trustline_restored=_restore_limit(dep_id, c)))
    lls = prev.get("last_ledger_sequence")
    if lls and ledger_index(c) > int(lls):  # past its LastLedgerSequence and not validated: it can never apply
        return _finish(dep_id, rid, _refuse("funding_failed", request_id=rid, result="expired", hash=h,
                                            trustline_restored=_restore_limit(dep_id, c),
                                            note="the approved payment expired without validating; nothing was sent"))
    return _refuse("request_pending", request_id=rid, hash=h, explorer=explorer(h), last_ledger_sequence=lls,
                   note="an earlier attempt with this request_id may still validate; nothing new was sent")


# ---- the top-up -----------------------------------------------------------------------------

def fund(dep_id: str, amount: str, request_id: str | None = None, speculos_decision: str | None = None) -> dict | None:
    """Top up an active wallet by `amount` RLUSD with the owner's Ledger approval. None if the wallet is unknown."""
    from . import service
    amount = normalized(amount)
    # Every top-up gets an id, so even a caller that sent none can be settled from the ledger after a crash.
    rid = (request_id or "").strip()[:100] or f"srv-{uuid.uuid4().hex}"
    out = replay(dep_id, rid, amount)
    if out:
        return out
    rec = deployments.get(dep_id)
    if not rec:
        return None
    if rid not in _requests(dep_id):  # a request seen before is settled under the lock, whatever the wallet is now
        refused = check(rec, amount)
        if refused:
            return replay(dep_id, rid, amount) or refused  # a twin request may have finished meanwhile
        if not config.DEVICE_FUNDING:
            return _device_required()
    c = client()
    with service._main_wallet:
        out = replay(dep_id, rid, amount, c, settle=True)
        if out:
            return out
        rec = deployments.get(dep_id)
        refused = check(rec, amount)  # again under the lock: another top-up or deployment may have used the room
        if refused:
            return refused
        if not config.DEVICE_FUNDING:
            return _device_required()
        main_addr = config.address("TREASURY")
        held = rlusd_balance(c, main_addr)
        if held < Decimal(amount):
            return _refuse("insufficient_main_balance", rlusd=plain(held), requested=amount)
        if not device.available():
            return _refuse("device_unavailable", speculos=config.SPECULOS_URL,
                           hint="start the device (docker start speculos-xrp)")
        _remember(dep_id, rid, status="pending", amount=amount, at=_now())
        state = {"trustline": False, "submitting": False}
        try:
            return _finish(dep_id, rid, _approve_raise_send(rec, rid, amount, main_addr, speculos_decision, c, state))
        except Exception as e:  # report, never 500 with the outcome unknown
            error = f"{type(e).__name__}: {e}"[:300]
            if state["submitting"]:  # the payment may be on its way: keep it pending, settle it from the ledger later
                return _refuse("request_pending", request_id=rid, error=error,
                               hash=_requests(dep_id).get(rid, {}).get("hash"))
            out = _refuse("topup_error", request_id=rid, error=error, payment_sent=False)
            if state["trustline"]:  # the raise may have landed; the payment never left: limit back to the budget
                out["trustline_restored"] = _restore_limit(dep_id, c)
            return _finish(dep_id, rid, out)


def _device_required() -> dict:
    return _refuse("device_required", hint="a top-up is the owner's action on the Ledger: set CEREAL_DEVICE_FUNDING=1")


def _approve_raise_send(rec: dict, rid: str | None, amount: str, main_addr: str, decision: str | None, c,
                        state: dict) -> dict:
    dep_id, sub, tag = rec["id"], rec["subwallet"], rec["tag"]
    old_budget = Decimal(str(rec["budget"]))
    new_budget = plain(old_budget + Decimal(amount))
    # 1. the owner approves first. The Payment takes the main wallet's next Sequence (nothing else uses it while we
    #    hold the lock) and a window long enough for a human, the TrustSet and the submit.
    pay = prepare(topup_payment(main_addr, sub, amount, dep_id, tag), c, signers_count=1,
                  window=config.DEVICE_WINDOW_LEDGERS)
    signed = device.sign(pay, None if config.DEVICE_DECISION == "manual" else decision)
    approval = {"by": signed.get("address") or config.LEDGER_ADDRESS,
                "result": "approved" if signed.get("ok") else signed.get("result"), "screens": signed.get("screens", [])}
    if not signed.get("ok"):
        code = signed.get("result") or "device_error"
        if code == "owner_rejected":  # the security log shows the owner's no (cereal/events.py reads refusals)
            deployments.record_refusal(dep_id, {"payee": sub, "amount": amount, "rail": "topup", "ok": False,
                                                "refused": code, "approval": approval, "request_id": rid, "at": _now()})
        return _refuse(code, deployment=dep_id, requested=amount, approval=approval, screens=approval["screens"],
                       sent_transactions=0, error=str(signed.get("error") or "")[-300:] or None)
    fund_hash = Transaction.from_xrpl(decode(signed["signedBlob"])).get_hash()
    _remember(dep_id, rid, hash=fund_hash, last_ledger_sequence=pay.last_ledger_sequence, approval=approval,
              budget_after=new_budget)
    # 2. raise the limit to exactly the new budget, or send nothing
    state["trustline"] = True
    tl = multisign_submit(limit_trustset(sub, new_budget, dep_id, tag),
                          [keystore.load(dep_id), config.wallet("CEREAL_COSIGN")], c)
    if not tl.get("ok"):
        return _refuse("trustline_failed", deployment=dep_id, requested=amount, result=tl.get("result"), trustline=tl,
                       approval=approval, payment_sent=False)
    _remember(dep_id, rid, trustline_hash=tl["hash"])
    # 3. the payment the owner approved
    state["submitting"] = True
    funded = device.submit_signed(signed, c)
    if not funded.get("ok") and funded.get("hash"):  # it may have validated as the window closed: ask once more
        r = _validated(c, funded["hash"])
        if r and r.get("meta", {}).get("TransactionResult") == "tesSUCCESS":
            funded = {**funded, "ok": True, "result": "tesSUCCESS", "validated": True}
    if not funded.get("ok"):
        # nothing arrived: put the limit back to the budget the wallet still has (the lock's invariant), and say so
        return _refuse("funding_failed", deployment=dep_id, requested=amount, result=funded.get("result"),
                       funding={k: funded.get(k) for k in ("result", "hash", "explorer", "validated", "message")},
                       trustline_hash=tl["hash"], trustline_restored=_restore_limit(dep_id, c), approval=approval)
    return _record_success(dep_id, rid, amount, new_budget, funded["hash"], tl["hash"], approval, c)


def _record_success(dep_id: str, rid: str | None, amount: str, new_budget: str, fund_hash: str, tl_hash: str | None,
                    approval: dict, c) -> dict:
    """Record a validated top-up once: settling the same payment again (after a crash mid-record) adds nothing."""
    rec = deployments.get(dep_id)
    entry = next((t for t in rec.get("topups") or [] if t.get("hash") == fund_hash), None)
    if entry is None:
        entry = {"amount": amount, "hash": fund_hash, "trustline_hash": tl_hash, "at": _now(),
                 "approval": {"by": approval.get("by"), "result": approval.get("result", "approved"),
                              "screens": approval.get("screens", [])},
                 "request_id": rid, "budget_after": new_budget}
        rec = deployments.update(dep_id, budget=new_budget, topups=[*(rec.get("topups") or []), entry])
    hashes = rec.get("hashes") or {}
    if fund_hash not in (hashes.get("topup") or []):
        rec = deployments.merge_hashes(dep_id, topup=[*(hashes.get("topup") or []), fund_hash],
                                       topup_trustline=[*(hashes.get("topup_trustline") or []), tl_hash])
    try:
        balance = str(rlusd_balance(c, rec["subwallet"]))
    except Exception:
        balance = None
    return {"ok": True, "deployment": dep_id, "amount": amount, "budget": new_budget, "balance": balance,
            "hashes": {"trustline": tl_hash, "fund": fund_hash},
            "explorer": {"trustline": explorer(tl_hash) if tl_hash else None, "fund": explorer(fund_hash)},
            "approval": entry["approval"], "request_id": rid, "wallet": {**deployments.public(rec), "balance": balance}}
