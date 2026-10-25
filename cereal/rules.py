"""A03: edit an existing wallet's spending rules, from form fields or one plain-English sentence.

    POST /subagents/{id}/rules/preview  → {ok, changes, problems, notes, rules}   reads only; signs and sends nothing
    POST /subagents/{id}/rules          → re-validates, then persists              {ok, rules, changes, notes, hashes, wallet}

A change is either structured fields or a `sentence`, never both. AI interprets a sentence using the current
rules and vendor directory. Its partial proposal is validated by the same policy as explicit fields. Any ambiguity,
unsupported request, invalid answer, or unavailable model blocks the entire change; there is no parser fallback.
Previews return `resolved_change` so Apply revalidates the reviewed fields without another model interpretation.

Mutable fields (and only these; anything else is rejected by the route's model):
- merchants (allowed_payees): every vendor must resolve (cereal's directory, or an r-address) and hold a valid cereal
  credential on the ledger right now (vendors.check). Revoked, pending, expired or unknown is a problem. Narrowing, or
  swapping among credentialed vendors, is allowed. An empty list is a problem: it would mean "any credentialed vendor".
  "Add" on a wallet without a list is a problem too (it would narrow "any credentialed vendor" to one). When the service
  runs with vendor credentials off (CEREAL_REQUIRE_VENDOR_CREDENTIAL=0), the co-signer skips the credential check and so
  does this one: the list is then the whole payee policy.
- expiry: expires_at = now + hours; it must be in the future and at most 7 days (168 hours) away.
- approval_threshold: a decimal >= 0, or null (no wallet threshold: only the company default, if any, applies; the
  co-signer always uses the lower of the two).
- sweep_when_done: a bool.
- spend (the budget). The budget is the balance, so a lower limit returns the excess on-ledger right away: one Payment
  from the subwallet to the main wallet (TREASURY), multi-signed by the subagent's key and cereal's co-signer, tagged
  with memo kind "return". excess = what the wallet can still pay out - (new limit - validated spend). A new limit below
  spent + pending is a problem. Raising the limit is refused with `use_add_funds`: only an owner-approved top-up (A04)
  adds money, so a raised number can never imply funds the ledger does not hold.

Owner approval: rule edits are made by the owner in the app and need no Ledger signature (the device only clear-signs
transactions; a rule is not one). No edit can add funds or let cereal sign for a vendor without a valid credential: the
balance, the ledger credential, the 7-day ceiling and the company threshold still bound every payment, and the one edit
that would add money (raising the budget) is refused here. Like every write on this service, the endpoints trust their
caller until R05 adds caller authentication; a subagent process must not be given network access to them in a
deployment beyond trusted local use.

Effects on payments already made: the co-signer reads the persisted record at payment time, so new rules apply to the
next payment it is asked to sign. Payments cereal already co-signed or presented (x402 blobs a facilitator holds) are
not recalled: they keep counting against the limit until the ledger shows their outcome; previews say so whenever
such pending payments exist. A payment the co-signer signs while a return is still validating can fail on the ledger
(tecPATH_PARTIAL) if the return leaves too little; the ledger caps it, so nothing is ever overspent.

Every applied change appends {at, changes, change, hashes?, returned?} to the record's `rules_history`; returns also
go to `hashes.returns` and add up in `returned_by_rules` (the budget is lowered by the same amount, so budget = spent +
what reclaim returns still holds). It is not written to
deployments.record_event: cereal/events.py renders those entries as refusals by the ledger in the security log, and a
rules change is not one.
"""
from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from xrpl.models.transactions import Payment

from . import config, deployments, directory, keystore, vendors
from .ledger import job_memo, multisign_submit, rlusd, rlusd_balance, stamp
from .rule_intent import interpret

MAX_HOURS = 7 * 24
FIELDS = ("spend", "expires_in_hours", "merchants", "approval_threshold", "sweep_when_done")
_locks: dict[str, threading.Lock] = {}  # one rules change per wallet at a time: two applies never return the same excess
_locks_guard = threading.Lock()


def _wallet_lock(dep_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(dep_id, threading.Lock())


# ---- the plan: what would change, what is wrong, what to know -----------------------------------------------------

def _dec(v) -> Decimal | None:
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _s(d: Decimal) -> str:
    """0.20 → "0.2", 1E+1 → "10": the exact value, never rounded."""
    out = format(d.normalize(), "f")
    return "0" if out in ("-0", "") else out


def _when(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return f"{dt:%b} {dt.day}, {dt:%H:%M} UTC"


def _span(hours: float) -> str:
    if hours >= 24 and abs(hours / 24 - round(hours / 24)) < 1e-9:
        d = round(hours / 24)
        return f"{d} day{'s' if d != 1 else ''}"
    h = round(hours, 2)
    return f"{h:g} hour{'s' if h != 1 else ''}" if h >= 1 else f"{round(hours * 60):g} minutes"


def _payment_totals(rec: dict) -> dict:
    """Validated spend, pending (co-signed or presented, outcome not yet known) and what was paid off-ledger (AP4M,
    exactly as the co-signer subtracts it from the balance)."""
    from .service import ap4m_spent
    spent, pending, n_pending = Decimal(0), Decimal(0), 0
    for p in rec.get("payments", []):
        amt = _dec(p.get("amount")) or Decimal(0)
        if p.get("ok") is True:
            spent += amt
        elif p.get("ok") is None:
            pending += amt; n_pending += 1
    return {"spent": spent, "pending": pending, "ap4m": ap4m_spent(rec), "n_pending": n_pending}


def current_rules(rec: dict) -> dict:
    return {"budget": rec["budget"], "expires_at": rec["expires_at"], "allowed_payees": list(rec.get("allowed_payees") or []),
            "approval_threshold": rec.get("approval_threshold"), "sweep_when_done": bool(rec.get("sweep_when_done"))}


def _merchant_list(addrs: list[str], names: dict[str, str]) -> str:
    if not addrs:
        return "any credentialed vendor"
    shown = [names.get(a) or f"{a[:6]}…{a[-4:]}" for a in addrs]
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def plan(rec: dict, change: dict, c=None, known: list[dict] | None = None) -> dict:
    """Validate a change against the wallet's record and the ledger. Sends nothing.

    Returns {ok, changes, problems, notes, rules, returns, codes, updates}; `updates` is what apply() persists."""
    problems: list[str] = []
    notes: list[str] = []
    changes: list[str] = []
    codes: set[str] = set()
    updates: dict = {}
    excess = Decimal(0)
    cur = current_rules(rec)
    fields = {k: change[k] for k in FIELDS if k in change and (change[k] is not None or k == "approval_threshold")}
    ops: list[tuple[str, list[str]]] = []
    sentence = change.get("sentence")
    if sentence is not None:
        if fields:
            problems.append("send either a sentence or fields, not both")
        elif not sentence.strip():
            problems.append("the sentence is empty")
        else:
            if known is None:
                try:
                    known = directory.list_vendors(c)
                except Exception:
                    return {"ok": False, "changes": [], "problems": ["Could not load the vendor directory. Try again."],
                            "notes": [], "rules": cur, "returns": "0", "codes": [], "updates": {}}
            parsed = interpret(sentence, rec.get("name") or rec.get("task") or "", cur, known)
            fields, ops = dict(parsed["fields"]), parsed["merchants"]
            problems += parsed["problems"]; codes |= parsed["codes"]
            if not fields and not ops and not problems:
                problems.append(f"no spending rule found in “{sentence.strip()}”")
    if "merchants" in fields:
        ops = [("set", list(fields.pop("merchants") or []))]

    # approval threshold
    if "approval_threshold" in fields:
        raw = fields["approval_threshold"]
        new_t: str | None = None
        ok = True
        if raw is not None:  # None clears it; an empty or malformed value is a problem, never a silent "none"
            d = _dec(raw)
            if d is None or d < 0:
                problems.append(f"approval threshold “{raw}” must be an amount of 0 or more, or none"); ok = False
            else:
                new_t = _s(d)
        if ok:
            old_d = _dec(cur["approval_threshold"]) if cur["approval_threshold"] not in (None, "") else None
            new_d = _dec(new_t) if new_t is not None else None
            if old_d != new_d:
                a = _s(old_d) if old_d is not None else None
                b = new_t
                changes.append("Approval threshold " + (f"{a} → {b} RLUSD" if a and b else
                                                        f"none → {b} RLUSD" if b else f"{a} RLUSD → none"))
                updates["approval_threshold"] = new_t
            company = _dec(config.APPROVAL_THRESHOLD) if config.APPROVAL_THRESHOLD else None
            if company is not None and (new_d is None or company < new_d):
                notes.append(f"the company default still applies: your Ledger approves any payment above "
                             f"{_s(company)} RLUSD")
            elif new_d is None:
                notes.append("no approval threshold: cereal co-signs every payment that passes its checks")

    # sweep when done
    if "sweep_when_done" in fields:
        v = fields["sweep_when_done"]
        if not isinstance(v, bool):
            problems.append("sweep when done must be true or false")
        elif v != cur["sweep_when_done"]:
            say = lambda on: "sweep back to the main wallet" if on else "keep funds in the wallet"
            changes.append(f"When done: {say(cur['sweep_when_done'])} → {say(v)}")
            updates["sweep_when_done"] = v

    # expiry
    if "expires_in_hours" in fields:
        try:
            h = float(fields["expires_in_hours"])
        except (TypeError, ValueError):
            h = float("nan")
        if not math.isfinite(h) or h <= 0:
            problems.append("the new duration must end in the future")
        elif h > MAX_HOURS:
            problems.append(f"the new duration ({_span(h)}) is longer than 7 days, the most a wallet may stay open")
        else:
            new_exp = datetime.now(timezone.utc) + timedelta(hours=h)
            changes.append(f"Expires {_when(datetime.fromisoformat(cur['expires_at']))} → {_when(new_exp)} "
                           f"(in {_span(h)})")
            updates["expires_at"] = new_exp.isoformat()

    # merchants
    if ops:
        if known is None:
            try:
                known = directory.list_vendors(c)
            except Exception:
                known = []
                notes.append("cereal's vendor directory could not be read; only r-addresses resolve right now")
        names = {v["address"]: v.get("name") or v["address"] for v in known}
        new = list(cur["allowed_payees"])
        bad = False
        for op, items in ops:
            if not items and op != "set":  # an empty structured list falls through to the empty-list problem
                problems.append("no vendor named"); bad = True; continue
            addrs = []
            for item in items:
                item = str(item).strip()
                addr = directory.resolve(item, known)  # a name from the directory, or an r-address as given
                if not addr:
                    problems.append(f"unknown vendor “{item}”: not in cereal's directory"); bad = True
                    continue
                addrs.append(addr)
            if op in ("only", "set"):
                new = list(dict.fromkeys(addrs))
            elif op == "add":
                if not cur["allowed_payees"]:
                    problems.append("this wallet already pays any credentialed vendor: to narrow it, say "
                                    "“only at …”"); bad = True
                new = list(dict.fromkeys(new + addrs))
            else:  # remove
                if not cur["allowed_payees"]:
                    problems.append("this wallet has no merchant list (any credentialed vendor): name the vendors it "
                                    "may pay with “only at …”"); bad = True
                missing = [a for a in addrs if a not in new]
                if missing and cur["allowed_payees"]:
                    notes.append(f"{_merchant_list(missing, names)} wasn't on the list")
                new = [a for a in new if a not in addrs]
        if not bad:
            if not new:
                problems.append("an empty merchant list would mean any credentialed vendor: keep at least one")
            for addr in new if config.REQUIRE_VENDOR_CREDENTIAL else []:  # mirrors the co-signer's own check
                v = vendors.check(c, addr, vendor_class=rec.get("vendor_class", "data"))
                if v.get("status") != "valid":
                    why = ((v.get("revocation") or {}).get("reason")) if v.get("status") == "revoked" else None
                    problems.append(f"{_merchant_list([addr], names)} is not trusted ({v.get('status')}"
                                    f"{': ' + why if why else ''}); cereal would refuse every payment to it")
            if new and set(new) != set(cur["allowed_payees"]):
                changes.append(f"Merchants {_merchant_list(cur['allowed_payees'], names)} → {_merchant_list(new, names)}")
                updates["allowed_payees"] = new

    # spend limit (the budget is the balance)
    totals = _payment_totals(rec)
    if "spend" in fields:
        new_b = _dec(fields["spend"])
        old_b = _dec(cur["budget"]) or Decimal(0)
        if new_b is None or new_b <= 0:
            problems.append(f"spend limit “{fields['spend']}” must be an amount above 0")
        elif new_b > old_b:
            codes.add("use_add_funds")
            problems.append(f"Only Add funds can raise a wallet's budget: {_s(old_b)} → {_s(new_b)} RLUSD needs "
                            f"{_s(new_b - old_b)} RLUSD more from the main wallet, approved on your Ledger")
        elif new_b < old_b:
            committed = totals["spent"] + totals["pending"]
            if new_b < committed:
                problems.append(f"{_s(new_b)} RLUSD is below what this wallet already spent or committed "
                                f"({_s(totals['spent'])} spent + {_s(totals['pending'])} pending)")
            else:
                try:
                    balance = rlusd_balance(c, rec["subwallet"])
                except Exception as e:
                    balance = None
                    problems.append(f"couldn't read the wallet's balance from the ledger ({type(e).__name__}); try again")
                if balance is not None:
                    excess = (balance - totals["ap4m"]) - (new_b - totals["spent"])
                    if excess > 0:
                        changes.append(f"Spend limit {_s(old_b)} → {_s(new_b)} RLUSD; {_s(excess)} RLUSD returns "
                                       "to the main wallet now")
                    else:
                        excess = Decimal(0)
                        changes.append(f"Spend limit {_s(old_b)} → {_s(new_b)} RLUSD")
                        notes.append("the wallet already holds no more than the new limit allows: nothing to return")
                    updates["budget"] = _s(new_b)

    if totals["n_pending"]:
        n = totals["n_pending"]
        notes.append(f"{n} payment{'s' if n != 1 else ''} ({_s(totals['pending'])} RLUSD) cereal already co-signed or "
                     "presented are not recalled; they count against the limit until the ledger shows their outcome")
    if not problems and not changes:
        problems.append("nothing to change: these are already this wallet's rules")
    if changes and not problems:
        notes.append("cereal enforces the new rules from the next payment it co-signs")
    rules = {**cur, **updates}
    resolved = dict(fields)
    if ops and not problems:
        resolved["merchants"] = rules["allowed_payees"]
    return {"ok": not problems, "changes": changes, "problems": problems, "notes": notes, "rules": rules,
            "returns": _s(excess), "codes": sorted(codes), "updates": updates,
            "resolved_change": resolved if not problems else None}


# ---- preview and apply --------------------------------------------------------------------------------------------

def _public(p: dict) -> dict:
    return {k: v for k, v in p.items() if k != "updates"}


def return_excess(rec: dict, amount: Decimal, c) -> dict:
    """Step one of burn.reclaim, for part of the balance: subwallet → main wallet, subagent + cereal multi-signed."""
    tx = stamp(Payment(account=rec["subwallet"], destination=config.address("TREASURY"), amount=rlusd(_s(amount))),
               [job_memo(rec["id"], rec["tag"], kind="return")])
    return multisign_submit(tx, [keystore.load(rec["id"]), config.wallet("CEREAL_COSIGN")], c)


def _refuse(reason: str, **evidence) -> dict:
    from . import service
    return service._refuse(reason, **evidence)


def preview(dep_id: str, change: dict) -> dict:
    from . import service
    rec = deployments.get(dep_id)
    if not rec or rec["status"] != "active":
        return _refuse("not_active", status=rec and rec["status"])
    rec = service._resolve_presented(rec)
    return _public(plan(rec, change, service.client()))


def apply(dep_id: str, change: dict) -> dict:
    from . import service
    with _wallet_lock(dep_id):
        rec = deployments.get(dep_id)
        if not rec or rec["status"] != "active":
            return _refuse("not_active", status=rec and rec["status"])
        rec = service._resolve_presented(rec)
        c = service.client()
        p = plan(rec, change, c)
        if p["problems"]:
            code = "use_add_funds" if "use_add_funds" in p["codes"] else "rules_problems"
            return _refuse(code, **{k: p[k] for k in ("problems", "changes", "notes")}, sent_transactions=0)
        hashes: dict[str, str] = {}
        excess = Decimal(p["returns"])
        if excess > 0:
            try:
                r = return_excess(rec, excess, c)
            except Exception as e:  # e.g. the node dropped mid-submit: the outcome is unknown, so claim nothing
                return _refuse("return_unknown", error=f"{type(e).__name__}: {e}"[:300], changes=p["changes"],
                               subwallet=rec["subwallet"],
                               problems=[f"cereal could not confirm the {_s(excess)} RLUSD return; no rule was changed. "
                                         "Check the subwallet on the explorer: a retry recomputes the excess from the "
                                         "ledger balance, so nothing is returned twice"])
            if not r.get("ok"):  # nothing persisted; never retried silently. A tec/tef or an expired tx moved nothing.
                return _refuse("return_failed", result=r.get("result"), hash=r.get("hash"), explorer=r.get("explorer"),
                               validated=r.get("validated"), changes=p["changes"],
                               problems=[f"returning {_s(excess)} RLUSD to the main wallet did not validate "
                                         f"({r.get('result')}); no rule was changed"])
            hashes["return"] = r["hash"]
        latest = deployments.get(dep_id)
        if latest["status"] != "active" and not hashes:  # reclaimed meanwhile (sweeper, owner): nothing moved, refuse
            return _refuse("not_active", status=latest["status"])
        entry = {"at": datetime.now(timezone.utc).isoformat(), "changes": p["changes"],
                 "change": {k: v for k, v in change.items() if k == "sentence" or k in FIELDS}}
        if hashes:
            entry["hashes"] = hashes
            entry["returned"] = _s(excess)
        extra = {"returned_by_rules": _s((_dec(latest.get("returned_by_rules")) or Decimal(0)) + excess)} if hashes else {}
        rec = deployments.update(dep_id, **p["updates"], **extra,
                                 rules_history=[*(latest.get("rules_history") or []), entry])
        if hashes:
            prior = (rec.get("hashes") or {}).get("returns") or []
            rec = deployments.merge_hashes(dep_id, returns=[*prior, hashes["return"]])
        wallet = service._with_balance(rec)
        rules = {**current_rules(rec), "balance": wallet.get("balance"), "rules_history": rec["rules_history"]}
        out = {"ok": True, "rules": rules, "changes": p["changes"], "notes": p["notes"], "hashes": hashes,
               "returned": _s(excess), "wallet": wallet}
        if hashes:
            out["explorer"] = f"{config.EXPLORER}/transactions/{hashes['return']}"
        return out
