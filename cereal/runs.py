"""A01, A02: run a wallet's task from the API, as its own subagent process, and keep an honest record of the run.

    start(dep_id) → {ok, run} | refusal      POST /subagents/{id}/run   (cereal/routes/runs.py)
    current(dep_id) → {ok, run}              GET  /subagents/{id}/run

What a run does, the same way cereal/chat.py runs a subagent: plan from an optional task prompt (otherwise the wallet's own sentence) with real quotes
(`pricing.plan`, only among the vendors the wallet allows, within what the wallet holds), then start
`python -m cereal.subagent <id> <task> --buy url@max ...` as a separate process. The subagent signs with its own key;
cereal co-signs each payment after its policy checks (the owner's Ledger above the threshold). When it reports done,
`POST /subagents/{id}/done` sweeps the leftovers home if the wallet says "sweep back when done".

The run is persisted on the wallet record as `run`:
    {id, deployment, status, started_at, finished_at, exit_code, pid, log, plan, summary, error}
    status: starting → running → succeeded (exit 0) | failed (non-zero exit, or the process could not start)
                                 | timed_out (still running after RUN_TIMEOUT_S; the process is killed)
                                 | interrupted (see below)
`succeeded` means the subagent process finished cleanly, not that every purchase went through: the payments and
refusals it caused are on the wallet record, with their ledger evidence.

Rules
- Creating a wallet never starts a run. Only `start` does, once per call, and never while a run is live.
- One live run per wallet: a second start while a run is starting, or running with its process alive, is refused
  (`already_running`). Starts for the same wallet are serialised in this process.
- Never retried: a failed or timed-out run is recorded and left for the owner to decide (start again, or clean up).
- Ordinary runs skip previously paid items. Chat runs (keep_open) allow a new explicit request to purchase a
  settled resource again; unresolved earlier payments block repetition. Reusing a request ID never pays twice.
- Refusals send nothing and record no run: not_active, expired, already_running, balance_unavailable (the ledger
  could not be read), nothing_to_buy, already_bought, no_trusted_vendor, over_budget (the quotes exceed the balance).

Cleanup policy for interrupted runs (A02)
- A run this service did not start in its own lifetime (the service restarted or crashed while it was live) is
  reconciled whenever its run is read or a new start is asked for:
  - its process is gone without having reported done → the run is marked `interrupted`. Nothing is retried or swept
    automatically: the wallet stays `active` with whatever it still holds. The owner can start the task again (items
    already paid for are skipped), report it done (sweep), or reclaim it; the service's sweeper reclaims it anyway
    once the wallet expires.
  - its process is gone but it reported done during the run → `succeeded` (its /done already swept the wallet when the
    wallet says so); only the exit code went unseen, which the run's `note` says.
  - its process is still alive → it stays `running` (and blocks a duplicate start) until it exits, or until it has run
    longer than RUN_TIMEOUT_S, when it is killed and marked `timed_out`.
- A pid is only trusted if the process still looks like this wallet's subagent (`cereal.subagent <id>`), so a reused
  pid never keeps a dead run alive.

Each run's output (one JSON line per subagent action) goes to runs/<run_id>.log next to the record file (gitignored).
Seeds never appear there: the subagent loads its key from the keystore and prints only public data.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from . import config, deployments

RUN_TIMEOUT_S = int(os.getenv("CEREAL_RUN_TIMEOUT_S", "1200"))  # 20 minutes, as long as MainAgent.wait_subagent
LIVE = ("starting", "running")

_owned: set[str] = set()                # run ids this process started and is still watching
_owned_lock = threading.Lock()
_start_locks: dict[str, threading.Lock] = {}  # one start at a time per wallet
_start_locks_guard = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _refuse(reason: str, **evidence) -> dict:
    return {"ok": False, "refused": reason, **evidence}


def runs_dir() -> Path:
    return config.DEPLOYMENTS_FILE.resolve().parent / "runs"


def _wallet_lock(dep_id: str) -> threading.Lock:
    with _start_locks_guard:
        return _start_locks.setdefault(dep_id, threading.Lock())


def _is_owned(run_id: str) -> bool:
    with _owned_lock:
        return run_id in _owned


def _update_run(dep_id: str, run_id: str, **fields) -> dict | None:
    """Merge fields into the wallet's run, only if it is still this run. Returns the updated run."""
    with deployments._lock:  # the store's own lock (re-entrant): read, check and write as one step
        rec = deployments.get(dep_id)
        run = (rec or {}).get("run")
        if not run or run.get("id") != run_id:
            return None
        run = {**run, **fields}
        deployments.update(dep_id, run=run)
        return run


# ---- the process ----
def _spawn(cmd: list[str], **kw) -> subprocess.Popen:
    return subprocess.Popen(cmd, **kw)


def _alive(pid: int | None, dep_id: str) -> bool:
    """True if `pid` is still running and is this wallet's subagent (a reused pid does not count)."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False  # someone else's process: the pid was reused
    try:
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # cannot tell; the signal check said it exists
    return "cereal.subagent" in cmd and dep_id in cmd


def _log_tail(path: str | None, lines: int = 40) -> list[str]:
    try:
        return Path(path).read_text(errors="replace").splitlines()[-lines:] if path else []
    except OSError:
        return []


def _received_resources(path: str | None) -> list[dict]:
    """Public documents actually returned by successful purchases, distinct from ledger settlement."""
    resources = {}
    for line in _log_tail(path, lines=200):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("event") != "resource_received":
            continue
        data = event.get("data")
        if isinstance(data, dict) and isinstance(data.get("resource"), str) and isinstance(data.get("title"), str):
            resources[data["resource"]] = {k: data[k] for k in ("resource", "hash", "title", "summary", "sample", "findings") if k in data}
    return list(resources.values())


def _failure_reason(path: str | None) -> str | None:
    """The last line of the subagent's output that is not one of its JSON events (usually the exception)."""
    for line in reversed(_log_tail(path)):
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except ValueError:
            return line[:300]
    return None


def _summary_since(dep_id: str, started_at: str) -> str | None:
    """The summary the subagent reported with /done during this run (None if it did not report)."""
    rec = deployments.get(dep_id) or {}
    if rec.get("summary") and (rec.get("finished_at") or "") >= started_at:
        return rec["summary"]
    return None


def _watch(dep_id: str, run_id: str, proc: subprocess.Popen, log_file, started_at: str) -> None:
    """Wait for the subagent (at most RUN_TIMEOUT_S), then record how it ended."""
    status = None
    try:
        try:
            code = proc.wait(timeout=RUN_TIMEOUT_S)
            status = "succeeded" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            proc.kill()
            code = proc.wait()
            status = "timed_out"
    finally:
        try:
            log_file.close()
        except Exception:
            pass
        run = (deployments.get(dep_id) or {}).get("run") or {}
        error = None
        if status == "failed":
            error = _failure_reason(run.get("log")) or f"the subagent exited with code {code}"
        elif status == "timed_out":
            error = f"still running after {RUN_TIMEOUT_S // 60} minutes; the process was stopped"
        elif status is None:  # the watcher itself broke: never leave the run looking alive
            status, code, error = "failed", proc.poll(), "cereal lost track of the subagent process"
        _update_run(dep_id, run_id, status=status, exit_code=code, finished_at=_now(),
                    summary=_summary_since(dep_id, started_at), error=error, resources=_received_resources(run.get("log")))
        with _owned_lock:
            _owned.discard(run_id)


def reconcile(dep_id: str, rec: dict | None = None) -> dict | None:
    """A02: settle a run this process is not watching (it was started before a restart). Returns the run."""
    rec = rec or deployments.get(dep_id)
    run = (rec or {}).get("run")
    if not run or run.get("status") not in LIVE or _is_owned(run["id"]):
        return run
    pid = run.get("pid")
    summary = _summary_since(dep_id, run["started_at"])
    if _alive(pid, dep_id):
        started = datetime.fromisoformat(run["started_at"])
        if datetime.now(timezone.utc) - started <= timedelta(seconds=RUN_TIMEOUT_S):
            return run  # still working; it reports /done itself
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        return _update_run(dep_id, run["id"], status="timed_out", finished_at=_now(), summary=summary,
                           error=f"still running after {RUN_TIMEOUT_S // 60} minutes; the process was stopped") or run
    if summary:  # it reported /done before it exited: it finished its plan; only the exit code went unseen
        return _update_run(dep_id, run["id"], status="succeeded", finished_at=_now(), summary=summary,
                           note="finished while the cereal service was restarting; exit code not seen") or run
    status = (deployments.get(dep_id) or {}).get("status")
    after = ("The wallet stays active: start the task again (items already paid for are skipped), or reclaim it."
             if status == "active" else f"The wallet is {status}.")
    return _update_run(dep_id, run["id"], status="interrupted", finished_at=_now(),
                       error="the cereal service restarted while this task was running, and its process is gone "
                             f"without reporting done. {after}") or run


# ---- the plan ----
def _item_of(resource: str | None) -> str | None:
    """"http://localhost:8003/swell/agenda" → "agenda" (a vendor's item path ends with the catalog item)."""
    return resource.rstrip("/").rsplit("/", 1)[-1] if resource else None


def _already_paid(rec: dict) -> set[str]:
    """Items an earlier run of this wallet already paid for: settled, or handed to a vendor and not yet known failed."""
    return {_item_of(p.get("resource")) for p in rec.get("payments", [])
            if p.get("resource") and p.get("ok") is not False} - {None}


def _plan(rec: dict, envelope: Decimal, task: str | None = None, repeat_completed: bool = False) -> tuple[dict | None, list[str], dict | None]:
    """Plan exactly like cereal/chat.py. Returns (plan record, --buy specs, refusal)."""
    from . import pricing
    goal = task or rec.get("sentence") or rec["task"]
    p = pricing.plan(goal, envelope, allowed=rec.get("allowed_payees") or None)
    if not p["needs"]:
        return None, [], _refuse("nothing_to_buy", goal=goal,
                                 hint="name what to buy in the wallet's sentence, for example the agenda or the speaker list")
    if repeat_completed:
        pending = {_item_of(p.get("resource")) for p in rec.get("payments", [])
                   if p.get("resource") and p.get("ok") is not False and p.get("validated") is not True}
        if pending.intersection(p["needs"]):
            return None, [], _refuse("payment_pending", items=sorted(pending.intersection(p["needs"])))
    paid = set() if repeat_completed else _already_paid(rec)
    todo = [l for l in p["lines"] if l["item"] not in paid]  # a second run never buys the same item twice
    if not todo:
        return None, [], _refuse("already_bought", items=p["needs"])
    missing = [l["item"] for l in todo if not l["chosen"]]
    if missing:
        return None, [], _refuse("no_trusted_vendor", items=missing,
                                 rejected={l["item"]: [{"vendor": r.get("vendor"), "reason": r.get("reason")}
                                                       for r in l["rejected"]] for l in todo if not l["chosen"]})
    price = sum((Decimal(l["chosen"]["quote"]["price"]) for l in todo), Decimal(0))
    if price > envelope:  # the quotes themselves: the wallet already holds its budget (no buffer is added here)
        return None, [], _refuse("over_budget", requested=str(price), remaining=str(envelope))
    lines = []
    for l in todo:
        mine = Decimal(l["chosen"]["quote"]["price"])
        room = envelope - (price - mine)  # the most this item may cost while the others still fit
        lines.append({
            "item": l["item"], "vendor": l["chosen"]["vendor"], "url": l["chosen"]["url"], "payee": l["chosen"]["payee"],
            "price": l["chosen"]["quote"]["price"],
            "fallbacks": [{"vendor": f["vendor"], "url": f["url"], "payee": f["payee"], "price": f["quote"]["price"]}
                          for f in l["fallbacks"] if Decimal(f["quote"]["price"]) <= room],
            "rejected": [{"vendor": r.get("vendor"), "price": (r.get("quote") or {}).get("price") or r.get("catalog_price"),
                          "reason": r.get("reason"), "evidence": (r.get("evidence") or {}).get("hash")}
                         for r in l["rejected"]]})
    specs = ["|".join([f"{l['url']}@{l['price']}"] + [f"{f['url']}@{f['price']}" for f in l["fallbacks"]])
             for l in lines]
    plan = {"goal": goal, "envelope": str(envelope), "items": [l["item"] for l in lines], "price": str(price),
            "lines": lines, "buy": specs, "skipped_already_paid": sorted(set(p["needs"]) & paid)}
    return plan, specs, None


def _envelope(rec: dict) -> Decimal | None:
    """What the wallet can spend now: its live RLUSD balance (None if the ledger cannot be read)."""
    from . import service
    try:
        return Decimal(str(service.rlusd_balance(service.client(), rec["subwallet"])))
    except Exception:
        return None


def _startable(rec: dict | None) -> dict | None:
    """The refusal for a wallet that cannot run now, or None."""
    if not rec:
        return _refuse("unknown_deployment")
    if rec["status"] != "active" or rec.get("archived") or not rec.get("subwallet"):
        return _refuse("not_active", status=rec["status"])
    if datetime.now(timezone.utc) >= datetime.fromisoformat(rec["expires_at"]):
        return _refuse("expired", expires_at=rec["expires_at"])
    return None


# ---- the API ----
def current(dep_id: str) -> dict:
    rec = deployments.get(dep_id)
    if not rec:
        return _refuse("unknown_deployment")
    return {"ok": True, "run": reconcile(dep_id, rec)}


def _replay(rec: dict | None, task: str | None, request_id: str | None, keep_open: bool = False) -> dict | None:
    """A lost HTTP response must never turn a retry into a second purchase run."""
    if not rec or not request_id:
        return None
    prior = (rec.get("run_requests") or {}).get(request_id)
    if not prior:
        return None
    if prior.get("task") != task or prior.get("keep_open", False) != keep_open:
        return _refuse("request_conflict")
    run = reconcile(rec["id"], rec)
    if run and run["id"] == prior["run_id"]:
        return {"ok": True, "run": run}
    return _refuse("request_superseded", run_id=prior["run_id"])


def start(dep_id: str, task: str | None = None, request_id: str | None = None, keep_open: bool = False) -> dict:
    with _wallet_lock(dep_id):  # a second start for this wallet waits here, then sees the first run
        rec = deployments.get(dep_id)
        replay = _replay(rec, task, request_id, keep_open)
        if replay is not None:
            return replay
        refused = _startable(rec)
        if refused:
            return refused
        run = reconcile(dep_id, rec)
        if run and run.get("status") in LIVE:
            return _refuse("already_running", run=run)
        envelope = _envelope(rec)
        if envelope is None:
            return _refuse("balance_unavailable", hint="the ledger could not be read; nothing was started")
        if envelope <= 0:
            return _refuse("over_budget", remaining=str(envelope))
        plan, specs, refused = _plan(rec, envelope, task, repeat_completed=keep_open)
        if refused:
            return refused
        run_id = "r_" + uuid.uuid4().hex[:8]
        # Check and reserve in one step under the store's lock (machine-wide when the store's lock is), so two
        # services sharing a record file cannot both start this wallet. Planning above stays outside the lock.
        # Lock order: runs.py never takes service._main_wallet, so it can never wait on it while holding this one.
        with deployments._lock:
            rec = deployments.get(dep_id)  # planning took a while: the wallet may have been reclaimed meanwhile
            replay = _replay(rec, task, request_id, keep_open)
            if replay is not None:
                return replay
            refused = _startable(rec)
            if refused:
                return refused
            live = rec.get("run") or {}
            if live.get("status") in LIVE:
                return _refuse("already_running", run=live)
            started_at = _now()
            run = {"id": run_id, "deployment": dep_id, "status": "starting", "started_at": started_at,
                   "finished_at": None, "exit_code": None, "pid": None, "log": str(runs_dir() / f"{run_id}.log"),
                   "plan": plan, "task": task or plan["goal"], "request_id": request_id, "keep_open": keep_open, "summary": None, "error": None}
            with _owned_lock:
                _owned.add(run_id)
            requests = dict(rec.get("run_requests") or {})
            if request_id:
                requests[request_id] = {"task": task, "run_id": run_id, "keep_open": keep_open}
            deployments.update(dep_id, run=run, run_requests=requests, buy_only=True)  # from now on cereal co-signs only plan purchases
        return _launch(rec, run, specs)


def _launch(rec: dict, run: dict, specs: list[str]) -> dict:
    """Start the subagent for a reserved run (status starting, owned by this process) and its watcher."""
    dep_id, run_id, started_at, plan = rec["id"], run["id"], run["started_at"], run["plan"]
    log_path = Path(run["log"])
    task = f"{rec.get('name') or rec['task']}: buy {' + '.join(plan['items'])}"
    cmd = [sys.executable, "-m", "cereal.subagent", dep_id, task] + [x for sp in specs for x in ("--buy", sp)]
    env = {**os.environ, "CEREAL_SERVICE_URL": config.SERVICE_URL, "CEREAL_RUN_ID": run_id}  # the subagent talks to this service
    log_file = proc = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = open(log_path, "w")
        # Its own session: a signal to the service (Ctrl-C, reload) does not kill a subagent mid-payment; a restarted
        # service reconciles it (see the cleanup policy above).
        proc = _spawn(cmd, stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                      cwd=str(config.ROOT), env=env, start_new_session=True)
        run = _update_run(dep_id, run_id, status="running", pid=proc.pid)
        threading.Thread(target=_watch, args=(dep_id, run_id, proc, log_file, started_at), daemon=True,
                         name=f"cereal-run-{run_id}").start()
        return {"ok": True, "run": run}
    except Exception as e:  # never leave a run that looks alive but that nothing watches
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:
                pass
        if log_file is not None:
            log_file.close()
        with _owned_lock:
            _owned.discard(run_id)
        run = _update_run(dep_id, run_id, status="failed", finished_at=_now(),
                          exit_code=proc.poll() if proc is not None else None,
                          error=f"the subagent could not start: {type(e).__name__}: {e}"[:300])
        return {"ok": True, "run": run}
