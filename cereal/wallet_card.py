"""Part 5: a wallet described in plain English → a limits card the owner confirms → a disposable wallet.

    "Market Sizing: spend up to 1 RLUSD over 2 days, only at Vendor A and Vendor C. Ask me above 0.2. Sweep back when done."

The card says exactly what cereal and the ledger will enforce: budget, how long it lives, which vendors it may pay,
the amount above which the owner's Ledger must approve a payment, and whether leftovers go home when it is done.
Claude parses when a key is set; otherwise a deterministic parser handles this sentence shape. Either way every
vendor is resolved against cereal's directory and checked on-ledger, and the card is re-checked when it is used.

R07: every card carries a `digest` of what it enforces. POST /wallets rebuilds the card and, given the digest the owner
reviewed, refuses `card_changed` when the rebuilt card differs (a vendor revoked since, a cap changed, or, when this
service no longer holds the reviewed reading of the sentence, a different parser reading).
R03: POST /wallets takes a client `request_id`; the guard at the end of this file makes a retry return the original.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from decimal import Decimal, InvalidOperation

from . import config, deployments, directory

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


def build_card(sentence: str, known: list[dict] | None = None, reviewed: str | None = None, owner: dict | None = None) -> dict:
    """Parse, resolve every vendor against the directory and the ledger, apply defaults, and list what's wrong.

    `reviewed`: the digest of a card this service built and showed for this sentence. Its reading of the sentence is
    reused instead of asking the model again (a model may read the same sentence differently twice), while every
    vendor credential, cap and default is checked again now. Unknown digest (another process, a restart): full rebuild."""
    from . import llm
    known = known if known is not None else directory.list_vendors()
    raw = _reading(reviewed, sentence) if reviewed else None
    if raw is None:
        raw = parse_with_claude(sentence, [v["name"] for v in known]) if llm.available() else None
        if raw is None:
            fell_back = [f"Claude couldn't read this ({llm.last_error}); read by the backup parser instead"] \
                if llm.available() else []
            raw = {**parse_fallback(sentence), "parse_notes": fell_back}
    problems, notes, allowed, vendors_out = [], list(raw.get("parse_notes") or []), [], []
    urls = site_urls(sentence)
    names = [n for n in raw.get("vendor_names") or [] if not _names_a_site(n, urls)]
    for n in names:
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
    site_specs, sites = _site_vendors(urls, owner, budget, vendors_out, allowed, problems, notes)
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
    if not names and not urls:
        notes.append("no vendors named: any vendor with a valid cereal credential")
    card = {"name": raw.get("name") or "Wallet", "sentence": sentence, "budget": str(budget), "currency": "RLUSD",
            "expires_in_hours": float(hours), "vendors": vendors_out, "allowed_payees": allowed,
            # Sites (docs/SITES.md): when the sentence names any vendor or site, the payee list is exactly `allowed`,
            # even if empty (only free sites named): never "any credentialed vendor".
            "payees_locked": bool(names or urls), "site_specs": site_specs, "sites": sites,
            "approval_threshold": threshold, "sweep_when_done": bool(raw.get("sweep_when_done", True)),
            "parsed_by": raw.get("parsed_by"), "problems": problems, "notes": notes}
    card["ok"] = not problems
    card["summary"] = summary(card)
    card["digest"] = card_digest(card)
    _remember(card["digest"], sentence, raw)
    return card


# The readings behind cards this service has shown, by (digest, sentence): POST /wallets with that digest deploys the
# reading the owner reviewed, never a fresh model reading of the same words. Bounded; lost on restart (then rebuilt).
_readings: OrderedDict[tuple[str, str], dict] = OrderedDict()
_readings_lock = threading.Lock()
READINGS_KEPT = 256


def _remember(digest: str, sentence: str, raw: dict) -> None:
    with _readings_lock:
        _readings[(digest, sentence)] = dict(raw)
        _readings.move_to_end((digest, sentence))
        while len(_readings) > READINGS_KEPT:
            _readings.popitem(last=False)


def _reading(digest: str, sentence: str) -> dict | None:
    with _readings_lock:
        raw = _readings.get((digest, sentence))
        return dict(raw) if raw is not None else None


def _canon_amount(value) -> str | None:
    """"0.50", "0.5" and 0.5 are one amount: the digest must not change with how a parser wrote it."""
    if value in (None, ""):
        return None
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except InvalidOperation:
        return str(value)


def card_digest(card: dict) -> str:
    """sha256 over canonical JSON of exactly what cereal and the ledger will enforce for this card: the name, budget,
    lifetime, payee allowlist, approval threshold, sweep, and each vendor's address and on-ledger credential status.
    Order never matters (allowlist and vendors are sorted); the wording, notes and which parser read it are not in it."""
    vendors = sorted(({"address": v.get("address"), "credential": v.get("credential")} for v in card.get("vendors") or []),
                     key=lambda v: (v["address"] or "", v["credential"] or ""))
    enforced = {"name": card.get("name"), "budget": _canon_amount(card.get("budget")),
                "expires_in_hours": float(card.get("expires_in_hours") or 0),
                "allowed_payees": sorted(card.get("allowed_payees") or []),
                "approval_threshold": _canon_amount(card.get("approval_threshold")),
                "sweep_when_done": bool(card.get("sweep_when_done")), "vendors": vendors,
                "payees_locked": bool(card.get("payees_locked")), "site_specs": sorted(card.get("site_specs") or [])}
    blob = json.dumps(enforced, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def summary(card: dict) -> str:
    """The card read back as one plain sentence, built from the parsed values, for the owner to confirm."""
    days = card["expires_in_hours"] / 24
    span = f"{days:g} day{'s' if days != 1 else ''}" if card["expires_in_hours"] >= 24 else f"{card['expires_in_hours']:g} hours"
    names = [v["name"] or v["named"] for v in card["vendors"] if (v.get("site") or {}).get("trust") not in ("free", "blocked")]
    free = [v["name"] or v["named"] for v in card["vendors"] if (v.get("site") or {}).get("kind") == "free"]
    where = ("only at " + (", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0])) if names \
        else ("at no paid vendor" if card.get("payees_locked") else "at any trusted vendor")
    if free:
        where += f" (reads {', '.join(free)} for free)"
    ask = f" Your Ledger approves any payment above {card['approval_threshold']} RLUSD." if card["approval_threshold"] else ""
    sweep = " Leftovers return to the main wallet when it is done." if card["sweep_when_done"] else ""
    return f"Spend up to {card['budget']} RLUSD over {span}, {where}.{ask}{sweep}"


# ---- R03: one wallet per client request_id (POST /wallets) ----
# In-process, like the rest of the service's state: one cereal service owns its deployments file. The request_id is
# stored on the record once deploy() has returned; until then it sits in `in_progress`, so a concurrent twin is refused
# `in_progress` instead of starting a second deploy. It leaves `in_progress` only after the record carries it.
requests_lock = threading.Lock()
in_progress: set[str] = set()


def find_request(request_id: str) -> dict | None:
    """The record an earlier POST /wallets with this request_id left: its wallet, or the refusal that made a record."""
    return next((r for r in deployments.all_() if r.get("request_id") == request_id), None)

# ---- Sites in a wallet sentence (docs/SITES.md) -------------------------------------------------------------------
URL_RE = re.compile(r"https?://[^\s,;<>\"')\]]+", re.I)
MAX_SITES = 5


# A bare web address ("npr.org", "www.npr.org/news"): a host ending in a common top-level domain, not part of an email.
BARE_RE = re.compile(r"(?<![@\w.-])((?:www\.)?(?:[a-z0-9-]+\.)+(?:com|org|net|io|ai|dev|app|co|gov|edu|news|info|us|me|tv|xyz))"
                     r"(/[^\s,;<>\"')\]]*)?(?![\w-])", re.I)


def site_urls(sentence: str) -> list[str]:
    """The web addresses a sentence names, in order, without trailing punctuation, at most MAX_SITES. A bare address
    ("npr.org") means https, like typing it in a browser."""
    out: list[str] = []
    text = sentence or ""
    for m in URL_RE.finditer(text):
        u = m.group(0).rstrip(".!?:")
        if u not in out:
            out.append(u)
    rest = URL_RE.sub(" ", text)  # bare addresses are looked for only outside full URLs
    for m in BARE_RE.finditer(rest):
        u = "https://" + (m.group(1) + (m.group(2) or "")).rstrip(".!?:")
        if u not in out and u.rstrip("/") not in [o.rstrip("/") for o in out]:
            out.append(u)
    return out[:MAX_SITES]


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    return (urlsplit(url).hostname or "").lower()


def _names_a_site(name: str, urls: list[str]) -> bool:
    """A vendor name the reader pulled out of one of the URLs ("https://npr.org", "npr.org", "NPR"): it is a site."""
    n = (name or "").strip().lower().rstrip("/")
    if "://" in n:
        return True
    for u in urls:
        host = _host(u)
        labels = {host, host.removeprefix("www."), host.removeprefix("www.").split(".")[0]}
        if n in labels or n == u.lower().rstrip("/"):
            return True
    return False


def _archive_hint(p: dict) -> str:
    """For a site that blocks agents: the public archived copy to use instead, if the probe found one."""
    a = p.get("archive") or {}
    if not a.get("url"):
        return ""
    return f" Its {a.get('source') or 'archived'} copy from {str(a.get('timestamp') or '')[:10]} can be read instead: {a['url']}"


def _site_vendors(urls: list[str], owner: dict | None, budget: Decimal, vendors_out: list, allowed: list,
                  problems: list, notes: list) -> tuple[list[str], list[dict]]:
    """Each URL in the sentence, checked like Sites does (sites_probe.probe), becomes a vendor on the card:
      free page        → readable for free, no payee (cereal reads it directly)
      payable, credential valid → public: its payTo is an allowed payee (cereal co-signs within the rules)
      payable, no credential    → private to the signed-in owner: allowed, and the owner's Ledger signs every payment
      blocked / unpayable / unreachable / not signed in → a problem, never silently dropped
    Returns (the run's --buy specs for paid sites, the probes to register as the owner's sites)."""
    if not urls:
        return [], []
    from . import sites_probe
    specs, sites, cost = [], [], Decimal(0)
    for url in urls:
        p = sites_probe.probe(url)
        if not p.get("ok"):
            problems.append(f"{url}: {p.get('reason') or p.get('refused')}")
            continue
        host = p.get("host") or _host(url)
        entry = {"named": url, "address": None, "name": host.removeprefix("www."), "credential": None, "title": p.get("title"),
                 "site": {"url": p["url"], "kind": p["kind"], "trust": None, "price": None}}
        if p["kind"] == "free":
            entry["site"]["trust"] = "free"
            vendors_out.append(entry); sites.append(p)
            notes.append(f"{host} is free: cereal reads it directly, no payment needed")
            continue
        if p["kind"] in ("unreachable", "unpayable"):
            entry["site"].update(trust="blocked", reason=p.get("reason"), blocked_by=p.get("blocked_by"))
            vendors_out.append(entry)  # shown, so the owner sees the address was read, and why it can't be used
            problems.append((p.get("reason") or f"{host} cannot be used") + _archive_hint(p))
            continue
        pay = p.get("payment") or {}
        entry.update(address=pay.get("pay_to"), credential=p.get("credential"),
                     name=(pay.get("description") or "").split(":")[0].strip() or host)
        entry["site"]["price"] = pay.get("amount")
        if p.get("verdict") == "block":
            why = (p.get("verdict_reasons") or ["it failed cereal's checks"])[0]
            entry["site"].update(trust="blocked", reason=why)
            vendors_out.append(entry)
            problems.append(f"{host} is blocked: {why}")
            continue
        if p.get("credential") == "valid":
            entry["site"]["trust"] = "public"
        elif owner:
            entry["site"]["trust"] = "private"
            notes.append(f"{host} has no cereal credential: it becomes one of {owner.get('name') or 'your'}'s private "
                         "sites, and your Ledger signs every payment to it")
        else:
            problems.append(f"sign in to use {host}: it has no cereal credential, so only your own wallets can pay it "
                            "(as a private site, your Ledger signs every payment)")
            continue
        vendors_out.append(entry); sites.append(p)
        if pay.get("pay_to") and pay["pay_to"] not in allowed:
            allowed.append(pay["pay_to"])
        try:
            cost += Decimal(str(pay.get("amount") or "0"))
        except InvalidOperation:
            pass
        specs.append(f"{p['url']}@{pay.get('amount')}")
    if budget > 0 and cost > budget:
        problems.append(f"the sites cost {cost} RLUSD, more than the {budget} RLUSD budget")
    return specs, sites

