"""Part 5: the vendor directory. Every vendor cereal knows (its own vendor roles plus every catalog it can reach), with
the on-ledger credential, what it sells and for how much, and what cereal's subagents paid it or were refused.

Names come from the vendors' own catalogs (untrusted labels); trust always comes from the ledger credential.
"""
from __future__ import annotations

import re
from decimal import Decimal

from . import config, deployments, vendors
from .ledger import client

ROLES = ("VENDOR_A", "VENDOR_B", "VENDOR_C")


def _catalogs() -> list[dict]:
    from .pricing import catalog
    return [c for c in (catalog(b, timeout=3) for b in config.VENDOR_URLS) if c]


def list_vendors(c=None) -> list[dict]:
    c = c or client()
    cats = _catalogs()
    by_addr: dict[str, dict] = {}
    for role in ROLES:
        try:
            addr = config.address(role)
        except Exception:
            continue
        by_addr[addr] = {"name": role.replace("_", " ").title(), "address": addr, "role": role, "url": None, "items": []}
    for cat in cats:
        addr = cat.get("pay_to")
        if not addr:
            continue
        v = by_addr.setdefault(addr, {"address": addr, "role": None})
        v.update({"name": cat.get("vendor") or v.get("name") or addr, "url": cat["base"],
                  "items": [{"item": i["item"], "price": i["price"]} for i in cat.get("items", [])]})
    recs = deployments.all_()
    for v in by_addr.values():
        paid = [p for r in recs for p in r.get("payments", []) if p.get("to") == v["address"] and p.get("ok")]
        refused = [f for r in recs for f in r.get("refusals", []) if f.get("payee") == v["address"]]
        v["paid"] = {"count": len(paid), "rlusd": str(sum((Decimal(str(p["amount"])) for p in paid), Decimal(0)))}
        v["refused"] = {"count": len(refused)}
        v["credential"] = vendors.check(c, v["address"])
    return sorted(by_addr.values(), key=lambda v: v["name"])


def resolve(name: str, known: list[dict] | None = None) -> str | None:
    """A vendor name from a sentence ("Vendor C", "C", "vendor-a") or an r-address → its XRPL address."""
    name = name.strip()
    if re.fullmatch(r"r[1-9A-HJ-NP-Za-km-z]{24,34}", name):
        return name
    want = re.sub(r"[^a-z0-9]", "", name.lower()).removeprefix("vendor")
    for v in known if known is not None else list_vendors():
        have = re.sub(r"[^a-z0-9]", "", str(v.get("name", "")).lower()).removeprefix("vendor")
        if want and want == have:
            return v["address"]
    return None
