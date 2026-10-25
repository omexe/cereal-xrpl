"""p1.4 — the cereal service: the only process that holds the main-wallet key and the co-signer key.

The main agent calls this API; it never signs. Run: uvicorn cereal.service:app --port 8001
Endpoints: GET /health · GET /main · POST /subagents · GET /subagents · GET /subagents/{id} ·
POST /subagents/{id}/done · POST /subagents/{id}/reclaim · POST /subagents/{id}/retire · POST /cosign
Every ledger action returns the Result shape; refusals are results, never exceptions.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import Tx
from xrpl.models.transactions.transaction import Transaction
from xrpl.wallet import Wallet

from . import ap4m, config, deployments, device, directory, keystore, subwallets, vendors
from .burn import reclaim as ledger_reclaim, retire as ledger_retire
from .fund import fund_burner, funding_payment
from .xlock import ProcessLock
from .ledger import account_info, client, cosign_and_submit, cosign_combine, decode_memos, prepare, rlusd_balance, submit_capture

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(_app):
    if __import__("os").getenv("CEREAL_SWEEPER", "1") != "0":  # the sweeper (defined below) starts with the service
        threading.Thread(target=_sweeper_loop, daemon=True, name="cereal-sweeper").start()
    yield


app = FastAPI(title="cereal service", lifespan=_lifespan)
_main_wallet = ProcessLock("treasury")  # one main-wallet transaction sequence at a time, across every local service


class DeployRequest(BaseModel):
    task: str
    budget: str
    allowed_payees: list[str] = []  # optional narrower filter; empty = any vendor credentialed for vendor_class
    expires_in_hours: float = 24
    vendor_class: str = "data"
    # Speculos demos only: which button the emulated owner presses (approve | reject). Ignored when a human is
    # driving the device (CEREAL_DEVICE_DECISION=manual); a real device always waits for its owner.
    speculos_decision: str | None = None
    # Part 5: the quote-based plan behind this budget (chosen vendor and price, fallbacks, skipped vendors and why)
    plan: dict | None = None
    # Part 5: payments above this many RLUSD need the owner's Ledger instead of cereal (None = company default only)
    approval_threshold: str | None = None
    sweep_when_done: bool = False            # leftovers go home automatically when the subagent reports done
    buy_only: bool = False                   # a planned task: cereal co-signs only x402 purchases, no direct payments
    name: str | None = None                  # the wallet's name, e.g. "Market Sizing"
    folder: str | None = None                # the design's folders (e.g. "Market Research"); shows in the export
    sentence: str | None = None              # the plain-English sentence it was created from
    speculos_payment_decision: str | None = None  # Speculos demos only: the owner's button for large payments
    # R03: the caller's idempotency key (e.g. a UUID per click). A repeat returns the first request's outcome
    # (same deployment, `replayed: true`) and sends nothing new. Stored on the record.
    request_id: str | None = None


class WalletRequest(BaseModel):
    sentence: str
    folder: str | None = None
    speculos_decision: str | None = None          # Speculos demos only: the owner's button for the budget
    speculos_payment_decision: str | None = None  # ... and for payments above the threshold
    card_digest: str | None = None  # R07: the digest of the card the owner reviewed; a rebuilt card that differs is refused
    request_id: str | None = None   # R03: a client-generated id; repeating it returns the original outcome, never a 2nd wallet


class VendorIssueRequest(BaseModel):
    vendor_class: str = "data"
    days: float | None = None


class VendorRevokeRequest(BaseModel):
    reason: str
    report: str = ""
    vendor_class: str = "data"


class CosignRequest(BaseModel):
    deployment_id: str | None = None
    job_id: str | None = None  # legacy single-job path (cereal/demo.py)
    tx: dict
    # Part 4 (x402): co-sign but do NOT submit; return the signed blob for the vendor's facilitator to submit.
    present: bool = False
    resource: str | None = None  # the URL being bought, for the record


class Ap4mRequest(BaseModel):
    resource: str
    max_rlusd: str = "0.25"  # the most this subagent will pay for the resource


class ChatRequest(BaseModel):
    message: str
    folder: str | None = None


class EventReport(BaseModel):
    kind: str            # hijack_alone | stolen_keys_drain | stolen_keys_main_wallet | prove_lock
    result: str          # the ledger's code, e.g. tefBAD_QUORUM, tecPATH_PARTIAL, tefBAD_SIGNATURE
    hash: str | None = None
    detail: dict | None = None


class DoneRequest(BaseModel):
    summary: str


def _refuse(reason: str, **evidence) -> dict:
    return {"ok": False, "refused": reason, **evidence}


def _with_balance(rec: dict) -> dict:
    out = deployments.public(rec)
    if rec.get("subwallet") and rec["status"] in ("active", "deploying"):
        try:
            out["balance"] = str(rlusd_balance(client(), rec["subwallet"]))
        except Exception:
            out["balance"] = None
    else:
        out["balance"] = "0"
    return out


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "main": config.address("TREASURY"), "cosigner": config.address("CEREAL_COSIGN")}


@app.get("/main")
def main_wallet() -> dict:
    c = client(); addr = config.address("TREASURY")
    return {"address": addr, "xrp": str(int(account_info(c, addr)["Balance"]) / 1_000_000),
            "rlusd": str(rlusd_balance(c, addr)), "outstanding_budget": str(deployments.outstanding_budget()),
            "active_subagents": len(deployments.active()),
            "recent_sweeps": recent_sweeps(5),
            "policy": {"vendor_credentials": config.REQUIRE_VENDOR_CREDENTIAL, "issuer": config.address("CREDENTIAL_ISSUER"),
                       "device_funding": config.DEVICE_FUNDING, "ledger_recovery": config.LEDGER_RECOVERY,
                       "device": config.LEDGER_ADDRESS, "ap4m": {"enabled": config.AP4M_ENABLED, **ap4m.available()}},
            "caps": {"MAX_SUBAGENT_BUDGET": config.MAX_SUBAGENT_BUDGET,
                     "MAX_OUTSTANDING_BUDGET": config.MAX_OUTSTANDING_BUDGET,
                     "MAX_ACTIVE_SUBAGENTS": config.MAX_ACTIVE_SUBAGENTS}}


MAX_REQUEST_ID = 128


def _request_terms(req: DeployRequest) -> dict:
    """R03: the terms a deploy request asks for, kept on the record so a repeat is compared with the request as it was
    sent (a later top-up or rules edit of the wallet is not a conflict)."""
    return {"task": req.task, "budget": str(req.budget), "allowed_payees": sorted(req.allowed_payees),
            "vendor_class": req.vendor_class, "expires_in_hours": req.expires_in_hours,
            "approval_threshold": req.approval_threshold, "sweep_when_done": bool(req.sweep_when_done)}


def _same_term(key: str, a, b) -> bool:
    if key == "allowed_payees":
        return sorted(a or []) == sorted(b or [])
    if key in ("budget", "expires_in_hours", "approval_threshold"):
        if a in (None, "") or b in (None, ""):
            return a in (None, "") and b in (None, "")
        try:
            return Decimal(str(a)) == Decimal(str(b))
        except ArithmeticError:  # decimal.InvalidOperation
            return False
    return a == b


def _request_conflict(rec: dict, req: DeployRequest) -> list[str]:
    """R03: the terms where a repeat of a request_id differs from the request that used it first."""
    first = rec.get("deploy_request") or {"budget": rec["budget"], "allowed_payees": rec.get("allowed_payees") or [],
                                          "vendor_class": rec.get("vendor_class", "data")}
    now = _request_terms(req)
    return [k for k, v in first.items() if not _same_term(k, v, now.get(k))]


def _replay(rec: dict, req: DeployRequest) -> dict:
    """R03: the outcome of the deploy that already used this request_id. Nothing is signed or sent."""
    differs = _request_conflict(rec, req)
    if differs:
        return _refuse("request_id_reused", request_id=req.request_id, deployment=rec["id"], differs=differs,
                       sent_transactions=0, hint="this request_id already deployed a different request; send a new one")
    if rec.get("outcome"):  # a refusal that created the record (rejected on the device, lock or funding failed, ...)
        return {**rec["outcome"], "replayed": True}
    if rec["status"] == "deploying":  # still running, or stopped by a crash or restart: never deployed a second time
        return _refuse("in_progress", request_id=req.request_id, deployment=rec["id"], status="deploying",
                       subwallet=rec.get("subwallet"), hashes=rec.get("hashes") or {}, replayed=True,
                       hint="the deploy with this request_id has not finished; nothing new was sent")
    if rec["status"] in ("rejected", "failed"):
        return _refuse(rec["status"], deployment=rec["id"], replayed=True)
    return {"ok": True, **_with_balance(rec), "replayed": True}


@app.post("/subagents")
def deploy(req: DeployRequest) -> dict:
    """Deploy a subagent into a new locked subwallet funded with exactly its budget.

    Caps (R02): checked once early (a fast refusal) and again inside the main-wallet lock, where the check and the
    `deploying` record are one locked write (deployments.reserve), so concurrent deploys never both pass a stale count.

    Idempotency (R03): the request_id is on the record from its first write. A repeat returns the first request's
    outcome (same deployment, `replayed: true`), including refusals that created a record (rejected, failed), and sends
    nothing new; a repeat with different terms is refused `request_id_reused`. A concurrent twin is refused
    `in_progress` at once (as POST /wallets does), so no request thread waits out another's device approval; asking
    again once the first has finished replays its outcome. A record left `deploying` by a crash or restart stays
    `in_progress` and is never deployed again. Refusals that created no record (caps, balances, device unavailable,
    an error before anything reached the ledger) are evaluated afresh on a repeat; nothing was sent for them.
    """
    if req.request_id and len(req.request_id) > MAX_REQUEST_ID:
        return _refuse("invalid_request_id", max_length=MAX_REQUEST_ID)
    prior = deployments.find_request(req.request_id)
    if prior:  # finished, refused, a conflict or still deploying: answered now, without the main-wallet lock
        return _replay(prior, req)
    refused = deployments.check_caps(req.budget)
    if refused:
        return refused
    payees = list(req.allowed_payees)
    if not payees and not config.REQUIRE_VENDOR_CREDENTIAL:
        return _refuse("no_payee_policy", hint="vendor credentials are off: pass allowed_payees")
    c = client(); main_addr = config.address("TREASURY")
    with _main_wallet:
        prior = deployments.find_request(req.request_id)
        if prior:  # a twin reserved it while this one waited on the lock
            return _replay(prior, req)
        if rlusd_balance(c, main_addr) < Decimal(req.budget):
            return _refuse("insufficient_main_balance", rlusd=str(rlusd_balance(c, main_addr)), requested=req.budget)
        if Decimal(int(account_info(c, main_addr)["Balance"])) / 1_000_000 < subwallets.activation_xrp(c) + 1:
            return _refuse("insufficient_main_xrp")
        if config.DEVICE_FUNDING and not device.available():
            return _refuse("device_unavailable", speculos=config.SPECULOS_URL,
                           hint="start the device (docker start speculos-xrp) or set CEREAL_DEVICE_FUNDING=0")
        rec = deployments.reserve(
            req.task, req.budget, payees, req.expires_in_hours, req.vendor_class, request_id=req.request_id or None,
            deploy_request=_request_terms(req) if req.request_id else None, plan=req.plan or None,
            approval_threshold=req.approval_threshold, name=req.name, folder=req.folder, sentence=req.sentence,
            sweep_when_done=req.sweep_when_done or None, speculos_payment_decision=req.speculos_payment_decision,
            buy_only=req.buy_only or None)
        if rec.get("refused"):  # a cap (no record, no transaction), or the request_id taken outside this lock
            prior = rec.get("refused") == "duplicate_request" and deployments.get(rec["deployment"])
            return _replay(prior, req) if prior else rec
        try:  # nothing in here reaches the ledger: on an error the reservation is undone and a retry starts afresh
            sub_key = keystore.new_subagent_key(rec["id"])
            deployments.update(rec["id"], subagent=sub_key)
            sub = Wallet.create()  # the subwallet's address exists before anything is on-ledger, so the owner sees it
            approval = None
            if config.DEVICE_FUNDING:
                # Part 3: the owner approves the budget on the device FIRST. The funding Payment takes the main wallet's
                # next-but-one Sequence (activation takes the next), is signed now and submitted after the lock.
                seq = int(account_info(c, main_addr)["Sequence"])
                pay = funding_payment(main_addr, sub.classic_address, req.budget, rec["id"], rec["tag"])
                pay = Transaction.from_dict({**pay.to_dict(), "sequence": seq + 1})
                decision = None if config.DEVICE_DECISION == "manual" else req.speculos_decision
                approval = device.sign(prepare(pay, c, signers_count=1, window=config.DEVICE_WINDOW_LEDGERS), decision)
                deployments.update(rec["id"], approval={
                    "by": approval.get("address") or config.LEDGER_ADDRESS,
                    "result": "approved" if approval.get("ok") else approval.get("result"),
                    "screens": approval.get("screens", [])})
        except Exception as e:
            if not deployments.release(rec["id"]):
                raise
            return _refuse("deploy_error", error=type(e).__name__, sent_transactions=0,
                           hint="stopped before anything reached the ledger; nothing was sent")
        if approval is not None and not approval.get("ok"):
            out = _refuse(approval.get("result") or "device_error", deployment=rec["id"],
                          screens=approval.get("screens", []), sent_transactions=0)
            deployments.update(rec["id"], status="rejected" if approval.get("result") == "owner_rejected" else "failed",
                               outcome=out)
            return out
        funded = None
        try:  # from here the ledger may be touched: an error keeps the record (and its cap slot) with what it reached
            deployments.update(rec["id"], subwallet=sub.classic_address)  # on the record before activation is sent
            made = subwallets.create(rec["id"], rec["tag"], req.budget, sub_key, c, sub=sub)
            del sub
            deployments.merge_hashes(rec["id"], activate=made["hashes"]["activate"], lock=made["hashes"]["lock"])
            if not made["ok"]:
                out = _refuse("subwallet_failed", deployment=rec["id"], error=made.get("error"))
                deployments.update(rec["id"], status="failed", outcome=out)
                return out
            if approval:
                funded = device.submit_signed(approval, c)
            else:
                funded = fund_burner(config.wallet("TREASURY"), made["address"], req.budget, rec["id"], rec["tag"], c)
            deployments.merge_hashes(rec["id"], fund=funded.get("hash"))
            if not funded.get("ok"):
                out = _refuse("funding_failed", deployment=rec["id"], result=funded)
                deployments.update(rec["id"], status="failed", outcome=out)
                return out
            rec = deployments.update(rec["id"], status="active")
        except Exception as e:
            if funded is not None and funded.get("ok"):  # funded and validated: only the record lagged behind
                return {"ok": True, **_with_balance(deployments.update(rec["id"], status="active"))}
            now = deployments.get(rec["id"]) or rec
            out = _refuse("deploy_interrupted", deployment=rec["id"], status=now["status"], subwallet=now.get("subwallet"),
                          hashes=now.get("hashes") or {}, error=type(e).__name__,
                          hint="stopped once the ledger may have been touched: check the subwallet and these hashes on "
                               "the explorer (the owner's Ledger can recover it). It keeps its cap slot and is never "
                               "deployed again")
            deployments.update(rec["id"], outcome=out)
            return out
    return {"ok": True, **_with_balance(rec)}


@app.post("/wallets/preview")
def wallet_preview(req: WalletRequest) -> dict:
    """Part 5: a plain-English sentence → the limits card the owner confirms, with the `digest` of what it enforces
    (R07: pass it back as `card_digest` when creating). Reads only; signs and sends nothing."""
    from . import wallet_card
    return wallet_card.build_card(req.sentence)


@app.post("/wallets")
def wallet_create(req: WalletRequest) -> dict:
    """Create a disposable wallet from a sentence. The card is rebuilt here from the sentence (a client's copy of the
    card is never trusted), refused if it has problems, then deployed with the owner's Ledger approval as usual.

    R07: with `card_digest`, the reviewed reading of the sentence is reused and everything else is checked again; a card
    that now differs from the one the owner reviewed is refused `card_changed`, with the new card to review, and nothing
    is sent. Without it the card is rebuilt from scratch and used (the chat flow, the CLI).
    R03: with `request_id`, a repeat returns the first outcome (same wallet id, `replayed: true`, its current status),
    including a refusal that left a record (owner_rejected); a concurrent twin is refused `in_progress`. A deploy that
    raised after its record existed is kept as `deploy_interrupted` on that record, so a retry never deploys again."""
    from . import wallet_card
    rid = req.request_id
    if rid:
        with wallet_card.requests_lock:
            prior = wallet_card.find_request(rid)
            if prior is None:
                if rid in wallet_card.in_progress:
                    return _refuse("in_progress", request_id=rid, hint="this wallet is being created; nothing new was sent")
                wallet_card.in_progress.add(rid)
        if prior is not None:
            if prior["status"] == "deploying" and "card" not in prior:  # deploy() writes request_id first; card after
                return _refuse("in_progress", request_id=rid, deployment=prior["id"], status=prior["status"],
                               hint="this wallet is being created; nothing new was sent")
            same = prior.get("sentence") == req.sentence and (prior.get("folder") or None) == (req.folder or None) \
                and (not req.card_digest or req.card_digest == prior.get("card_digest"))
            if not same:
                return _refuse("request_id_reused", request_id=rid, deployment=prior["id"], sent_transactions=0)
            if prior.get("create_refusal"):
                return {**prior["create_refusal"], "card": prior.get("card"), "replayed": True}
            return {"ok": True, **_with_balance(prior), "replayed": True}
    try:
        card = wallet_card.build_card(req.sentence, reviewed=req.card_digest) if req.card_digest \
            else wallet_card.build_card(req.sentence)
        if req.card_digest and card.get("digest") != req.card_digest:
            return _refuse("card_changed", card=card, reviewed_digest=req.card_digest, sent_transactions=0)
        if not card["ok"]:
            return _refuse("card_problems", problems=card["problems"], card=card)
        before = {r["id"] for r in deployments.all_()}
        try:
            out = deploy(DeployRequest(task=card["name"], budget=card["budget"], allowed_payees=card["allowed_payees"],
                                       expires_in_hours=card["expires_in_hours"],
                                       approval_threshold=card["approval_threshold"],
                                       sweep_when_done=card["sweep_when_done"], name=card["name"], sentence=req.sentence,
                                       folder=req.folder,
                                       speculos_decision=req.speculos_decision,
                                       speculos_payment_decision=req.speculos_payment_decision, request_id=rid))
        except Exception as e:
            made = [r for r in deployments.all_() if r["id"] not in before and r.get("sentence") == req.sentence
                    and not r.get("request_id")]
            if not made:
                raise  # nothing was recorded, so nothing can have been sent: a retry starts afresh
            # Stopped partway: how far it got is on the record (hashes, status). Never retried, never claimed settled.
            out = _refuse("deploy_interrupted", deployment=made[-1]["id"], status=made[-1]["status"],
                          error=f"{type(e).__name__}: {e}"[:300],
                          hint="check the record's hashes on the explorer before creating another wallet")
        dep_id = out.get("id") if out.get("ok") else out.get("deployment")
        if not dep_id:  # refused before any record existed (caps, balance, device): a retry is evaluated afresh
            return {**out, "card": card}
        # The card the owner confirmed, and the request that made this record (successes and refusals alike).
        kept = {"card": card, "card_digest": card.get("digest"), **({"request_id": rid} if rid else {}),
                **({} if out.get("ok") else {"create_refusal": out})}
        deployments.update(dep_id, **kept)
        return {**out, **{k: v for k, v in kept.items() if k != "create_refusal"}}
    finally:
        if rid:
            with wallet_card.requests_lock:
                wallet_card.in_progress.discard(rid)


@app.get("/subagents")
def list_subagents() -> list[dict]:
    return [_with_balance(r) for r in deployments.all_()]


@app.get("/subagents/{dep_id}")
def get_subagent(dep_id: str) -> dict:
    rec = deployments.get(dep_id)
    if not rec:
        raise HTTPException(404, "unknown deployment")
    return _with_balance(_resolve_presented(rec))


@app.post("/subagents/{dep_id}/done")
def done(dep_id: str, req: DoneRequest) -> dict:
    rec = deployments.get(dep_id)
    if not rec:
        raise HTTPException(404, "unknown deployment")
    rec = deployments.update(dep_id, summary=req.summary, finished_at=datetime.now(timezone.utc).isoformat())
    if rec.get("sweep_when_done") and rec["status"] == "active":  # "sweep back when done"
        return {**rec, "swept": reclaim(dep_id)}
    return rec


@app.post("/subagents/{dep_id}/reclaim")
def reclaim(dep_id: str) -> dict:
    rec = deployments.get(dep_id)
    if not rec or rec["status"] != "active":
        return _refuse("not_active", status=rec and rec["status"])
    c = client()
    before = rlusd_balance(c, rec["subwallet"])
    # Part 1: the service loads the subagent's key from the local keystore to co-sign the sweep.
    # Part 3 replaces this with the owner's Ledger (weight 2) signing alone.
    steps = ledger_reclaim(rec["subwallet"], config.address("TREASURY"), keystore.load(dep_id),
                           config.wallet("CEREAL_COSIGN"), c, rec["id"], rec["tag"])
    deployments.merge_hashes(dep_id, reclaim=[r.get("hash") for _, r in steps])
    ok = all(r.get("ok") for _, r in steps)
    if ok:
        deployments.update(dep_id, status="reclaimed", returned=str(before),
                           reclaimed_at=datetime.now(timezone.utc).isoformat())
    out = {"ok": ok, "returned": str(before), "steps": [{"step": n, **r} for n, r in steps]}
    closed = close_ap4m_channel(dep_id)
    if closed:
        out["ap4m"] = closed
    return out


def close_ap4m_channel(dep_id: str) -> dict | None:
    """Part 4b: a finished subagent's AP4M Channel is closed with the rest of it. Record every redemption from the chain
    first, then close, so the unused cap returns to the team's AP4M budget. Returns None if it never used AP4M."""
    channel = ap4m.channel_for_job(dep_id)
    if not channel:
        return None
    added = reconcile_ap4m(dep_id)
    res = ap4m.close(channel)
    if not res.get("ok") and ap4m.channel_state(channel).get("status") == 2:
        res = {**res, "ok": True, "note": "closed on-chain; the service's reply was lost"}  # seen live: "fetch failed"
    if res.get("ok"):
        deployments.merge_hashes(dep_id, ap4m_close=res.get("tx_hash"))
        ap4m.forget_job(dep_id)
    return {"channel_id": channel, "recorded": len(added), **{k: res.get(k) for k in ("ok", "tx_hash", "error")}}


@app.post("/subagents/{dep_id}/retire")
def retire(dep_id: str) -> dict:
    rec = deployments.get(dep_id)
    if not rec or rec["status"] not in ("reclaimed", "recovered"):
        return _refuse("not_reclaimed", status=rec and rec["status"])
    r = ledger_retire(rec["subwallet"], config.address("TREASURY"), keystore.load(dep_id),
                      config.wallet("CEREAL_COSIGN"), client(), rec["id"], rec["tag"])
    if r.get("ok"):
        deployments.merge_hashes(dep_id, retire=r.get("hash"))
        deployments.update(dep_id, status="retired")
    return r


TF_PARTIAL_PAYMENT = 0x00020000


def ap4m_spent(rec: dict) -> Decimal:
    """RLUSD this subagent already spent on the AP4M rail (paid from the team's AP4M vault, not its subwallet)."""
    return sum((Decimal(str(p["amount"])) for p in rec.get("payments", []) if p.get("rail") == "ap4m" and p.get("ok")),
               Decimal(0))


def _payment_shape_refusal(tx_json: dict, amt) -> dict | None:
    """Only plain, exact RLUSD payments: no partial payments, no paths, SendMax (x402 sets it) at most the Amount."""
    if int(tx_json.get("Flags", 0) or 0) & TF_PARTIAL_PAYMENT:
        return _refuse("partial_payment_not_allowed")
    if tx_json.get("Paths") or tx_json.get("DeliverMin"):
        return _refuse("paths_not_allowed")
    sm = tx_json.get("SendMax")
    if sm is not None:
        if not isinstance(sm, dict) or sm.get("currency") != amt.currency or sm.get("issuer") != amt.issuer \
                or Decimal(str(sm.get("value"))) > Decimal(amt.value):
            return _refuse("send_max_not_allowed", send_max=sm, amount=amt.value)
    return None


def _resolve_presented(rec: dict) -> dict:
    """x402 payments are submitted by the vendor's facilitator; read their outcome from the ledger, not from anyone's word."""
    pending = [p for p in rec.get("payments", []) if p.get("result") == "presented" and p.get("hash")]
    if not pending:
        return rec
    c = client()
    for p in pending:
        try:
            r = c.request(Tx(transaction=p["hash"])).result
        except Exception:
            continue
        if r.get("validated"):
            res = r.get("meta", {}).get("TransactionResult")
            deployments.update_payment(rec["id"], p["hash"], result=res, ok=res == "tesSUCCESS", validated=True)
    return deployments.get(rec["id"])


def _approval_threshold(rec: dict) -> Decimal | None:
    """The lower of the wallet's own threshold and the company default; None when neither is set."""
    vals = [Decimal(str(v)) for v in (rec.get("approval_threshold"), config.APPROVAL_THRESHOLD) if v not in (None, "")]
    return min(vals) if vals else None


def _owner_approves_payment(rec: dict, agent_signed: Transaction, amt, threshold: Decimal, present: bool,
                            resource: str | None) -> dict:
    """A payment above the threshold passed every policy check; cereal does NOT co-sign it. The owner's Ledger is
    asked instead: it shows the payment, and if approved its signature (weight 2) joins the subagent's (weight 1)."""
    from xrpl.core.binarycodec import decode
    from xrpl.transaction import multisign
    c = client()
    if not device.available():
        return _refuse("device_unavailable", requested=amt.value, threshold=str(threshold))
    d = agent_signed.to_dict(); d.pop("signers", None)
    base = Transaction.from_dict(d)
    decision = None if config.DEVICE_DECISION == "manual" else rec.get("speculos_payment_decision")
    signed = device.sign(base, decision)
    approval = {"by": signed.get("address") or config.LEDGER_ADDRESS, "threshold": str(threshold),
                "result": "approved" if signed.get("ok") else signed.get("result"), "screens": signed.get("screens", [])}
    if not signed.get("ok"):
        return _refuse(signed.get("result") or "device_error", requested=amt.value, threshold=str(threshold),
                       approval=approval, sent_transactions=0, error=str(signed.get("error") or "")[-300:] or None)
    combined = multisign(base, [agent_signed, Transaction.from_xrpl(decode(signed["signedBlob"]))])
    entry = {"to": agent_signed.destination, "amount": amt.value, "approved_by": "ledger", "approval": approval,
             "at": datetime.now(timezone.utc).isoformat()}
    if present:  # x402: the vendor's facilitator submits it
        h = combined.get_hash()
        deployments.record_payment(rec["id"], {**entry, "rail": "x402", "resource": resource, "ok": None,
                                               "result": "presented", "hash": h,
                                               "explorer": f"{config.EXPLORER}/transactions/{h}"})
        return {"ok": True, "presented": True, "hash": h, "blob": combined.blob(), "approved_by": "ledger",
                "approval": approval}
    result = submit_capture(combined, c)
    deployments.record_payment(rec["id"], {**entry, "rail": "direct", **result})
    return {**result, "approved_by": "ledger", "approval": approval}


def _cosign_deployment(rec: dict | None, tx_json: dict, present: bool = False, resource: str | None = None) -> dict:
    if not rec or rec["status"] != "active":
        return _refuse("unknown_or_inactive_deployment")
    tx = Transaction.from_xrpl(tx_json)
    if tx.transaction_type.value != "Payment" or tx.account != rec["subwallet"]:
        return _refuse("not_a_subwallet_payment", account=tx.account, type=tx.transaction_type.value)
    if rec.get("buy_only") and not present:  # a planned run buys its plan's resources over x402, nothing else
        amt = tx.amount
        return _refuse("not_a_planned_purchase", payee=tx.destination,
                       amount=amt.value if isinstance(amt, IssuedCurrencyAmount) else str(amt),
                       hint="this wallet's task only pays vendors for the resources in its plan")
    c = client()
    if config.REQUIRE_VENDOR_CREDENTIAL:  # Part 2: trust comes from the ledger, not from a list we keep
        v = vendors.check(c, tx.destination, vendor_class=rec.get("vendor_class", "data"))
        if v["status"] != "valid":
            return _refuse("vendor_not_credentialed", payee=tx.destination, vendor=v)
    if rec["allowed_payees"] and tx.destination not in rec["allowed_payees"]:  # optional narrower filter
        return _refuse("payee_not_allowed", payee=tx.destination, allowed=rec["allowed_payees"])
    amt = tx.amount
    if not isinstance(amt, IssuedCurrencyAmount) or amt.currency != config.RLUSD_CURRENCY:
        return _refuse("not_rlusd", amount=str(amt))
    if amt.issuer != config.RLUSD_ISSUER:  # R01: the RLUSD code from any other issuer is a different token
        return _refuse("wrong_issuer", issuer=amt.issuer, expected=config.RLUSD_ISSUER, currency=amt.currency)
    shape = _payment_shape_refusal(tx_json, amt)
    if shape:
        return shape
    remaining = rlusd_balance(c, rec["subwallet"]) - ap4m_spent(rec)  # one budget across both rails
    if Decimal(amt.value) > remaining:
        return _refuse("over_budget", requested=amt.value, remaining=str(remaining))
    if datetime.now(timezone.utc) >= datetime.fromisoformat(rec["expires_at"]):
        return _refuse("expired", expires_at=rec["expires_at"])
    memos = decode_memos(tx_json)
    if not memos or memos[0].get("job") != rec["id"] or memos[0].get("tag") != rec["tag"]:
        return _refuse("memo_mismatch")
    threshold = _approval_threshold(rec)
    if threshold is not None and Decimal(amt.value) > threshold:
        return _owner_approves_payment(rec, tx, amt, threshold, present, resource)
    if present:  # x402: hand the co-signed blob back; the vendor's facilitator verifies and submits it
        combined = cosign_combine(tx, config.wallet("CEREAL_COSIGN"))
        result = {"ok": True, "presented": True, "hash": combined.get_hash(), "blob": combined.blob()}
        deployments.record_payment(rec["id"], {"to": tx.destination, "amount": amt.value, "rail": "x402",
                                               "resource": resource, "ok": None, "result": "presented",
                                               "hash": result["hash"], "explorer": f"{config.EXPLORER}/transactions/{result['hash']}",
                                               "at": datetime.now(timezone.utc).isoformat()})
        return result
    result = cosign_and_submit(tx, config.wallet("CEREAL_COSIGN"), c)
    deployments.record_payment(rec["id"], {"to": tx.destination, "amount": amt.value, "rail": "direct", **result,
                                           "at": datetime.now(timezone.utc).isoformat()})
    return result


@app.post("/subagents/{dep_id}/events")
def report_event(dep_id: str, ev: EventReport) -> dict:
    """A refusal that happened on the ledger itself (no cereal signature involved), reported by a subagent or a demo
    beat. With a hash, cereal checks the ledger: the event is marked verified only if the validated result matches."""
    from . import events
    if not deployments.get(dep_id):
        raise HTTPException(404, "unknown deployment")
    if ev.kind not in events.REPORTABLE:
        return _refuse("unknown_event_kind", allowed=sorted(events.REPORTABLE))
    verified = None
    if ev.hash:
        try:
            r = client().request(Tx(transaction=ev.hash)).result
            verified = bool(r.get("validated")) and r.get("meta", {}).get("TransactionResult") == ev.result
        except Exception:
            verified = False
    entry = {"kind": ev.kind, "result": ev.result, "hash": ev.hash, "verified": verified, "detail": ev.detail,
             "at": datetime.now(timezone.utc).isoformat()}
    deployments.record_event(dep_id, entry)
    return {"ok": True, **entry}


@app.get("/plan")
def plan_preview(goal: str, envelope: str = "2") -> dict:
    """Part 5: the quote-based plan for a goal, read-only: every vendor's price, which one wins and why, the budget
    each subagent would get, and what stays in the main wallet. Nothing is signed or deployed."""
    from . import pricing
    p = pricing.plan(goal, Decimal(envelope))
    return {**p, "summary": pricing.summary(p)}


@app.get("/export.json")
def export_json() -> dict:
    """Part 5: every payment across wallets and rails, with totals by wallet, vendor, rail and folder."""
    from . import books
    rs = books.rows()
    return {"rows": rs, "totals": books.totals(rs)}


@app.get("/export.csv")
def export_csv():
    """Part 5: the same rows as a CSV download for finance."""
    from fastapi.responses import Response
    from . import books
    return Response(books.to_csv(books.rows()), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=cereal-payments.csv"})


# ---- chat: one plain-English message → rules → subagent → purchase → sweep (cereal/chat.py) ----
_chats: dict[str, dict] = {}


@app.post("/chat")
def chat_start(req: ChatRequest) -> dict:
    """Start the chat flow in the background; poll GET /chat/{chat_id} for its messages."""
    import uuid
    from . import chat
    cid = "c_" + uuid.uuid4().hex[:6]
    _chats[cid] = {"chat_id": cid, "status": "running", "message": req.message, "messages": []}

    def work():
        try:
            res = chat.run(req.message, req.folder, say=lambda who, text, link: _chats[cid]["messages"].append(
                {"who": who, "text": text, "link": link, "at": datetime.now(timezone.utc).isoformat()}))
            _chats[cid].update(status="done", ok=res.get("ok"), deployment=res.get("deployment"),
                               spent=res.get("spent"), returned=res.get("returned"))
        except Exception as e:  # report, never hang the UI
            _chats[cid].update(status="failed", error=f"{type(e).__name__}: {e}"[:300])
    threading.Thread(target=work, daemon=True).start()
    return {"chat_id": cid, "status": "running"}


@app.get("/chat/{cid}")
def chat_status(cid: str) -> dict:
    if cid not in _chats:
        raise HTTPException(404, "unknown chat")
    return _chats[cid]


# ---- sweeper: leftovers go home without anyone asking ----
SWEEP_SECONDS = int(__import__("os").getenv("CEREAL_SWEEP_SECONDS", "60"))


def sweep_once() -> dict:
    """Reclaim every active wallet past its expiry (leftover RLUSD home), and retire every reclaimed or recovered
    subwallet the ledger now lets us delete (its XRP reserve home). Safe to run any time."""
    swept, retired = [], []
    now = datetime.now(timezone.utc)
    for r in deployments.all_():
        try:
            if r["status"] == "active" and r.get("subwallet") and datetime.fromisoformat(r["expires_at"]) <= now:
                res = reclaim(r["id"])
                if res.get("ok"):
                    deployments.update(r["id"], swept_by="expiry")
                    swept.append({"deployment": r["id"], "returned": res.get("returned")})
            elif r["status"] in ("reclaimed", "recovered") and r.get("subwallet"):
                res = retire(r["id"])
                if res.get("ok"):
                    retired.append({"deployment": r["id"], "hash": res.get("hash")})
        except Exception:
            continue  # one bad record never stops the sweep
    return {"swept": swept, "retired": retired, "at": now.isoformat()}


@app.post("/sweep")
def sweep_now() -> dict:
    """Run the sweeper once now."""
    return sweep_once()


@app.get("/sweeps")
def recent_sweeps(limit: int = 10) -> list[dict]:
    """Leftovers that came home, newest first: which wallet, how much, why (done, expiry, owner recovery)."""
    out = [{"deployment": r["id"], "wallet": r.get("name") or r.get("task"), "returned": r.get("returned"),
            "at": r.get("reclaimed_at") or r.get("recovered_at"),
            "why": "expired" if r.get("swept_by") == "expiry" else ("owner's Ledger" if r["status"] == "recovered"
                                                                    else "finished"),
            "hash": ((r.get("hashes") or {}).get("reclaim") or [None])[0]}
           for r in deployments.all_() if r.get("reclaimed_at") or r.get("recovered_at")]
    return sorted(out, key=lambda x: x["at"] or "", reverse=True)[:limit]


def _sweeper_loop():
    import time as _t
    while True:
        _t.sleep(SWEEP_SECONDS)
        try:
            sweep_once()
        except Exception:
            pass


@app.get("/events")
def security_events(limit: int = 200) -> list[dict]:
    """The security log: every refused or out-of-policy attempt, who stopped it, why, the outcome and the proof."""
    from . import events
    return events.feed()[:limit]


@app.post("/subagents/{dep_id}/ap4m")
def pay_ap4m(dep_id: str, req: Ap4mRequest) -> dict:
    """Part 4b: a subagent pays an AP4M merchant's 402 over Mastercard's rail (XRPL EVM). Same budget as the XRPL rails:
    refused if the price could take the subagent past its budget across both. The Channel's on-chain cap is the budget."""
    rec = deployments.get(dep_id)
    refused = None
    if not config.AP4M_ENABLED:
        refused = _refuse("ap4m_disabled", hint="the Mastercard rail is off; start the service with CEREAL_AP4M=1")
    elif not rec or rec["status"] != "active":
        refused = _refuse("unknown_or_inactive_deployment")
    elif datetime.now(timezone.utc) >= datetime.fromisoformat(rec["expires_at"]):
        refused = _refuse("expired", expires_at=rec["expires_at"])
    else:
        remaining = rlusd_balance(client(), rec["subwallet"]) - ap4m_spent(rec)
        if Decimal(req.max_rlusd) > remaining:
            refused = _refuse("over_budget", requested=req.max_rlusd, remaining=str(remaining))
        elif not all(ap4m.available().values()):
            refused = _refuse("ap4m_unavailable", **ap4m.available(), hint="cd ap4m && npm ci; create ap4m/.env")
    if refused:
        if rec:
            deployments.record_refusal(dep_id, {"payee": req.resource, "amount": req.max_rlusd, "rail": "ap4m", **refused,
                                                "at": datetime.now(timezone.utc).isoformat()})
        return refused
    out = ap4m.pay(req.resource, req.max_rlusd, rec["budget"], rec["id"], rec["tag"])
    recorded = reconcile_ap4m(dep_id, out, req.resource)
    if not out.get("ok") and not recorded:
        deployments.record_refusal(dep_id, {"payee": req.resource, "rail": "ap4m", "resource": req.resource,
                                            "refused": out.get("refused"), "error": str(out.get("error") or "")[:300],
                                            "channel_id": out.get("channel_id"), "at": datetime.now(timezone.utc).isoformat()})
    return {**out, "recorded": recorded}


def reconcile_ap4m(dep_id: str, out: dict | None = None, resource: str | None = None) -> list[dict]:
    """Record what the subagent's AP4M Channel actually redeemed on-chain, whatever pay.mjs reported.

    The ledger is the truth (as for x402): a crash after a voucher was redeemed can never hide a payment."""
    out = out or {}
    rec = deployments.get(dep_id)
    channel = out.get("channel_id") or ap4m.channel_for_job(dep_id)
    if not rec or not channel:
        return []
    st = ap4m.channel_state(channel)
    if not st.get("ok"):
        return []
    known = {p.get("hash") for p in rec.get("payments", []) if p.get("rail") == "ap4m"}
    added = []
    for r in st.get("redemptions", []):
        if r["tx"] in known:
            continue
        entry = {"rail": "ap4m", "resource": resource or out.get("resource_url"), "to": r.get("payout"),
                 "amount": r["amount"], "ok": True, "result": "redeemed", "hash": r["tx"],
                 "explorer": f"https://explorer.testnet.xrplevm.org/tx/{r['tx']}", "channel_id": channel,
                 "receipt": out.get("receipt_id") if out.get("redeem_tx") == r["tx"] else None,
                 "source": "pay.mjs" if out.get("redeem_tx") == r["tx"] else "chain",
                 "at": datetime.now(timezone.utc).isoformat()}
        deployments.record_payment(dep_id, entry)
        added.append(entry)
    return added


@app.post("/subagents/{dep_id}/ap4m/reconcile")
def ap4m_reconcile(dep_id: str) -> dict:
    """Read the subagent's AP4M Channel on-chain and record any redemption cereal has not recorded yet."""
    if not deployments.get(dep_id):
        raise HTTPException(404, "unknown deployment")
    added = reconcile_ap4m(dep_id)
    return {"ok": True, "added": added, "ap4m_spent": str(ap4m_spent(deployments.get(dep_id)))}


@app.post("/cosign")
def cosign(req: CosignRequest) -> dict:
    if req.deployment_id:
        result = _cosign_deployment(deployments.get(req.deployment_id), req.tx, req.present, req.resource)
        if result.get("refused"):
            amt = req.tx.get("Amount")
            deployments.record_refusal(req.deployment_id, {
                "payee": req.tx.get("Destination"), "amount": amt.get("value") if isinstance(amt, dict) else amt,
                **result, "at": datetime.now(timezone.utc).isoformat()})
        return result
    if req.job_id:  # legacy single-job path
        from .cosign import CosignRequest as LegacyRequest, cosign as legacy
        return legacy(LegacyRequest(job_id=req.job_id, tx=req.tx))
    return _refuse("missing_deployment_id")


# ---- vendor registry (cereal's CREDENTIAL_ISSUER; vendors accept with their own key) ----
@app.get("/vendors")
def vendor_list() -> list[dict]:
    """Every vendor cereal knows: name, address, credential (from the ledger), items and prices, paid and refused."""
    return directory.list_vendors()


@app.get("/vendors/{address}")
def vendor_status(address: str, vendor_class: str = "data") -> dict:
    return vendors.check(client(), address, vendor_class=vendor_class)


@app.post("/vendors/{address}/issue")
def vendor_issue(address: str, req: VendorIssueRequest) -> dict:
    return vendors.issue(config.wallet("CREDENTIAL_ISSUER"), address, client(), vendor_class=req.vendor_class, days=req.days)


@app.post("/vendors/{address}/revoke")
def vendor_revoke(address: str, req: VendorRevokeRequest) -> dict:
    """One public transaction blocks this vendor for every cereal customer."""
    return vendors.revoke(config.wallet("CREDENTIAL_ISSUER"), address, client(), req.reason, req.report,
                          vendor_class=req.vendor_class)


# The React app's feature routers (cereal/routes/): run a task, edit rules, top up, folders and archive.
from .routes import funding as _funding, rules as _rules, runs as _runs, workspace as _workspace  # noqa: E402
from .routes import sessions as _sessions, site_access as _site_access, sites as _sites, sites_probe as _sites_probe  # noqa: E402

# /sites/probe and /sites/{id}/... are registered before /sites so the literal paths win.
for _router in (_runs.router, _rules.router, _funding.router, _workspace.router,
                _sessions.router, _sites_probe.router, _site_access.router, _sites.router):
    app.include_router(_router)
