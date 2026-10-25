"""A01/A02 unit tests (no network): starting a wallet's task, one live run at a time, and an honest record of how it ended.
The subagent process (subprocess.Popen) and the quote-based planner (pricing.plan) are replaced by fakes."""
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from cereal import config, deployments, runs

VENDOR_C = "r3NdoyQhgKorLo54v2VGkMrMTyPHbTXszs"
VENDOR_A = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"
SENTENCE = ("Run test: spend up to 0.5 RLUSD today, only at Vendor A and Vendor C. Get the Swell agenda. "
            "Ask me above 0.4. Sweep back when done.")
LINE = {"item": "agenda", "price": "0.15", "budget": "0.20", "fallbacks": [], "unaffordable": [],
        "chosen": {"vendor": "Vendor C", "url": "http://localhost:8003/swell/agenda", "payee": VENDOR_C,
                   "quote": {"ok": True, "price": "0.15", "payee": VENDOR_C}},
        "rejected": []}


class FakeProc:
    """A subagent process that runs until the test releases it."""
    def __init__(self, cmd, **kw):
        self.cmd, self.kw, self.pid, self.returncode = cmd, kw, 4242, None
        self.exit_code, self.killed = 0, False
        self.release = threading.Event()

    def wait(self, timeout=None):
        if not self.release.wait(timeout):
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        self.returncode = self.exit_code
        return self.exit_code

    def kill(self):
        self.killed, self.exit_code = True, -9
        self.release.set()

    def poll(self):
        return self.returncode


@pytest.fixture
def env(tmp_path, monkeypatch):
    from cereal import pricing, service
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(config, "SERVICE_URL", "http://127.0.0.1:8107")
    monkeypatch.setattr(service, "client", lambda: object())
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: Decimal("0.5"))
    plans, procs = [], []
    plan = {"needs": ["agenda"], "lines": [LINE]}

    def fake_plan(goal, envelope, bases=None, allowed=None):
        plans.append({"goal": goal, "envelope": envelope, "allowed": allowed})
        return {"ok": True, "reason": None, "total": "0.20", **plan}
    monkeypatch.setattr(pricing, "plan", fake_plan)

    def fake_popen(cmd, **kw):
        procs.append(FakeProc(cmd, **kw))
        return procs[-1]
    monkeypatch.setattr(runs, "_spawn", fake_popen)
    yield {"plans": plans, "procs": procs, "plan": plan, "mp": monkeypatch}
    for p in procs:  # never leave a watcher thread waiting
        p.release.set()


def wallet(**fields) -> str:
    rec = deployments.create("Run test", "0.5", [VENDOR_A, VENDOR_C], 24)
    deployments.update(rec["id"], **{"status": "active", "subwallet": "rSUB", "sentence": SENTENCE,
                                     "name": "Run test", "sweep_when_done": True, **fields})
    return rec["id"]


def api():
    from cereal import service
    return TestClient(service.app)


def wait_for(dep_id: str, status: str, timeout: float = 5) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        run = deployments.get(dep_id).get("run") or {}
        if run.get("status") == status:
            return run
        time.sleep(0.01)
    raise AssertionError(f"run never reached {status}: {deployments.get(dep_id).get('run')}")


def test_creating_a_wallet_never_starts_its_task(env):
    dep = wallet()
    assert api().get(f"/subagents/{dep}/run").json() == {"ok": True, "run": None}
    assert env["procs"] == [] and env["plans"] == []


def test_start_plans_like_chat_and_launches_the_subagent_without_blocking(env):
    dep = wallet()
    out = api().post(f"/subagents/{dep}/run").json()
    assert out["ok"] and out["run"]["status"] == "running" and out["run"]["pid"] == 4242
    assert env["plans"] == [{"goal": SENTENCE, "envelope": Decimal("0.5"), "allowed": [VENDOR_A, VENDOR_C]}]
    (proc,) = env["procs"]
    assert proc.cmd[1:5] == ["-m", "cereal.subagent", dep, "Run test: buy agenda"]
    assert proc.cmd[5:] == ["--buy", "http://localhost:8003/swell/agenda@0.15"]
    assert proc.kw["env"]["CEREAL_SERVICE_URL"] == "http://127.0.0.1:8107"
    assert proc.kw["cwd"] == str(config.ROOT) and proc.kw["stderr"] == subprocess.STDOUT
    assert proc.kw["start_new_session"] is True, "a signal to the service never kills a subagent mid-payment"
    run = deployments.get(dep)["run"]
    assert run["plan"]["lines"][0]["vendor"] == "Vendor C" and run["plan"]["buy"] == ["http://localhost:8003/swell/agenda@0.15"]
    assert run["log"].endswith(f"runs/{run['id']}.log") and os.path.exists(run["log"])
    assert api().get(f"/subagents/{dep}/run").json()["run"]["status"] == "running"  # GET while it works


def test_a_second_start_while_running_is_refused(env):
    dep = wallet()
    first = api().post(f"/subagents/{dep}/run").json()["run"]
    second = api().post(f"/subagents/{dep}/run").json()
    assert second["ok"] is False and second["refused"] == "already_running" and second["run"]["id"] == first["id"]
    assert len(env["procs"]) == 1, "no second subagent process"


def test_concurrent_starts_launch_one_subagent(env):
    dep = wallet()
    slow = env["mp"]
    from cereal import pricing
    real = pricing.plan
    slow.setattr(pricing, "plan", lambda *a, **k: (time.sleep(0.2), real(*a, **k))[1])
    out = []
    threads = [threading.Thread(target=lambda: out.append(runs.start(dep))) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(o.get("refused") or "started" for o in out) == ["already_running", "already_running", "started"]
    assert len(env["procs"]) == 1


def test_success_is_recorded_with_the_subagents_summary(env):
    dep = wallet()
    run = api().post(f"/subagents/{dep}/run").json()["run"]
    deployments.update(dep, summary="Run test: buy agenda: bought 1 of 1 x402 and 0 of 0 AP4M resources",
                       finished_at=datetime.now(timezone.utc).isoformat())  # what the subagent's /done writes
    env["procs"][0].release.set()
    done = wait_for(dep, "succeeded")
    assert done["id"] == run["id"] and done["exit_code"] == 0 and done["finished_at"] and done["error"] is None
    assert done["summary"].startswith("Run test: buy agenda: bought 1 of 1")
    again = api().post(f"/subagents/{dep}/run").json()  # finished runs never block a new one
    assert again["ok"] and again["run"]["id"] != run["id"]


def test_a_failed_process_is_recorded_with_its_reason(env):
    dep = wallet(summary="an old summary", finished_at="2026-01-01T00:00:00+00:00")
    run = api().post(f"/subagents/{dep}/run").json()["run"]
    with open(run["log"], "a") as f:
        f.write('{"event": "start", "data": {}}\nTraceback (most recent call last):\nRuntimeError: vendor down\n')
    env["procs"][0].exit_code = 1
    env["procs"][0].release.set()
    failed = wait_for(dep, "failed")
    assert failed["exit_code"] == 1 and failed["error"] == "RuntimeError: vendor down"
    assert failed["summary"] is None, "a summary from before this run is not this run's"
    assert deployments.get(dep)["status"] == "active", "nothing is swept or retried automatically"
    assert len(env["procs"]) == 1


def test_a_timeout_is_recorded_and_the_process_stopped(env):
    env["mp"].setattr(runs, "RUN_TIMEOUT_S", 0.05)
    dep = wallet()
    api().post(f"/subagents/{dep}/run")
    timed = wait_for(dep, "timed_out")
    assert env["procs"][0].killed and timed["exit_code"] == -9 and "process was stopped" in timed["error"]


def test_a_run_whose_process_is_gone_after_a_restart_is_interrupted(env):
    dep = wallet()
    started = datetime.now(timezone.utc).isoformat()
    deployments.update(dep, run={"id": "r_old", "deployment": dep, "status": "running", "pid": 999999,
                                 "started_at": started, "finished_at": None, "log": None, "plan": None})
    env["mp"].setattr(runs, "_alive", lambda pid, d: False)  # the old service's subagent died with it
    run = api().get(f"/subagents/{dep}/run").json()["run"]
    assert run["status"] == "interrupted" and run["finished_at"] and "restarted" in run["error"]
    assert deployments.get(dep)["status"] == "active", "the wallet stays active for the owner or the sweeper"
    assert api().post(f"/subagents/{dep}/run").json()["ok"], "the owner can start the task again"


def test_a_starting_run_left_by_a_crash_is_interrupted(env):
    dep = wallet()
    deployments.update(dep, run={"id": "r_crash", "deployment": dep, "status": "starting", "pid": None,
                                 "started_at": datetime.now(timezone.utc).isoformat(), "log": None})
    assert runs.current(dep)["run"]["status"] == "interrupted"


def test_a_live_orphan_blocks_a_duplicate_until_it_times_out(env):
    dep = wallet()
    killed = []
    env["mp"].setattr(runs, "_alive", lambda pid, d: True)
    env["mp"].setattr(runs.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    deployments.update(dep, run={"id": "r_orphan", "deployment": dep, "status": "running", "pid": 31337,
                                 "started_at": datetime.now(timezone.utc).isoformat(), "log": None})
    assert api().post(f"/subagents/{dep}/run").json()["refused"] == "already_running"
    old = (datetime.now(timezone.utc) - timedelta(seconds=runs.RUN_TIMEOUT_S + 60)).isoformat()
    deployments.update(dep, run={**deployments.get(dep)["run"], "started_at": old})
    assert runs.current(dep)["run"]["status"] == "timed_out" and killed and killed[0][0] == 31337
    assert env["procs"] == []


def test_a_sentence_that_names_nothing_to_buy_is_refused_and_starts_nothing(env):
    env["plan"].update(needs=[], lines=[])
    dep = wallet(sentence="Idle test: spend up to 0.1 RLUSD today, only at Vendor C. Keep funds when done.")
    out = api().post(f"/subagents/{dep}/run").json()
    assert out["ok"] is False and out["refused"] == "nothing_to_buy"
    assert env["procs"] == [] and deployments.get(dep).get("run") is None


def test_an_item_no_allowed_vendor_sells_is_refused(env):
    env["plan"].update(needs=["speakers"], lines=[{"item": "speakers", "chosen": None, "fallbacks": [], "price": None,
                                                   "rejected": [{"vendor": "Vendor A", "reason": "not_on_your_list"}]}])
    out = runs.start(wallet())
    assert out["refused"] == "no_trusted_vendor" and out["items"] == ["speakers"] and env["procs"] == []


def test_quotes_above_what_the_wallet_holds_are_refused(env):
    env["mp"].setattr(__import__("cereal.service", fromlist=["x"]), "rlusd_balance", lambda c, a: Decimal("0.10"))
    out = runs.start(wallet())
    assert out["refused"] == "over_budget" and out["requested"] == "0.15" and env["procs"] == []


def test_only_active_unexpired_wallets_run(env):
    reclaimed = wallet(status="reclaimed")
    assert api().post(f"/subagents/{reclaimed}/run").json()["refused"] == "not_active"
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert api().post(f"/subagents/{wallet(expires_at=past)}/run").json()["refused"] == "expired"
    assert api().post("/subagents/d_nope/run").status_code == 404
    assert env["procs"] == []


def test_a_pid_only_counts_if_it_is_this_wallets_subagent():
    assert runs._alive(None, "d_x") is False
    assert runs._alive(os.getpid(), "d_x") is False, "a reused pid (here: pytest) is not the subagent"
    p = subprocess.Popen(["sleep", "0"])
    p.wait()
    assert runs._alive(p.pid, "d_x") is False


def test_a_new_run_skips_items_an_earlier_run_already_paid_for(env):
    dep = wallet()
    deployments.record_payment(dep, {"to": VENDOR_C, "amount": "0.15", "rail": "x402", "ok": True,
                                     "resource": "http://localhost:8003/swell/agenda", "hash": "H1"})
    out = runs.start(dep)
    assert out["refused"] == "already_bought" and out["items"] == ["agenda"] and env["procs"] == []
    speakers = {**LINE, "item": "speakers", "chosen": {**LINE["chosen"], "url": "http://localhost:8003/swell/speakers",
                                                         "quote": {"ok": True, "price": "0.30", "payee": VENDOR_C}}}
    env["plan"].update(needs=["agenda", "speakers"], lines=[LINE, speakers])
    run = runs.start(dep)["run"]
    assert env["procs"][0].cmd[5:] == ["--buy", "http://localhost:8003/swell/speakers@0.30"]
    assert run["plan"]["items"] == ["speakers"] and run["plan"]["skipped_already_paid"] == ["agenda"]


def test_a_payment_known_to_have_failed_does_not_count_as_bought(env):
    dep = wallet()
    deployments.record_payment(dep, {"to": VENDOR_C, "amount": "0.15", "rail": "x402", "ok": False,
                                     "result": "tecPATH_PARTIAL", "resource": "http://localhost:8003/swell/agenda"})
    assert runs.start(dep)["ok"] and len(env["procs"]) == 1


def test_fallbacks_the_wallet_cannot_afford_are_dropped(env):
    fallback = {"vendor": "Vendor A", "url": "http://localhost:8000/swell/agenda", "payee": VENDOR_A,
                "quote": {"ok": True, "price": "0.25", "payee": VENDOR_A}}
    env["plan"]["lines"] = [{**LINE, "fallbacks": [fallback]}]
    env["mp"].setattr(__import__("cereal.service", fromlist=["x"]), "rlusd_balance", lambda c, a: Decimal("0.20"))
    runs.start(wallet())
    assert env["procs"][0].cmd[5:] == ["--buy", "http://localhost:8003/swell/agenda@0.15"]
    env["mp"].setattr(__import__("cereal.service", fromlist=["x"]), "rlusd_balance", lambda c, a: Decimal("0.5"))
    runs.start(wallet())
    assert env["procs"][1].cmd[5:] == ["--buy", "http://localhost:8003/swell/agenda@0.15|http://localhost:8000/swell/agenda@0.25"]


def test_an_unreadable_balance_refuses_instead_of_guessing(env):
    def down(c, a):
        raise ConnectionError("rpc down")
    env["mp"].setattr(__import__("cereal.service", fromlist=["x"]), "rlusd_balance", down)
    assert runs.start(wallet())["refused"] == "balance_unavailable" and env["procs"] == [] and env["plans"] == []


def test_a_wallet_reclaimed_while_planning_does_not_start(env):
    dep = wallet()
    from cereal import pricing
    real = pricing.plan
    def plan_then_sweep(*a, **k):
        out = real(*a, **k)
        deployments.update(dep, status="reclaimed")  # the sweeper got there first
        return out
    env["mp"].setattr(pricing, "plan", plan_then_sweep)
    assert runs.start(dep)["refused"] == "not_active" and env["procs"] == []


def test_a_launch_that_breaks_is_recorded_as_failed_and_never_blocks_the_next_start(env):
    dep = wallet()
    def broken(cmd, **kw):
        raise ValueError("bad argument")
    env["mp"].setattr(runs, "_spawn", broken)
    run = runs.start(dep)["run"]
    assert run["status"] == "failed" and "ValueError: bad argument" in run["error"] and not runs._is_owned(run["id"])
    started = []
    def thread_fails(*a, **k):
        raise RuntimeError("can't start new thread")
    env["mp"].setattr(runs, "_spawn", lambda cmd, **kw: started.append(FakeProc(cmd, **kw)) or started[-1])
    env["mp"].setattr(runs.threading.Thread, "start", thread_fails)
    run = runs.start(dep)["run"]
    assert run["status"] == "failed" and started[0].killed, "a process nothing watches is stopped"


def test_an_orphan_that_reported_done_before_it_exited_succeeded(env):
    dep = wallet()
    started = datetime.now(timezone.utc).isoformat()
    deployments.update(dep, status="reclaimed", summary="bought 1 of 1", finished_at=datetime.now(timezone.utc).isoformat(),
                       run={"id": "r_done", "deployment": dep, "status": "running", "pid": 999999, "started_at": started})
    env["mp"].setattr(runs, "_alive", lambda pid, d: False)
    run = runs.current(dep)["run"]
    assert run["status"] == "succeeded" and run["summary"] == "bought 1 of 1" and "exit code not seen" in run["note"]


def test_a_run_another_service_reserved_while_this_one_planned_is_not_doubled(env):
    dep = wallet()
    from cereal import pricing
    real = pricing.plan
    def plan_while_another_service_starts(*a, **k):
        out = real(*a, **k)
        deployments.update(dep, run={"id": "r_elsewhere", "deployment": dep, "status": "starting", "pid": None,
                                     "started_at": datetime.now(timezone.utc).isoformat()})
        return out
    env["mp"].setattr(pricing, "plan", plan_while_another_service_starts)
    out = runs.start(dep)
    assert out["refused"] == "already_running" and out["run"]["id"] == "r_elsewhere" and env["procs"] == []


def test_chat_task_uses_existing_wallet_policy_and_idempotent_retry(env):
    dep = wallet(approval_threshold="0.4")
    before = deployments.get(dep)
    body = {"task": 'Get the speaker list. Use my "Run test" wallet.', "request_id": "chat-1"}
    first = api().post(f"/subagents/{dep}/run", json=body).json()
    assert first["ok"] and first["run"]["task"] == body["task"]
    assert env["plans"][0] == {"goal": body["task"], "envelope": Decimal("0.5"), "allowed": [VENDOR_A, VENDOR_C]}
    after = deployments.get(dep)
    for key in ("sentence", "budget", "allowed_payees", "approval_threshold", "expires_at", "sweep_when_done"):
        assert after[key] == before[key]
    assert api().post(f"/subagents/{dep}/run", json=body).json()["run"]["id"] == first["run"]["id"]
    env["procs"][0].release.set()
    wait_for(dep, "succeeded")
    assert api().post(f"/subagents/{dep}/run", json=body).json()["run"]["id"] == first["run"]["id"]
    assert len(env["procs"]) == len(env["plans"]) == 1
    conflict = api().post(f"/subagents/{dep}/run", json={**body, "task": "Buy another item"}).json()
    assert conflict["refused"] == "request_conflict"
    newer = api().post(f"/subagents/{dep}/run", json={**body, "request_id": "chat-2"}).json()
    assert newer["ok"]
    assert api().post(f"/subagents/{dep}/run", json=body).json()["refused"] == "request_superseded"
    assert len(env["procs"]) == 2


def test_chat_does_not_accept_policy_overrides_or_blank_tasks(env):
    dep = wallet()
    for body in ({"task": "agenda", "budget": "1000"}, {"task": "agenda", "allowed_payees": []},
                 {"task": "  "}, {"task": "a" * 4001}, {"request_id": " "}):
        assert api().post(f"/subagents/{dep}/run", json=body).status_code == 422
    assert not env["procs"] and not env["plans"]


def test_chat_refuses_archived_wallet_and_unsupported_task(env):
    dep = wallet(archived=True)
    assert api().post(f"/subagents/{dep}/run", json={"task": "agenda"}).json()["refused"] == "not_active"
    deployments.update(dep, archived=False)
    env["plan"].update(needs=[], lines=[])
    assert api().post(f"/subagents/{dep}/run", json={"task": "Unlisted research"}).json()["refused"] == "nothing_to_buy"
    assert not env["procs"]


def test_received_research_content_is_returned_with_finished_run(env):
    import json
    dep = wallet()
    run = api().post(f"/subagents/{dep}/run").json()["run"]
    document = {"resource": "http://a/swell/market-data", "title": "Market brief", "summary": "Sample research",
                "findings": ["Sample finding"], "sample": True, "hash": "ABC", "private_metadata": "omit"}
    with open(run["log"], "a") as f:
        f.write(json.dumps({"event": "resource_received", "data": document}) + "\n")
        f.write(json.dumps({"event": "refused", "data": {"title": "Not retrieved"}}) + "\n")
    env["procs"][0].release.set()
    done = wait_for(dep, "succeeded")
    assert done["resources"] == [{k: v for k, v in document.items() if k != "private_metadata"}]


def test_chat_completion_keeps_wallet_open_but_explicit_finish_sweeps(env):
    from cereal import service
    dep = wallet()
    out = runs.start(dep, task="get agenda", request_id="chat-1", keep_open=True)
    run_id = out["run"]["id"]
    assert env["procs"][0].kw["env"]["CEREAL_RUN_ID"] == run_id
    swept = []
    env["mp"].setattr(service, "reclaim", lambda id: swept.append(id) or {"ok": True})
    client = api()
    response = client.post(f"/subagents/{dep}/done", json={"summary": "got agenda", "run_id": run_id}).json()
    assert response["status"] == "active"
    assert not swept
    assert runs.start(dep, task="get agenda", request_id="chat-1", keep_open=True)["run"]["id"] == run_id
    assert runs.start(dep, task="get agenda", request_id="chat-1", keep_open=False)["refused"] == "request_conflict"
    assert client.post(f"/subagents/{dep}/done", json={"summary": "stale", "run_id": "old"}).json()["refused"] == "stale_run"
    client.post(f"/subagents/{dep}/done", json={"summary": "owner finished"})
    assert swept == [dep]


def test_chat_accepts_multiple_new_requests_and_reports_empty_balance(env):
    from cereal import service
    dep = wallet()
    first = runs.start(dep, task="get agenda", request_id="one", keep_open=True)["run"]
    env["procs"][-1].release.set()
    wait_for(dep, "succeeded")
    deployments.record_payment(dep, {"to": VENDOR_C, "amount": "0.15", "ok": True, "validated": True,
                                     "resource": "http://localhost:8003/swell/agenda", "hash": "SETTLED"})
    second = runs.start(dep, task="get agenda", request_id="two", keep_open=True)["run"]
    assert second["id"] != first["id"]
    assert len(env["procs"]) == 2
    env["procs"][-1].release.set()
    wait_for(dep, "succeeded")
    env["mp"].setattr(service, "rlusd_balance", lambda *_: Decimal("0"))
    out = runs.start(dep, task="get agenda", request_id="three", keep_open=True)
    assert out["refused"] == "over_budget" and out["remaining"] == "0"
    assert len(env["procs"]) == 2
    assert deployments.get(dep)["status"] == "active"


def test_new_chat_request_cannot_repay_an_unresolved_purchase(env):
    dep = wallet()
    deployments.record_payment(dep, {"to": VENDOR_C, "amount": "0.15", "ok": None,
                                     "resource": "http://localhost:8003/swell/agenda", "hash": "PENDING"})
    assert runs.start(dep, task="get agenda", request_id="new", keep_open=True)["refused"] == "payment_pending"
    assert not env["procs"]


def test_explicit_site_specs_are_bound_to_the_request_id(env):
    dep = wallet()
    specs = ["http://localhost:8003/swell/agenda@0.15"]
    first = runs.start(dep, specs=specs, task="site research", request_id="site-request")
    assert first["ok"]
    assert runs.start(dep, specs=specs, task="site research", request_id="site-request")["run"]["id"] == first["run"]["id"]
    changed = ["http://localhost:8003/swell/speakers@0.15"]
    assert runs.start(dep, specs=changed, task="site research", request_id="site-request")["refused"] == "request_conflict"
    assert len(env["procs"]) == 1
