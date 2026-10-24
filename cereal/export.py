"""The accounting export: every burner payment with its decoded team/project/task, as CSV."""
from __future__ import annotations

import csv
from pathlib import Path

from xrpl.clients import JsonRpcClient

from . import config, jobs
from .ledger import account_tx, decode_memos, explorer

COLUMNS = ["date", "ledger_index", "kind", "type", "result", "from", "to", "amount", "currency", "hash", "explorer",
           "team", "project", "task", "job_id", "sentence"]


def _iso(ripple_seconds) -> str:
    from xrpl.utils import ripple_time_to_datetime
    try:
        return ripple_time_to_datetime(int(ripple_seconds)).isoformat()
    except (TypeError, ValueError):
        return ""


def rows_for_burner(c: JsonRpcClient, burner_addr: str) -> list[dict]:
    out = []
    for t in account_tx(c, burner_addr):
        tx = t["tx"]
        if tx.get("SourceTag") != config.SOURCE_TAG:
            continue
        memos = decode_memos(tx)
        tag = memos[0].get("tag", "") if memos else ""
        kind = memos[0].get("kind", tx.get("TransactionType")) if memos else tx.get("TransactionType")
        job = jobs.by_tag(tag) if tag else None
        meta = t.get("meta") if isinstance(t.get("meta"), dict) else {}
        result = meta.get("TransactionResult", "")
        amt = (meta.get("delivered_amount") if result == "tesSUCCESS" else None) or tx.get("Amount") or tx.get("DeliverMax") or ""
        if tx.get("TransactionType") != "Payment":
            amount, currency = "", ""
        elif isinstance(amt, dict):
            amount, currency = amt.get("value", ""), "RLUSD" if amt.get("currency") == config.RLUSD_CURRENCY else amt.get("currency")
        else:
            amount, currency = (str(int(amt) / 1_000_000) if amt else ""), "XRP"
        out.append({
            "date": _iso(tx.get("date")), "ledger_index": t.get("ledger_index", ""), "kind": kind,
            "type": tx.get("TransactionType", ""), "result": result,
            "from": tx.get("Account", ""), "to": tx.get("Destination", ""), "amount": amount, "currency": currency,
            "hash": t.get("hash", ""), "explorer": explorer(t["hash"]) if t.get("hash") else "",
            "team": job["team"] if job else "", "project": job["project"] if job else "",
            "task": job["task"] if job else "", "job_id": job["id"] if job else "",
            "sentence": job["sentence"] if job else "",
        })
    return out


def export_csv(path: str | Path, c: JsonRpcClient, burners: list[str] | None = None) -> Path:
    burners = burners or [j["burner"] for j in jobs.all_jobs()]
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS); w.writeheader()
        for b in burners:
            for row in rows_for_burner(c, b):
                w.writerow(row)
    return path
