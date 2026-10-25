"""A05/A06 offline tests: folders, rename, move, archive and restore. Metadata only: no ledger call, no policy change."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from cereal import config, deployments, folders

PAYEE = "rGrhEwizViewpp8b91RTdUV2MpdWUdaEay"
SUB = "rnjvujdQv8N8noFhtDKCxDSFFUxntc1nWR"
POLICY = ("status", "budget", "allowed_payees", "expires_at", "vendor_class", "approval_threshold", "sweep_when_done",
          "subwallet", "subagent", "tag", "payments", "hashes", "task", "returned")


@pytest.fixture
def api(tmp_path, monkeypatch):
    from cereal import service
    monkeypatch.setattr(config, "DEPLOYMENTS_FILE", tmp_path / "deployments.json")
    monkeypatch.setattr(service, "client", lambda: object())
    monkeypatch.setattr(service, "rlusd_balance", lambda c, a: Decimal("0.4"))
    for name in ("ledger_reclaim", "ledger_retire", "fund_burner", "cosign_and_submit", "cosign_combine", "submit_capture"):
        monkeypatch.setattr(service, name, lambda *a, _n=name, **k: pytest.fail(f"metadata must not call {_n}"))
    return TestClient(service.app)


def _wallet(status="active", **extra):
    rec = deployments.create("pull the agenda", "1", [PAYEE])
    return deployments.update(rec["id"], status=status, subwallet=SUB, name="Agenda",
                              payments=[{"to": PAYEE, "amount": "0.25", "ok": True, "result": "tesSUCCESS",
                                         "hash": "H1", "at": "2026-10-24T19:32:27+00:00"}], **extra)


def _policy(rec):
    return {k: rec.get(k) for k in POLICY}


# ---- folders ----

def test_create_trims_and_persists_atomically(api):
    out = api.post("/folders", json={"name": "  Market Research  "}).json()
    assert out["ok"] and out["folder"]["name"] == "Market Research" and out["folder"]["id"].startswith("f_")
    assert api.get("/folders").json() == [out["folder"]]
    assert folders.path() == config.DEPLOYMENTS_FILE.with_name("deployments.folders.json") and folders.path().exists()
    assert sorted(p.name for p in folders.path().parent.iterdir()) == ["deployments.folders.json"]  # no temp left


def test_duplicates_are_refused_ignoring_case(api):
    first = api.post("/folders", json={"name": "Ops"}).json()["folder"]
    dup = api.post("/folders", json={"name": " ops "}).json()
    assert dup == {"ok": False, "refused": "folder_exists", "folder": first}
    assert api.get("/folders").json() == [first]


@pytest.mark.parametrize("name,why", [("", "empty"), ("   ", "empty"), (None, "empty"), ("x" * 61, "too_long"),
                                      ("a\nb", "unprintable")])
def test_invalid_folder_names_are_refusals(api, name, why):
    r = api.post("/folders", json={"name": name})
    assert r.status_code == 200 and r.json() == {"ok": False, "refused": "invalid_folder_name", "problem": why, "limit": 60}
    assert api.get("/folders").json() == []


def test_sixty_characters_is_allowed(api):
    assert api.post("/folders", json={"name": "x" * 60}).json()["ok"]


def test_folders_include_names_records_already_use(api):
    _wallet(folder="From Creation")
    stored = api.post("/folders", json={"name": "Stored"}).json()["folder"]
    assert api.get("/folders").json() == [stored, {"id": "From Creation", "name": "From Creation"}]
    # creating a name only records use stores it under the records' spelling, so its wallets stay in it
    kept = api.post("/folders", json={"name": "from creation"}).json()
    assert kept["ok"] and kept["folder"]["name"] == "From Creation" and kept["folder"]["id"].startswith("f_")
    assert api.get("/folders").json() == [stored, kept["folder"]]
    assert api.post("/folders", json={"name": "FROM CREATION"}).json()["refused"] == "folder_exists"


def test_one_folder_however_records_spell_it(api):
    ops = api.post("/folders", json={"name": "Ops"}).json()["folder"]
    _wallet(folder="ops"); _wallet(folder=" Ops "); _wallet(folder="Padded ")
    assert api.get("/folders").json() == [ops, {"id": "Padded ", "name": "Padded "}]
    assert api.post("/folders", json={"name": "Café"}).json()["ok"]  # decomposed é
    assert api.post("/folders", json={"name": "café"}).json()["refused"] == "folder_exists"  # composed é


def test_a_folder_stays_listed_when_its_last_wallet_leaves(api):
    rec = _wallet(folder="From Creation")
    assert api.post(f"/subagents/{rec['id']}/meta", json={"folder": None}).json()["ok"]
    assert [f["name"] for f in api.get("/folders").json()] == ["From Creation"]


# ---- meta: rename, move ----

def test_rename_and_move_touch_only_metadata(api):
    rec = _wallet()
    api.post("/folders", json={"name": "Research"})
    out = api.post(f"/subagents/{rec['id']}/meta", json={"name": "  Swell agenda ", "folder": "research"}).json()
    assert out["ok"] and out["changed"] == ["folder", "name"]
    assert out["wallet"]["name"] == "Swell agenda" and out["wallet"]["folder"] == "Research"  # canonical name
    assert out["wallet"]["balance"] == "0.4"  # the API record shape (service._with_balance)
    after = deployments.get(rec["id"])
    assert _policy(after) == _policy(rec) and after["name"] == "Swell agenda" and after["folder"] == "Research"
    assert set(after) - set(rec) == {"folder"}  # nothing else was added

    out = api.post(f"/subagents/{rec['id']}/meta", json={"folder": None}).json()
    assert out["changed"] == ["folder"] and deployments.get(rec["id"])["folder"] is None
    assert deployments.get(rec["id"])["name"] == "Swell agenda"  # fields not sent are left alone


def test_a_listed_folder_with_odd_spelling_can_be_chosen(api):
    _wallet(folder=" Padded ")
    rec = _wallet()
    out = api.post(f"/subagents/{rec['id']}/meta", json={"folder": "padded"}).json()
    assert out["ok"] and out["wallet"]["folder"] == " Padded "  # the listed spelling, so the UI files it together


def test_a_refused_change_stores_no_folder(api):
    _wallet(folder="Derived")
    rec = _wallet()
    r = api.post(f"/subagents/{rec['id']}/meta", json={"folder": "Derived", "archived": None}).json()
    assert r["refused"] == "invalid_archived"
    assert not folders.path().exists() and deployments.get(rec["id"]) == rec


@pytest.mark.parametrize("body", [{"status": "active"}, {"budget": "5"}, {"allowed_payees": [SUB]},
                                  {"expires_at": "2099-01-01T00:00:00+00:00"}, {"name": "ok", "status": "active"},
                                  {"archived": "false"}, {"archived": 0}, {"name": 5}])
def test_anything_but_name_folder_archived_is_a_422(api, body):
    rec = _wallet(status="retired")
    r = api.post(f"/subagents/{rec['id']}/meta", json=body)
    assert r.status_code == 422
    assert deployments.get(rec["id"]) == rec


@pytest.mark.parametrize("body,refused", [({"name": ""}, "invalid_name"), ({"name": "y" * 81}, "invalid_name"),
                                          ({"name": None}, "invalid_name"), ({"folder": "Nowhere"}, "unknown_folder"),
                                          ({"archived": None}, "invalid_archived")])
def test_bad_values_are_refusals_and_change_nothing(api, body, refused):
    rec = _wallet()
    r = api.post(f"/subagents/{rec['id']}/meta", json=body)
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["refused"] == refused
    assert deployments.get(rec["id"]) == rec


def test_eighty_character_name_is_allowed(api):
    rec = _wallet()
    assert api.post(f"/subagents/{rec['id']}/meta", json={"name": "n" * 80}).json()["wallet"]["name"] == "n" * 80


def test_unknown_wallet_is_a_404(api):
    assert api.post("/subagents/d_nope/meta", json={"name": "x"}).status_code == 404


# ---- A06: archive is presentation only ----

@pytest.mark.parametrize("status", ["active", "reclaimed", "retired"])
def test_archive_then_restore_never_changes_status_or_funds(api, status):
    rec = _wallet(status=status, returned="0.5" if status != "active" else None)
    archived = api.post(f"/subagents/{rec['id']}/meta", json={"archived": True}).json()["wallet"]
    assert archived["archived"] is True and archived["status"] == status
    restored = api.post(f"/subagents/{rec['id']}/meta", json={"archived": False}).json()["wallet"]
    assert restored["archived"] is False and restored["status"] == status
    after = deployments.get(rec["id"])
    assert _policy(after) == _policy(rec)  # no reclaim, no retire, no payment, no budget change


def test_a_retired_wallet_cannot_be_revived_through_meta(api):
    rec = _wallet(status="retired")
    r = api.post(f"/subagents/{rec['id']}/meta", json={"archived": False, "status": "active"})
    assert r.status_code == 422 and deployments.get(rec["id"])["status"] == "retired"


def test_an_archived_active_wallet_is_still_swept_at_expiry(api, monkeypatch):
    from cereal import service
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    rec = _wallet(expires_at=past)
    api.post(f"/subagents/{rec['id']}/meta", json={"archived": True})
    swept = []
    monkeypatch.setattr(service, "reclaim", lambda dep_id: swept.append(dep_id) or {"ok": True, "returned": "0.75"})
    assert service.sweep_once()["swept"] == [{"deployment": rec["id"], "returned": "0.75"}] and swept == [rec["id"]]


def test_the_export_keeps_archived_wallets(api, monkeypatch):
    from cereal import directory
    monkeypatch.setattr(directory, "list_vendors", lambda: [])
    rec = _wallet(status="retired")
    api.post(f"/subagents/{rec['id']}/meta", json={"archived": True})
    rows = api.get("/export.json").json()["rows"]
    assert [r["deployment"] for r in rows] == [rec["id"]] and rows[0]["tx_hash"] == "H1"
