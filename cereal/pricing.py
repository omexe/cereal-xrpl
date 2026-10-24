"""Part 5: quote-based pricing. The main agent never guesses a budget: it reads what vendors sell, takes the binding
price from each item's 402, checks every vendor's credential on-ledger, buys from the cheapest trusted vendor, and
sizes each subagent's budget to that quote plus a small buffer. Claude (when a key is set) only decides WHAT to buy;
the money is computed here and then enforced by cereal and the ledger.

    python -m cereal.pricing "Pull the Swell agenda and speaker list" --envelope 2
"""
from __future__ import annotations

import argparse
import json
import re
from decimal import ROUND_UP, Decimal

import requests

from . import config, vendors
from .ledger import client
from .pay import pick_rlusd_requirement

CENT = Decimal("0.01")
SYNONYMS = {"speaker": "speakers", "speakers": "speakers", "agenda": "agenda", "schedule": "agenda", "sessions": "agenda"}


def catalog(base: str, timeout: float = 5) -> dict | None:
    """A vendor's free catalog (GET /catalog), or None if it is down. Vendor data is untrusted: prices are re-read
    from the 402 and the vendor is checked on-ledger before anything is chosen."""
    try:
        r = requests.get(f"{base.rstrip('/')}/catalog", timeout=timeout)
        return {**r.json(), "base": base.rstrip("/")} if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def quote(url: str, timeout: float = 10) -> dict:
    """The binding price: an unpaid GET answers 402 with the payment requirement. Nothing is signed or sent."""
    try:
        r = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        return {"ok": False, "reason": "vendor_unreachable", "error": str(e)[:120]}
    if r.status_code != 402:
        return {"ok": False, "reason": f"no_paywall_http_{r.status_code}"}
    req = pick_rlusd_requirement(r.json())
    if req is None:
        return {"ok": False, "reason": "no_rlusd_option"}
    return {"ok": True, "price": str(req.amount), "payee": req.pay_to}


def offers(item: str, bases: list[str] | None = None, c=None) -> list[dict]:
    """Every vendor that lists `item`, with its catalog price, binding quote and on-ledger credential."""
    c = c or client()
    out = []
    for cat in filter(None, (catalog(b) for b in (bases or config.VENDOR_URLS))):
        for it in cat.get("items", []):
            if it.get("item") != item:
                continue
            url = f"{cat['base']}{it['path']}"
            q = quote(url)
            payee = q.get("payee") or cat.get("pay_to")
            cred = vendors.check(c, payee) if payee else {"status": "none"}
            out.append({"item": item, "vendor": cat.get("vendor"), "url": url, "payee": payee,
                        "catalog_price": it.get("price"), "quote": q, "credential": cred})
    return out


def choose(item: str, found: list[dict]) -> dict:
    """Cheapest trusted offer wins; every other offer is kept with the reason it lost (the plan shows all of them)."""
    trusted, rejected = [], []
    for o in found:
        st = o["credential"].get("status")
        if not o["quote"].get("ok"):
            rejected.append({**o, "reason": o["quote"].get("reason")})
        elif st != "valid":
            rejected.append({**o, "reason": f"vendor_{st}", "evidence": (o["credential"].get("revocation") or {})})
        elif o["catalog_price"] is not None and Decimal(str(o["catalog_price"])) != Decimal(o["quote"]["price"]):
            # the catalog and the paywall disagree: trust the 402 (it is what we would pay), but say so
            trusted.append({**o, "note": "catalog price differs from the 402"})
        else:
            trusted.append(o)
    trusted.sort(key=lambda o: Decimal(o["quote"]["price"]))
    return {"item": item, "chosen": trusted[0] if trusted else None, "fallbacks": trusted[1:], "rejected": rejected}


def budget_for(price: Decimal) -> Decimal:
    """Quote plus a buffer (max of a percentage and a floor), rounded up to the cent. Unused money is reclaimed."""
    buf = max(price * Decimal(config.PRICE_BUFFER_PCT), Decimal(config.PRICE_BUFFER_MIN))
    return (price + buf).quantize(CENT, rounding=ROUND_UP)


def needs_from_goal(goal: str, items: list[str]) -> list[str]:
    """Which catalog items the goal asks for. Claude picks when a key is set; otherwise words in the goal are matched
    to item names (with a few synonyms). Only names that exist in a catalog can come back."""
    from . import llm
    if llm.available():
        picked = llm.choose_items(goal, items)
        if picked:
            return [i for i in picked if i in items]
    words = re.findall(r"[a-z]+", goal.lower())
    wanted = []
    for w in words:
        item = SYNONYMS.get(w, w)
        if item in items and item not in wanted:
            wanted.append(item)
    return wanted


def plan(goal: str, envelope: Decimal, bases: list[str] | None = None) -> dict:
    """One subagent per needed item, each budgeted to its cheapest trusted quote plus buffer, within the envelope."""
    c = client()
    cats = [x for x in (catalog(b) for b in (bases or config.VENDOR_URLS)) if x]
    items = sorted({it["item"] for cat in cats for it in cat.get("items", [])})
    needs = needs_from_goal(goal, items)
    lines, total = [], Decimal(0)
    for item in needs:
        ch = choose(item, offers(item, [cat["base"] for cat in cats], c))
        if ch["chosen"]:
            price = Decimal(ch["chosen"]["quote"]["price"])
            budget = budget_for(price)
            fallbacks = [f for f in ch["fallbacks"] if Decimal(f["quote"]["price"]) <= budget]
            lines.append({**ch, "price": str(price), "budget": str(budget), "fallbacks": fallbacks,
                          "unaffordable": [f for f in ch["fallbacks"] if f not in fallbacks]})
            total += budget
        else:
            lines.append({**ch, "price": None, "budget": "0"})
    ok = bool(needs) and all(l["chosen"] for l in lines) and total <= envelope
    reason = None if ok else ("nothing_to_buy" if not needs else
                              "no_trusted_vendor" if not all(l["chosen"] for l in lines) else "over_envelope")
    return {"ok": ok, "reason": reason, "goal": goal, "envelope": str(envelope), "total": str(total),
            "kept_in_main_wallet": str(envelope - total) if ok else str(envelope), "needs": needs, "lines": lines,
            "vendors_seen": [cat.get("vendor") for cat in cats]}


def summary(p: dict) -> list[str]:
    """The plan as the main agent prints it: every offer, why it won or lost, and each budget."""
    out = [f"plan for: {p['goal']}  (envelope {p['envelope']} RLUSD; vendors {', '.join(map(str, p['vendors_seen']))})"]
    for l in p["lines"]:
        out.append(f"  need {l['item']}:")
        if l["chosen"]:
            out.append(f"    ✓ {l['chosen']['vendor']} {l['chosen']['quote']['price']} RLUSD (cheapest trusted)")
        for f in l.get("fallbacks", []):
            out.append(f"    · {f['vendor']} {f['quote']['price']} RLUSD (fallback, fits the budget)")
        for f in l.get("unaffordable", []):
            out.append(f"    · {f['vendor']} {f['quote']['price']} RLUSD (trusted, but over this budget)")
        for r in l["rejected"]:
            ev = r.get("evidence") or {}
            why = f"{r['reason']}" + (f" ({ev.get('reason')}) {config.EXPLORER}/transactions/{ev['hash']}" if ev.get("hash") else "")
            price = r["quote"].get("price") or r.get("catalog_price")
            out.append(f"    ✗ {r['vendor']} {price} RLUSD skipped: {why}")
        if l["chosen"]:
            out.append(f"    budget {l['budget']} RLUSD = quote {l['price']} + buffer")
    out.append(f"  total {p['total']} of {p['envelope']} RLUSD; {p['kept_in_main_wallet']} stays in the main wallet"
               if p["ok"] else f"  no plan: {p['reason']}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Quote-based plan (reads catalogs and 402s; signs and sends nothing).")
    ap.add_argument("goal"); ap.add_argument("--envelope", default="2"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    p = plan(a.goal, Decimal(a.envelope))
    print(json.dumps(p, indent=2, default=str) if a.json else "\n".join(summary(p)))


if __name__ == "__main__":
    main()
