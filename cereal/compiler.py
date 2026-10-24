"""The sentence → conditions card. Compiled once; the owner reads and signs the card; the agent never calls this.

Uses the Anthropic API when ANTHROPIC_API_KEY is set, otherwise a deterministic parser that covers the demo
sentence shape: "Give the research agent 200 RLUSD for data vendors until Sunday noon, project Swell-brief, team growth, task news".
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

CARD_SCHEMA = {
    "budget": "decimal string, e.g. '200'",
    "currency": "RLUSD",
    "vendor_class": "one of: data, inference, compute, other",
    "expires_at": "ISO-8601 UTC timestamp",
    "tag": {"team": "string", "project": "string", "task": "string"},
    "signers": {"agent": 1, "cereal": 1, "quorum": 2, "master": "disabled"},
}


def _fallback(sentence: str) -> dict:
    budget = re.search(r"(\d+(?:\.\d+)?)\s*(RLUSD|USD|XRP)", sentence, re.I)
    project = re.search(r"project\s+([\w\-]+)", sentence, re.I)
    team = re.search(r"team\s+([\w\-]+)", sentence, re.I)
    task = re.search(r"task\s+([\w\-]+)", sentence, re.I)
    hours = 24
    if re.search(r"\b(today|tonight)\b", sentence, re.I):
        hours = 12
    elif re.search(r"\bweek\b", sentence, re.I):
        hours = 24 * 7
    vendor_class = "data"
    for cls in ("inference", "compute", "data"):
        if re.search(cls, sentence, re.I):
            vendor_class = cls; break
    return {
        "budget": budget.group(1) if budget else "0",
        "currency": (budget.group(2).upper() if budget else "RLUSD"),
        "vendor_class": vendor_class,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(),
        "tag": {"team": team.group(1) if team else "default", "project": project.group(1) if project else "default",
                "task": task.group(1) if task else "default"},
        "signers": CARD_SCHEMA["signers"],
        "compiled_by": "fallback-parser",
    }


def compile_sentence(sentence: str) -> dict:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return _fallback(sentence)
    try:
        import anthropic
        now = datetime.now(timezone.utc).isoformat()
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model="claude-sonnet-5-5", max_tokens=400,
            system=("You compile one plain-English spending instruction into a JSON conditions card for a disposable "
                    "agent wallet. Output only JSON matching this schema: " + json.dumps(CARD_SCHEMA) +
                    f". Now is {now}. Never invent a budget; if absent use '0'. Signers are always "
                    "agent 1, cereal 1, quorum 2, master disabled."),
            messages=[{"role": "user", "content": sentence}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        card = json.loads(text[text.find("{"): text.rfind("}") + 1])
        card["signers"] = CARD_SCHEMA["signers"]; card["compiled_by"] = "claude-sonnet-5-5"
        return card
    except Exception as e:  # the demo must not depend on the model being up
        card = _fallback(sentence); card["compiled_by"] = f"fallback-parser ({type(e).__name__})"
        return card
