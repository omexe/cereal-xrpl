"""A05, A06: wallet names, folders, and presentation-only archiving. Metadata never touches payment policy.

Contract (frontend/src/api.ts):
    GET  /folders                         → [{id, name}]
    POST /folders  {name}                 → {ok, folder: {id, name}} | refusal
    POST /subagents/{id}/meta  {name?, folder?: str | null, archived?: bool} → {ok, wallet} | refusal

Folders (A05): stored folders plus every folder name a record already uses. A new name is trimmed, 1-60 printable
characters and unique ignoring case (`invalid_folder_name`, `folder_exists`). Creating a name only records use, or
moving a wallet into or out of one, stores it, so a folder never vanishes because its last wallet left.

Meta (A05): the body may carry only `name` (str), `folder` (str or null) and `archived` (a JSON boolean). Any other
field (status, budget, allowed_payees, expires_at, ...) or a wrong type (`"archived": "false"`) is a 422 before
anything is read or written, so this endpoint can never change what a wallet may spend, where, or until when.
A well-typed but invalid value is a refusal result: `invalid_name` (not 1-80 printable characters), `unknown_folder`
(folder names resolve ignoring case to the listed spelling; null = unfiled), `invalid_archived` (null). Only the
fields sent are written, with `deployments.update`. Unknown id → 404.

Archive vs reclaim/retire (A06):
- Archiving is presentation only: it sets `archived: true` so the app files the wallet under Archived Wallets. It
  sends no transaction, moves no funds, reclaims nothing and deletes no account.
- An archived active wallet keeps its RLUSD and its rules; its subagent can still spend within them, and the sweeper
  still reclaims it at expiry and retires it afterwards. Reclaim (POST /subagents/{id}/reclaim) is what returns funds.
- Restoring (`archived: false`) only unhides. It never changes `status`: a reclaimed wallet stays reclaimed and a
  retired account stays retired (deleted on the ledger); no flag can bring one back.
- The export (/export.json, /export.csv) lists every wallet's payments, archived or not.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool

from .. import deployments, folders

router = APIRouter()
MAX_WALLET_NAME = 80


class FolderCreate(BaseModel):
    name: str | None = None


class MetaChange(BaseModel):
    model_config = ConfigDict(extra="forbid")  # status, budget, payees, expiry: never through this endpoint
    name: str | None = None
    folder: str | None = None
    archived: StrictBool | None = None


@router.get("/folders")
def list_folders() -> list[dict]:
    return folders.all_()


@router.post("/folders")
def create_folder(req: FolderCreate) -> dict:
    from .. import service
    name, why = folders.clean(req.name, folders.MAX_NAME)
    if why:
        return service._refuse("invalid_folder_name", problem=why, limit=folders.MAX_NAME)
    folder, created = folders.create(name)
    if not created:
        return service._refuse("folder_exists", folder=folder)
    return {"ok": True, "folder": folder}


@router.post("/subagents/{dep_id}/meta")
def update_meta(dep_id: str, req: MetaChange) -> dict:
    from .. import service
    rec = deployments.get(dep_id)
    if not rec:
        raise HTTPException(404, "unknown deployment")
    sent = req.model_fields_set
    fields: dict = {}
    if "name" in sent:
        name, why = folders.clean(req.name, MAX_WALLET_NAME)
        if why:
            return service._refuse("invalid_name", problem=why, limit=MAX_WALLET_NAME)
        fields["name"] = name
    if "folder" in sent:
        if req.folder is None:
            fields["folder"] = None  # unfiled: back to Disposable Wallets
        else:
            folder = folders.find(req.folder)
            if not folder:
                return service._refuse("unknown_folder", folder=req.folder, known=[f["name"] for f in folders.all_()])
            fields["folder"] = folder["name"]
    if "archived" in sent:
        if req.archived is None:
            return service._refuse("invalid_archived", hint="archived is true or false")
        fields["archived"] = req.archived
    if "folder" in fields:  # validated: keep both folders listed, even the one this wallet leaves empty
        folders.ensure(rec.get("folder"))
        folders.ensure(fields["folder"])
    if fields:
        rec = deployments.update(dep_id, **fields)
    return {"ok": True, "wallet": service._with_balance(rec), "changed": sorted(fields)}
