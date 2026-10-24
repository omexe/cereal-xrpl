"""Part 5: the security log. One feed of every harmful or out-of-policy attempt and what stopped it, built from what
cereal recorded (its own refusals, the owner's rejections, the planner's skipped vendors) plus refusals that happened
on the ledger itself, which subagents and demo beats report and cereal checks against the ledger when a hash exists.
"""
from __future__ import annotations

from . import config, deployments

PLAIN = {
    "vendor_not_credentialed": "vendor isn't trusted (credential revoked, expired, pending or missing)",
    "payee_not_allowed": "vendor isn't on this wallet's list",
    "over_budget": "more than this wallet has left",
    "expired": "this wallet's time ran out",
    "not_rlusd": "wrong currency; only RLUSD",
    "partial_payment_not_allowed": "payment shape not allowed (partial payment)",
    "paths_not_allowed": "payment shape not allowed (payment paths)",
    "send_max_not_allowed": "payment shape not allowed (could overpay)",
    "memo_mismatch": "payment isn't tagged to this wallet",
    "owner_rejected": "the owner said no on the Ledger",
    "device_unavailable": "the owner's Ledger isn't connected",
    "price_above_limit": "price is above what the subagent will pay",
    "tefBAD_QUORUM": "one signature isn't enough to move this wallet's money",
    "tecPATH_PARTIAL": "more than the wallet holds",
    "tefBAD_SIGNATURE": "these keys can't touch the main wallet",
    "vendor_revoked": "skipped while planning: the vendor's credential is revoked",
    "vendor_pending": "skipped while planning: the vendor hasn't accepted its credential",
    "cap_exceeded": "company limit reached",
}
REPORTABLE = {  # events a subagent or demo beat may report; each is a refusal by the ledger itself
    "hijack_alone": "a hijacked subagent signed a payment by itself",
    "stolen_keys_drain": "stolen subagent + cereal keys tried to take more than the wallet holds",
    "stolen_keys_main_wallet": "stolen subagent + cereal keys tried to spend from the main wallet",
    "prove_lock": "the subagent signed a payment by itself (lock check)",
}
EXPLORER = config.EXPLORER


def _link(h: str | None) -> str | None:
    return f"{EXPLORER}/transactions/{h}" if h else None


def feed() -> list[dict]:
    out = []
    for r in deployments.all_():
        who = {"deployment": r["id"], "wallet": r.get("name") or r.get("task")}
        if r.get("status") == "rejected":
            ap = r.get("approval") or {}
            out.append({**who, "at": r.get("created_at"), "by": "owner", "kind": "budget_rejected",
                        "code": ap.get("result") or "owner_rejected",
                        "what": f"the main agent asked for a {r['budget']} RLUSD budget",
                        "why": PLAIN.get("owner_rejected"), "outcome": "nothing sent", "proof": None,
                        "screens": ap.get("screens", [])})
        for f in r.get("refusals", []):
            code = f.get("refused") or f.get("result")
            ev = ((f.get("vendor") or {}).get("revocation") or {}).get("hash")
            by = "owner" if code == "owner_rejected" else "cereal"
            out.append({**who, "at": f.get("at"), "by": by, "kind": "payment_refused", "code": code,
                        "what": f"pay {f.get('amount')} RLUSD to {f.get('payee')}", "why": PLAIN.get(code, code),
                        "outcome": "nothing sent", "proof": _link(ev), "rail": f.get("rail")})
        for x in (r.get("plan") or {}).get("rejected", []):
            out.append({**who, "at": r.get("created_at"), "by": "main agent", "kind": "vendor_skipped",
                        "code": x.get("reason"), "what": f"buy {r['plan']['item']} from {x.get('vendor')} at {x.get('price')} RLUSD",
                        "why": PLAIN.get(x.get("reason"), x.get("reason")), "outcome": "never considered",
                        "proof": _link(x.get("evidence"))})
        for e in r.get("events", []):
            capped = e.get("result") == "tecPATH_PARTIAL"
            out.append({**who, "at": e.get("at"), "by": "ledger", "kind": e.get("kind"), "code": e.get("result"),
                        "what": REPORTABLE.get(e.get("kind"), e.get("kind")), "why": PLAIN.get(e.get("result"), e.get("result")),
                        "outcome": "capped: nothing moved" if capped else "nothing sent", "proof": _link(e.get("hash")),
                        "verified": e.get("verified")})
        for p in r.get("payments", []):
            if p.get("approved_by") == "ledger":
                out.append({**who, "at": p.get("at"), "by": "owner", "kind": "large_payment_approved",
                            "code": "approved", "what": f"pay {p.get('amount')} RLUSD to {p.get('to')}",
                            "why": f"above the {p.get('approval', {}).get('threshold')} RLUSD threshold",
                            "outcome": "signed by the owner's Ledger", "proof": p.get("explorer")})
    return sorted(out, key=lambda e: e.get("at") or "", reverse=True)
