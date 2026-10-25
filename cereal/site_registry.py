"""Sites, each user's private list (owner: unit 2). Contract in docs/SITES.md.

Stored next to the record file (<records>.sites.json), per owner. Trust tiers: "public" (the payee holds a valid
cereal credential: cereal co-signs within the wallet's rules), "private" (only this owner's wallets may pay it, and
every payment needs the owner's Ledger), "free" (no paywall), "blocked" (never paid; reason and evidence kept).
"""
from __future__ import annotations


def add(owner_id: str, probe: dict) -> dict:
    """Store a probed site for this owner. {ok: True, site} or a refusal (not_accessible, site_blocked: stored as
    blocked so the owner sees why)."""
    raise NotImplementedError


def list_for(owner_id: str) -> list[dict]:
    raise NotImplementedError


def get(owner_id: str, site_id: str) -> dict | None:
    raise NotImplementedError


def remove(owner_id: str, site_id: str) -> bool:
    raise NotImplementedError


def update(owner_id: str, site_id: str, **fields) -> dict | None:
    raise NotImplementedError


def block(owner_id: str, payee: str, reason: str, evidence: dict | None = None) -> list[dict]:
    """Block every site of this owner that pays `payee` (e.g. paid_not_delivered). Returns the sites changed."""
    raise NotImplementedError


def trust_for(owner_id: str | None, payee: str) -> str | None:
    """"private" if this owner has a non-blocked private site paying `payee`, "blocked" if blocked, else None."""
    raise NotImplementedError
