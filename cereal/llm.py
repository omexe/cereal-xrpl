"""cereal's model layer: OpenRouter first, the Anthropic API as the fallback, deterministic code when neither is set.

    OPENROUTER_API_KEY      → OpenRouter (OpenAI-compatible chat completions), model CEREAL_OPENROUTER_MODEL
    ANTHROPIC_API_KEY       → Anthropic Messages API (fallback), model CEREAL_MODEL
    CEREAL_LLM=off          → never call a model (fully deterministic demo)

Two entry points: extract() (one structured JSON answer, e.g. a wallet sentence → limits card) and run_tool_loop()
(the main agent and subagents acting through tools). A model only reads and proposes; every limit is enforced by
cereal and the ledger, so a wrong or manipulated answer can't move money past them. A tool loop falls back to the
next provider only if no tool ran yet, so a payment is never repeated by a retry.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Iterable

import requests

from . import config  # noqa: F401  (loads .env, where the keys live)

MODEL = os.getenv("CEREAL_MODEL", "claude-haiku-5-5")                              # Anthropic API (Andrew's choice)
OPENROUTER_MODEL = os.getenv("CEREAL_OPENROUTER_MODEL", "anthropic/claude-haiku-5.5")  # the same model via OpenRouter
OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # Anthropic refusal fallback ("default" routing)
OR_MAX_TOKENS = int(os.getenv("CEREAL_OPENROUTER_MAX_TOKENS", "1200"))  # per call; OpenRouter refuses requests the
                                                                         # account's credit can't cover in full
served_by: str | None = None                        # which provider answered the last call (for the record)
last_error: str | None = None                       # why the last call fell through, in plain words


class NoModel(Exception):
    """No provider produced an answer before any tool ran; callers fall back to their deterministic plan."""


def providers() -> list[str]:
    if os.getenv("CEREAL_LLM", "auto").lower() in ("off", "0", "false", "no"):
        return []
    out = []
    if os.getenv("OPENROUTER_API_KEY"):
        out.append("openrouter")
    if os.getenv("ANTHROPIC_API_KEY"):
        out.append("anthropic")
    return out


def available() -> bool:
    return bool(providers())


class ProviderError(Exception):
    pass


# ---- OpenRouter ------------------------------------------------------------------------------------------------

def _or_post(body: dict, timeout: int = 180) -> dict:
    try:
        r = requests.post(OPENROUTER_URL, json=body, timeout=timeout, headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json",
            "X-Title": "cereal"})
    except requests.RequestException as e:
        raise ProviderError(f"openrouter unreachable: {type(e).__name__}") from e
    try:
        data = r.json()
    except ValueError:
        raise ProviderError(f"openrouter HTTP {r.status_code}: not JSON")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error") or {}
        raise ProviderError(f"openrouter HTTP {r.status_code}: {err.get('message') if isinstance(err, dict) else err}")
    return data


def _json_from(text: str) -> dict | None:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)  # a JSON object inside prose or a code fence
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def _or_extract(system: str, user: str, schema: dict, name: str, timeout: float = 180) -> dict | None:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    body = {"model": OPENROUTER_MODEL, "max_tokens": OR_MAX_TOKENS, "messages": msgs,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}}
    try:
        data = _or_post(body, timeout=timeout)
    except ProviderError as e:
        if "HTTP 402" in str(e) or "HTTP 401" in str(e):
            raise  # credit or key problem: retrying without structured outputs can't help
        # the route may not take structured outputs: ask for the JSON in the reply instead
        body.pop("response_format")
        body["messages"] = [{"role": "system", "content": system + "\nReply with only one JSON object matching this "
                                                                   "JSON Schema, no prose: " + json.dumps(schema)},
                            {"role": "user", "content": user}]
        data = _or_post(body, timeout=timeout)
    return _json_from((data.get("choices") or [{}])[0].get("message", {}).get("content") or "")


def _or_loop(system: str, user: str, tools: dict, max_turns: int, on_event, state: dict, terminal=()) -> str:
    spec = [{"type": "function", "function": {"name": n, "description": (fn.__doc__ or n).strip().split("\n")[0],
                                              "parameters": schema}} for n, (schema, fn) in tools.items()]
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for _ in range(max_turns):
        data = _or_post({"model": OPENROUTER_MODEL, "max_tokens": OR_MAX_TOKENS, "messages": messages, "tools": spec,
                         "tool_choice": "auto"})
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        calls = msg.get("tool_calls") or []
        turn = {"role": "assistant", "content": msg.get("content") or ""}
        if calls:
            turn["tool_calls"] = calls
        messages.append(turn)
        if not calls:
            return msg.get("content") or ""
        ended = False
        for call in calls:
            name = call.get("function", {}).get("name")
            try:
                args = json.loads(call.get("function", {}).get("arguments") or "{}")
            except ValueError:
                args = {}
            out = _run_tool(tools, name, args, on_event, state)
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": json.dumps(out, default=str)})
            ended = ended or name in terminal
        if ended:  # the task's closing tool ran: nothing more is asked of the model
            return "done"
    return "max turns reached"


# ---- Anthropic API (fallback) -----------------------------------------------------------------------------------

def _anthropic_create(**kw):
    import anthropic
    # A stalled call must not hold a run for the SDK's default 10 minutes: fail over to the deterministic path instead.
    request_timeout = kw.pop("_request_timeout", None)
    client = anthropic.Anthropic(timeout=request_timeout or float(os.getenv("CEREAL_ANTHROPIC_TIMEOUT", "90")),
                                max_retries=0 if request_timeout is not None else 2)
    if kw.get("model", "").startswith("claude-haiku"):  # Haiku 5.5 has no server-side refusal fallback
        return client.messages.create(**kw)
    try:  # server-side refusal fallback, routed by category ("default")
        return client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kw)
    except TypeError:  # an SDK without the fallbacks parameter
        return client.messages.create(**kw)


def _anthropic_extract(system: str, user: str, schema: dict, name: str, timeout: float | None = None) -> dict | None:
    resp = _anthropic_create(model=MODEL, max_tokens=4000, system=system, _request_timeout=timeout,
                             messages=[{"role": "user", "content": user}],
                             output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}})
    if resp.stop_reason == "refusal":
        return None
    return _json_from(next((b.text for b in resp.content if getattr(b, "type", "") == "text"), ""))


def _anthropic_loop(system: str, user: str, tools: dict, max_turns: int, on_event, state: dict, terminal=()) -> str:
    spec = [{"name": n, "description": (fn.__doc__ or n).strip().split("\n")[0], "input_schema": schema}
            for n, (schema, fn) in tools.items()]
    messages: list[dict] = [{"role": "user", "content": user}]
    for _ in range(max_turns):
        resp = _anthropic_create(model=MODEL, max_tokens=16000, system=system, tools=spec, messages=messages,
                                 output_config={"effort": "medium"})
        messages.append({"role": "assistant", "content": resp.content})  # append-only: thinking blocks stay intact
        if resp.stop_reason == "refusal":
            return "refused"
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        results = []
        ended = False
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use":
                out = _run_tool(tools, block.name, block.input or {}, on_event, state)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, default=str)})
                ended = ended or block.name in terminal
        messages.append({"role": "user", "content": results})
        if ended:  # the task's closing tool ran: nothing more is asked of the model
            return "done"
    return "max turns reached"


# ---- shared -----------------------------------------------------------------------------------------------------

def _run_tool(tools: dict, name: str, args: dict, on_event, state: dict) -> Any:
    state["tools_run"] = state.get("tools_run", 0) + 1
    if name not in tools:
        out = {"error": f"unknown tool {name}"}
    else:
        _, fn = tools[name]
        try:
            out = fn(**args)
        except Exception as e:  # tool errors go back to the model as data
            out = {"error": f"{type(e).__name__}: {e}"}
    if on_event:
        on_event(name, out)
    return out


def _plain(err: Exception | str) -> str:
    s = str(err)
    if "HTTP 402" in s:
        return "the OpenRouter account is out of credit (openrouter.ai/settings/credits)"
    if "HTTP 401" in s:
        return "the model API key was rejected"
    return s[:200]


def extract(system: str, user: str, schema: dict, name: str, *, timeout: float | None = None) -> dict | None:
    """One structured answer that matches `schema`, from the first provider that gives a valid one; None if none
    (then `last_error` says why)."""
    global served_by, last_error
    last_error = None if providers() else "no model key set"
    for p in providers():
        try:
            extractor = _or_extract if p == "openrouter" else _anthropic_extract
            out = extractor(system, user, schema, name, **({"timeout": timeout} if timeout is not None else {}))
        except Exception as e:
            out, last_error = None, f"{p}: {_plain(e)}"
        if isinstance(out, dict):
            served_by, last_error = (OPENROUTER_MODEL if p == "openrouter" else MODEL), None
            return out
        if out is None and last_error is None:
            last_error = f"{p}: no valid answer"
    return None


def run_tool_loop(system: str, user: str, tools: dict[str, tuple[dict, Callable[..., Any]]],
                  max_turns: int = 12, on_event: Callable[[str, Any], None] | None = None,
                  terminal: Iterable[str] = ()) -> str:
    """tools: name -> (input JSON schema, python function(**input)). Returns the final text. Falls back to the next
    provider only if the first failed before running any tool (tools can pay; a payment must never be repeated).
    terminal: tools that close the task (a subagent's done()). Once one has run, the loop returns "done" at once
    instead of asking the model for a closing message nobody reads: that extra call held a paid-up run (and its
    wallet) for up to three 90-second attempts."""
    global served_by, last_error
    last_error = None
    terminal = frozenset(terminal)
    for p in providers():
        state: dict = {}
        try:
            text = (_or_loop if p == "openrouter" else _anthropic_loop)(system, user, tools, max_turns, on_event, state,
                                                                        terminal)
            served_by = OPENROUTER_MODEL if p == "openrouter" else MODEL
            return text
        except Exception as e:
            last_error = f"{p}: {_plain(e)}"
            if state.get("tools_run"):
                return f"stopped after a provider error mid-task ({last_error}); not retried, tools already ran"
    raise NoModel(last_error or "no model key set")


def choose_items(goal: str, items: list[str]) -> list[str] | None:
    """Which catalog items the goal needs. The model only names items; it never sets prices or budgets."""
    schema = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string", "enum": items}}},
              "required": ["items"], "additionalProperties": False}
    out = extract("Pick only the catalog items the goal needs. Do not pick extras.",
                  f"Goal: {goal}\nCatalog items: {items}", schema, "choose_items")
    if not out:
        return None
    return [i for i in out.get("items", []) if i in items]
