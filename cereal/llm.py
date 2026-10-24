"""Minimal tool-use loop on the Anthropic API, shared by the main agent and subagents.

Used only when ANTHROPIC_API_KEY is set; otherwise callers run their deterministic plan.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

MODEL = os.getenv("CEREAL_MODEL", "claude-sonnet-5-5")


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def run_tool_loop(system: str, user: str, tools: dict[str, tuple[dict, Callable[..., Any]]],
                  max_turns: int = 12, on_event: Callable[[str, Any], None] | None = None) -> str:
    """tools: name -> (input JSON schema, python function(**input)). Returns the final text."""
    import anthropic
    client = anthropic.Anthropic()
    spec = [{"name": n, "description": (fn.__doc__ or n).strip().split("\n")[0], "input_schema": schema}
            for n, (schema, fn) in tools.items()]
    messages: list[dict] = [{"role": "user", "content": user}]
    for _ in range(max_turns):
        resp = client.messages.create(model=MODEL, max_tokens=1500, system=system, tools=spec, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        results = []
        for block in resp.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            _, fn = tools[block.name]
            try:
                out = fn(**(block.input or {}))
            except Exception as e:  # tool errors go back to the model as data
                out = {"error": f"{type(e).__name__}: {e}"}
            if on_event:
                on_event(block.name, out)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, default=str)})
        messages.append({"role": "user", "content": results})
    return "max turns reached"


def choose_items(goal: str, items: list[str]) -> list[str] | None:
    """Ask Claude which catalog items the goal needs. It only names items; it never sets prices or budgets."""
    import anthropic
    client = anthropic.Anthropic()
    tool = {"name": "choose_items", "description": "The catalog items needed to accomplish the goal.",
            "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string",
                             "enum": items}}}, "required": ["items"]}}
    try:
        resp = client.messages.create(model=MODEL, max_tokens=300, tools=[tool],
                                      tool_choice={"type": "tool", "name": "choose_items"},
                                      system="Pick only the catalog items the goal needs. Do not pick extras.",
                                      messages=[{"role": "user", "content": f"Goal: {goal}\nCatalog items: {items}"}])
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use":
                return [i for i in block.input.get("items", []) if i in items]
    except Exception:
        return None
    return None
