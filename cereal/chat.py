"""cereal chat: one message in plain English → the hivemind turns it into rules, deploys a subagent that carries them,
the subagent buys, and the leftovers sweep home. Every step is a line of conversation with its proof link.

    python -m cereal.chat "Market research: spend up to 1 RLUSD today, only at Vendor A and Vendor C. Get the Swell
                           agenda and the speaker list. Ask me above 0.2."

    POST /chat {message} → {chat_id}; GET /chat/{chat_id} → {status, messages}   (the same flow, for the UI)

Who does what: the hivemind (main agent) reads the message and plans; Claude helps it read the message and pick what
to buy when a model key is set, deterministic code otherwise. cereal enforces the rules at every payment, the owner's
Ledger approves the budget (and any payment above the threshold), and XRPL keeps the subagent from paying alone.
"""
from __future__ import annotations

import sys
import time
from decimal import Decimal
from typing import Callable

import requests

from . import config, llm, pricing

EXPLORER = config.EXPLORER


def _tx(h):
    return f"{EXPLORER}/transactions/{h}" if h else None


def run(message: str, folder: str | None = None, say: Callable[[str, str, str | None], None] | None = None) -> dict:
    url = config.SERVICE_URL
    out = {"messages": [], "ok": False}

    def _say(who: str, text: str, link: str | None = None):
        out["messages"].append({"who": who, "text": text, "link": link, "at": time.time()})
        (say or (lambda w, t, l: print(f"{w:>9}: {t}" + (f"\n{'':>11}{l}" if l else ""), flush=True)))(who, text, link)

    _say("you", message)
    # 1. the rules
    card = requests.post(f"{url}/wallets/preview", json={"sentence": message}, timeout=180).json()
    who_read = f" (read by {card.get('parsed_by')})" if card.get("parsed_by") else ""
    _say("hivemind", f"Here's what I'll enforce{who_read}: {card.get('summary')}")
    for n in card.get("notes", []):
        _say("hivemind", f"Note: {n}")
    if not card.get("ok"):
        _say("hivemind", "I can't create this wallet: " + "; ".join(card.get("problems", [])))
        return out
    # 2. what to buy, priced only among the vendors you allowed
    allowed = card.get("allowed_payees") or None
    p = pricing.plan(message, Decimal(card["budget"]), allowed=allowed)
    if not p["needs"]:
        _say("hivemind", "I couldn't tell what to buy from that. Name the items (for example the agenda or the speaker list).")
        return out
    for line in p["lines"]:
        if line["chosen"]:
            skipped = [f"{r['vendor']} ({'not on your list' if r['reason'] == 'not_on_your_list' else r['reason'].replace('_', ' ')})"
                       for r in line["rejected"]]
            _say("hivemind", f"{line['item']}: {line['chosen']['vendor']} at {line['chosen']['quote']['price']} RLUSD is the "
                             f"cheapest vendor you allowed" + (f"; skipped {', '.join(skipped)}" if skipped else ""))
        else:
            _say("hivemind", f"{line['item']}: no trusted vendor you allowed sells it")
    if not p["ok"]:
        _say("hivemind", "No subagent deployed: " + {"over_envelope": "the quotes cost more than your budget",
                                                     "no_trusted_vendor": "something on the list has no allowed vendor"}
             .get(p["reason"], p["reason"] or "no plan"))
        return out
    budget = str(min(Decimal(p["total"]), Decimal(card["budget"])))
    # 3. one subagent wallet that carries your rules, funded to what the plan costs
    payees = allowed or sorted({o["payee"] for l in p["lines"] for o in [l["chosen"], *l["fallbacks"]]})
    plan_rec = {"item": " + ".join(l["item"] for l in p["lines"]), "price": str(sum(Decimal(l["price"]) for l in p["lines"])),
                "budget": budget, "vendor": ", ".join(l["chosen"]["vendor"] for l in p["lines"]),
                "fallbacks": [{"vendor": f["vendor"], "url": f["url"], "price": f["quote"]["price"]} for l in p["lines"] for f in l["fallbacks"]],
                "rejected": [{"vendor": r["vendor"], "price": r["quote"].get("price") or r.get("catalog_price"),
                              "reason": r["reason"], "evidence": (r.get("evidence") or {}).get("hash")} for l in p["lines"] for r in l["rejected"]]}
    dep = requests.post(f"{url}/subagents", timeout=900, json={
        "task": card["name"], "budget": budget, "allowed_payees": payees, "expires_in_hours": card["expires_in_hours"],
        "approval_threshold": card["approval_threshold"], "sweep_when_done": True, "buy_only": True, "name": card["name"],
        "sentence": message, "folder": folder, "plan": plan_rec}).json()
    if not dep.get("ok"):
        _say("hivemind", f"No subagent deployed: {dep.get('refused')}")
        return out
    _say("ledger", f"Owner approved {budget} RLUSD for the new subwallet on the Ledger", _tx((dep.get("hashes") or {}).get("fund")))
    _say("hivemind", f"Deployed subagent {dep['id']} with {budget} RLUSD (you allowed up to {card['budget']}). Its rules: "
                     f"may pay only {', '.join(directory_names(payees))}"
                     + (f"; your Ledger approves anything above {card['approval_threshold']} RLUSD" if card['approval_threshold'] else "")
                     + "; leftovers sweep home when it's done.")
    # 4. the subagent buys
    from .main_agent import MainAgent
    agent = MainAgent([], prove_lock=False)
    specs = ["|".join([f"{l['chosen']['url']}@{l['chosen']['quote']['price']}"] +
                      [f"{f['url']}@{f['quote']['price']}" for f in l["fallbacks"]]) for l in p["lines"]]
    agent.start_subagent(dep["id"], f"{card['name']}: buy {plan_rec['item']}", extra=[x for sp in specs for x in ("--buy", sp)])
    w = agent.wait_subagent(dep["id"])
    names = dict(zip(payees, directory_names(payees)))
    for ev in agent.logs.get(dep["id"], []):
        e, d = ev.get("event"), ev.get("data") or {}
        if e == "start":
            _say("subagent", f"Started ({'Claude' if d.get('mode') == 'llm' else 'plan'} mode) with {d.get('budget')} RLUSD")
        elif e == "model_unavailable":
            _say("subagent", f"Model unavailable ({d.get('reason')}); following the plan instead")
        elif e == "buy" and d.get("ok"):
            signer = "your Ledger" if d.get("approved_by") == "ledger" else "cereal"
            what = (d.get("resource") or "").rsplit("/", 1)[-1] or "it"
            _say("subagent", f"Bought {what} from {names.get(d.get('payee'), 'the vendor')} for {d.get('price')} RLUSD "
                             f"(second signature: {signer})", d.get("explorer"))
        elif e in ("refused", "buy"):
            what = (d.get("resource") or "").rsplit("/", 1)[-1] or "a purchase"
            _say("cereal", f"Refused {what}: {d.get('refused') or d.get('error') or d.get('status')} (nothing sent)")
        elif e == "done":
            pass
        elif e not in ("budget_left",) and isinstance(d, dict) and d.get("summary"):
            _say("subagent", d["summary"])
    # 5. done → sweep home (the subagent reports done; make sure it's swept even if it didn't)
    rec = requests.get(f"{url}/subagents/{dep['id']}", timeout=60).json()
    if rec["status"] == "active":
        requests.post(f"{url}/subagents/{dep['id']}/done", json={"summary": "chat flow finished"}, timeout=600)
        rec = requests.get(f"{url}/subagents/{dep['id']}", timeout=60).json()
    spent = sum(Decimal(str(x["amount"])) for x in rec["payments"] if x.get("ok"))
    _say("cereal", f"Swept {rec.get('returned', '0')} RLUSD back to the main wallet", _tx((rec.get("hashes") or {}).get("reclaim", [None])[0]))
    _say("hivemind", f"Done: bought {sum(1 for x in rec['payments'] if x.get('ok'))} of {len(p['lines'])}, spent {spent} RLUSD, "
                     f"{rec.get('returned', '0')} RLUSD swept home. Wallet {rec['status']}.")
    out.update(ok=w.get("exit") == 0, deployment=dep["id"], spent=str(spent), returned=rec.get("returned"))
    return out


def directory_names(addrs: list[str]) -> list[str]:
    from .directory import list_vendors
    names = {v["address"]: v["name"] for v in list_vendors()}
    return [names.get(a, a[:10] + "…") for a in addrs]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('usage: python -m cereal.chat "<what to buy, with your rules>"')
    sys.exit(0 if run(" ".join(sys.argv[1:])).get("ok") else 1)
