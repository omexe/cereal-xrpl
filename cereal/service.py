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
from xrpl.models.transactions.transaction import Transaction

from . import config, deployments, keystore, subwallets, vendors
from .burn import reclaim as ledger_reclaim, retire as ledger_retire
from .fund import fund_burner, fund_burner_on_device
from .ledger import account_info, client, cosign_and_submit, decode_memos, rlusd_balance

app = FastAPI(title="cereal service")
_main_wallet = threading.Lock()  # one main-wallet transaction sequence at a time


class DeployRequest(BaseModel):
    task: str
    budget: str
    allowed_payees: list[str] = []  # optional narrower filter; empty = any vendor credentialed for vendor_class
    expires_in_hours: float = 24
    vendor_class: str = "data"


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
            "policy": {"vendor_credentials": config.REQUIRE_VENDOR_CREDENTIAL, "issuer": config.address("CREDENTIAL_ISSUER")},
            "caps": {"MAX_SUBAGENT_BUDGET": config.MAX_SUBAGENT_BUDGET,
                     "MAX_OUTSTANDING_BUDGET": config.MAX_OUTSTANDING_BUDGET,
                     "MAX_ACTIVE_SUBAGENTS": config.MAX_ACTIVE_SUBAGENTS}}


@app.post("/subagents")
def deploy(req: DeployRequest) -> dict:
    refused = deployments.check_caps(req.budget)
    if refused:
        return refused
    payees = list(req.allowed_payees)
    if not payees and not config.REQUIRE_VENDOR_CREDENTIAL:
        return _refuse("no_payee_policy", hint="vendor credentials are off: pass allowed_payees")
    c = client(); main_addr = config.address("TREASURY")
    with _main_wallet:
        if rlusd_balance(c, main_addr) < Decimal(req.budget):
            return _refuse("insufficient_main_balance", rlusd=str(rlusd_balance(c, main_addr)), requested=req.budget)
        if Decimal(int(account_info(c, main_addr)["Balance"])) / 1_000_000 < subwallets.activation_xrp(c) + 1:
            return _refuse("insufficient_main_xrp")
        rec = deployments.create(req.task, req.budget, payees, req.expires_in_hours, req.vendor_class)
        sub_key = keystore.new_subagent_key(rec["id"])
        deployments.update(rec["id"], subagent=sub_key)
        made = subwallets.create(rec["id"], rec["tag"], req.budget, sub_key, c)
        deployments.update(rec["id"], subwallet=made["address"])
        deployments.merge_hashes(rec["id"], activate=made["hashes"]["activate"], lock=made["hashes"]["lock"])
        if not made["ok"]:
            deployments.update(rec["id"], status="failed")
            return _refuse("subwallet_failed", deployment=rec["id"], error=made.get("error"))
        if config.LEDGER_ADDRESS and __import__("os").getenv("CEREAL_DEVICE_FUNDING") == "1":  # Part 3
            funded = fund_burner_on_device(made["address"], req.budget, rec["id"], rec["tag"])
        else:
            funded = fund_burner(config.wallet("TREASURY"), made["address"], req.budget, rec["id"], rec["tag"], c)
        deployments.merge_hashes(rec["id"], fund=funded.get("hash"))
        if not funded.get("ok"):
            deployments.update(rec["id"], status="failed")
            return _refuse("funding_failed", deployment=rec["id"], result=funded)
        rec = deployments.update(rec["id"], status="active")
    return {"ok": True, **_with_balance(rec)}


@app.get("/subagents")
def list_subagents() -> list[dict]:
    return [_with_balance(r) for r in deployments.all_()]


@app.get("/subagents/{dep_id}")
def get_subagent(dep_id: str) -> dict:
    rec = deployments.get(dep_id)
    if not rec:
        raise HTTPException(404, "unknown deployment")
    return _with_balance(rec)


@app.post("/subagents/{dep_id}/done")
def done(dep_id: str, req: DoneRequest) -> dict:
    if not deployments.get(dep_id):
        raise HTTPException(404, "unknown deployment")
    return deployments.update(dep_id, summary=req.summary, finished_at=datetime.now(timezone.utc).isoformat())


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
    return {"ok": ok, "returned": str(before), "steps": [{"step": n, **r} for n, r in steps]}


@app.post("/subagents/{dep_id}/retire")
def retire(dep_id: str) -> dict:
    rec = deployments.get(dep_id)
    if not rec or rec["status"] != "reclaimed":
        return _refuse("not_reclaimed", status=rec and rec["status"])
    r = ledger_retire(rec["subwallet"], config.address("TREASURY"), keystore.load(dep_id),
                      config.wallet("CEREAL_COSIGN"), client(), rec["id"], rec["tag"])
    if r.get("ok"):
        deployments.merge_hashes(dep_id, retire=r.get("hash"))
        deployments.update(dep_id, status="retired")
    return r


def _cosign_deployment(rec: dict | None, tx_json: dict) -> dict:
    if not rec or rec["status"] != "active":
        return _refuse("unknown_or_inactive_deployment")
    tx = Transaction.from_xrpl(tx_json)
    if tx.transaction_type.value != "Payment" or tx.account != rec["subwallet"]:
        return _refuse("not_a_subwallet_payment", account=tx.account, type=tx.transaction_type.value)
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
    remaining = rlusd_balance(c, rec["subwallet"])
    if Decimal(amt.value) > remaining:
        return _refuse("over_budget", requested=amt.value, remaining=str(remaining))
    if datetime.now(timezone.utc) >= datetime.fromisoformat(rec["expires_at"]):
        return _refuse("expired", expires_at=rec["expires_at"])
    memos = decode_memos(tx_json)
    if not memos or memos[0].get("job") != rec["id"] or memos[0].get("tag") != rec["tag"]:
        return _refuse("memo_mismatch")
    result = cosign_and_submit(tx, config.wallet("CEREAL_COSIGN"), c)
    deployments.record_payment(rec["id"], {"to": tx.destination, "amount": amt.value, **result,
                                           "at": datetime.now(timezone.utc).isoformat()})
    return result


@app.post("/cosign")
def cosign(req: CosignRequest) -> dict:
    if req.deployment_id:
        result = _cosign_deployment(deployments.get(req.deployment_id), req.tx)
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
