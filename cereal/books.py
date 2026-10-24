"""Part 5: the accounting export. One row per payment across every wallet and rail, from cereal's records, each with
its transaction hash so anyone can check it on the explorer. Plain-text names stay off-chain; the private tag on every
memo is what ties a ledger transaction back to its wallet here.
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal

from . import deployments, directory

COLUMNS = ["date", "folder", "wallet", "deployment", "task", "rail", "vendor", "payee", "amount", "currency", "result",
           "signed_by", "tx_hash", "explorer", "tag", "item"]


def rows() -> list[dict]:
    names = {v["address"]: v["name"] for v in directory.list_vendors()}
    out = []
    for r in deployments.all_():
        for p in r.get("payments", []):
            out.append({
                "date": p.get("at"), "folder": r.get("folder") or "", "wallet": r.get("name") or r.get("task"),
                "deployment": r["id"], "task": r.get("task"), "rail": p.get("rail") or "direct",
                "vendor": names.get(p.get("to")) or ("Mastercard AP4M merchant" if p.get("rail") == "ap4m" else ""),
                "payee": p.get("to"), "amount": p.get("amount"),
                "currency": "RLUSD", "result": p.get("result"),
                "signed_by": "subagent + owner's Ledger" if p.get("approved_by") == "ledger" else
                             ("Mastercard AP4M voucher" if p.get("rail") == "ap4m" else "subagent + cereal"),
                "tx_hash": p.get("hash"), "explorer": p.get("explorer"), "tag": r.get("tag"),
                "item": (r.get("plan") or {}).get("item") or (p.get("resource") or "").rsplit("/", 1)[-1] or ""})
    return sorted(out, key=lambda x: x["date"] or "")


def totals(rs: list[dict]) -> dict:
    ok = [x for x in rs if x["result"] in ("tesSUCCESS", "redeemed")]
    by = lambda key: {k: str(sum((Decimal(str(x["amount"])) for x in ok if x[key] == k), Decimal(0)))
                      for k in sorted({x[key] for x in ok})}
    return {"payments": len(ok), "rlusd": str(sum((Decimal(str(x["amount"])) for x in ok), Decimal(0))),
            "by_wallet": by("wallet"), "by_vendor": by("vendor"), "by_rail": by("rail"), "by_folder": by("folder")}


def to_csv(rs: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rs)
    return buf.getvalue()
