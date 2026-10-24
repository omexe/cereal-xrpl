"""Part 5: a wallet described in plain English → a limits card the owner confirms → a disposable wallet.

    "Market Sizing: spend up to 1 RLUSD over 2 days, only at Vendor A and Vendor C. Ask me above 0.2. Sweep back when done."

The card says exactly what cereal and the ledger will enforce: budget, how long it lives, which vendors it may pay,
the amount above which the owner's Ledger must approve a payment, and whether leftovers go home when it is done.
Claude parses when a key is set; otherwise a deterministic parser handles this sentence shape. Either way every
vendor is resolved against cereal's directory and checked on-ledger, and the card is re-checked when it is used.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from . import config, directory

AMOUNT = r"\$?\s*(\d+(?:\.\d+)?)\s*(?:rlusd|usd|dollars?)?"


def _amount(text: str) -> str | None:
    m = re.search(AMOUNT, text, re.I)
    return m.group(1) if m else None


def parse_fallback(sentence: str) -> dict:
    s = " ".join(sentence.split())
    name = None
    m = re.match(r"^\s*([^:.,]{2,60}):\s*(.+)$", s)
    if m:
        name, s_rest = m.group(1).strip(), m.group(2)
    else:
        s_rest = s
    threshold = None
    m = re.search(r"ask me (?:for anything |if |when |for payments )?(?:above|over|more than|>)\s*" + AMOUNT, s_rest, re.I)
    if m:
        threshold = m.group(1)
        s_budget = s_rest[:m.start()] + s_rest[m.end():]
    else:
        s_budget = s_rest
    budget = None
    m = re.search(r"(?:up to|spend|budget(?: of)?|with|give it)\s*" + AMOUNT, s_budget, re.I) or re.search(AMOUNT, s_budget, re.I)
    if m:
        budget = m.group(1)
    hours = None
    m = re.search(r"(?:for|over|within|lasting)\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|days?|weeks?)", s_rest, re.I)
    if m:
        n, unit = float(m.group(1)), m.group(2).lower()
        hours = n * (24 * 7 if unit.startswith("week") else 24 if unit.startswith("day") else 1)
    elif re.search(r"\b(today|tonight)\b", s_rest, re.I):
        hours = 12
    vendors_text = None
    m = re.search(r"only (?:at|from|with|on)\s+(.+?)(?:[.;]|$)", s_rest, re.I) or \
        re.search(r",\s*([^,.;:]+(?:,[^,.;:]+)*?)\s+only\b", s_rest, re.I)
    if m:
        vendors_text = m.group(1)
    names = [n.strip() for n in re.split(r",|\band\b|&", vendors_text or "") if n.strip()]
    sweep = not re.search(r"\b(keep|don'?t sweep|do not sweep)\b", s_rest, re.I)
    return {"name": name, "budget": budget, "expires_in_hours": hours, "vendor_names": names,
            "approval_threshold": threshold, "sweep_when_done": sweep, "parsed_by": "fallback-parser"}


def parse_with_claude(sentence: str, known_names: list[str]) -> dict | None:
    """The model reads the sentence into the card's fields (OpenRouter first, then the Anthropic API). It never invents
    a value the sentence doesn't state; unknown fields come back null and cereal applies stated defaults."""
    from . import llm
    nullable = lambda t: {"type": [t, "null"]}
    schema = {"type": "object", "additionalProperties": False,
              "required": ["name", "budget", "expires_in_hours", "vendor_names", "approval_threshold", "sweep_when_done"],
              "properties": {"name": nullable("string"),
                             "budget": {"type": ["string", "null"], "description": "RLUSD (dollars), digits only"},
                             "expires_in_hours": nullable("number"),
                             "vendor_names": {"type": "array", "items": {"type": "string"}},
                             "approval_threshold": {"type": ["string", "null"],
                                                    "description": "RLUSD; payments above it need the owner's approval"},
                             "sweep_when_done": nullable("boolean")}}
    out = llm.extract(
        "Read one plain-English instruction for a disposable agent wallet into its fields. Never invent a budget, "
        "vendor, duration or threshold the sentence does not state: use null. Dollars mean RLUSD. "
        "Known vendors: " + ", ".join(known_names), sentence, schema, "wallet_card")
    if not out:
        return None
    if out.get("sweep_when_done") is None:
        out["sweep_when_done"] = True
    return {**out, "vendor_names": out.get("vendor_names") or [], "parsed_by": llm.served_by}


def build_card(sentence: str, known: list[dict] | None = None) -> dict:
    """Parse, resolve every vendor against the directory and the ledger, apply defaults, and list what's wrong."""
    from . import llm
    known = known if known is not None else directory.list_vendors()
    raw = (parse_with_claude(sentence, [v["name"] for v in known]) if llm.available() else None) or parse_fallback(sentence)
    problems, notes, allowed, vendors_out = [], [], [], []
    for n in raw.get("vendor_names") or []:
        addr = directory.resolve(n, known)
        v = next((x for x in known if x["address"] == addr), None)
        status = (v or {}).get("credential", {}).get("status") if v else None
        vendors_out.append({"named": n, "address": addr, "name": v["name"] if v else None, "credential": status})
        if not addr:
            problems.append(f"unknown vendor '{n}': not in cereal's directory")
        elif status != "valid":
            problems.append(f"{v['name']} is not trusted ({status}); cereal would refuse every payment to it")
        else:
            allowed.append(addr)
    try:
        budget = Decimal(str(raw.get("budget") or "0"))
    except InvalidOperation:
        budget = Decimal(0)
    if budget <= 0:
        problems.append("no budget in the sentence")
    elif budget > Decimal(str(config.MAX_SUBAGENT_BUDGET)):
        problems.append(f"budget {budget} is over the company cap of {config.MAX_SUBAGENT_BUDGET} RLUSD per wallet")
    threshold = raw.get("approval_threshold")
    if threshold is not None:
        try:
            threshold = str(Decimal(str(threshold)))
        except InvalidOperation:
            problems.append(f"approval threshold '{threshold}' is not an amount"); threshold = None
    if threshold is None and config.APPROVAL_THRESHOLD:
        threshold = config.APPROVAL_THRESHOLD
        notes.append(f"company default: your Ledger approves any payment above {threshold} RLUSD")
    hours = raw.get("expires_in_hours") or 24
    if not raw.get("expires_in_hours"):
        notes.append("no duration given: the wallet expires in 24 hours")
    if not raw.get("vendor_names"):
        notes.append("no vendors named: any vendor with a valid cereal credential")
    card = {"name": raw.get("name") or "Wallet", "sentence": sentence, "budget": str(budget), "currency": "RLUSD",
            "expires_in_hours": float(hours), "vendors": vendors_out, "allowed_payees": allowed,
            "approval_threshold": threshold, "sweep_when_done": bool(raw.get("sweep_when_done", True)),
            "parsed_by": raw.get("parsed_by"), "problems": problems, "notes": notes}
    card["ok"] = not problems
    card["summary"] = summary(card)
    return card


def summary(card: dict) -> str:
    """The card read back as one plain sentence, built from the parsed values, for the owner to confirm."""
    days = card["expires_in_hours"] / 24
    span = f"{days:g} day{'s' if days != 1 else ''}" if card["expires_in_hours"] >= 24 else f"{card['expires_in_hours']:g} hours"
    names = [v["name"] or v["named"] for v in card["vendors"]]
    where = ("only at " + (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0])) if names \
        else "at any trusted vendor"
    ask = f" Your Ledger approves any payment above {card['approval_threshold']} RLUSD." if card["approval_threshold"] else ""
    sweep = " Leftovers return to the main wallet when it is done." if card["sweep_when_done"] else ""
    return f"Spend up to {card['budget']} RLUSD over {span}, {where}.{ask}{sweep}"
