"""The accounting export: every burner payment with its decoded team/project/task, as CSV."""
from __future__ import annotations

import csv
from pathlib import Path

from xrpl.clients import JsonRpcClient

from . import config, jobs
from .ledger import account_tx, decode_memos, explorer

COLUMNS = ["date", "ledger_index", "kind", "from", "to", "amount", "currency", "hash", "explorer",
           "team", "project", "task", "job_id", "sentence"]


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
        amt = tx.get("Amount") or tx.get("DeliverMax") or ""
        if isinstance(amt, dict):
            amount, currency = amt.get("value", ""), "RLUSD" if amt.get("currency") == config.RLUSD_CURRENCY else amt.get("currency")
        else:
            amount, currency = (str(int(amt) / 1_000_000) if amt else ""), "XRP"
        out.append({
            "date": tx.get("date", ""), "ledger_index": t.get("ledger_index", ""), "kind": kind,
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
