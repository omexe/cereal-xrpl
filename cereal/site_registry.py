"""Sites, each user's private list (owner: unit 2). Contract in docs/SITES.md.

Stored next to the record file (<records>.sites.json), per owner. Trust tiers: "public" (the payee holds a valid
cereal credential: cereal co-signs within the wallet's rules), "private" (only this owner's wallets may pay it, and
every payment needs the owner's Ledger), "free" (no paywall), "blocked" (never paid; reason and evidence kept).

Store: {"u_<owner>": {"s_<id>": site}}, written atomically under a machine-wide lock (cereal/sidestore.py). A site is
the probe's fields plus {id, owner, name, trust, blocked_reason, blocked_by, blocked_at, blocked_evidence, added_at,
probed_at, wallets}. Nothing here grants trust on the ledger: "private" only lets the owner's own Ledger sign payments
to that payee from the owner's own wallets (cereal never co-signs them; see service._cosign_deployment).

Blocks: a probe block (verdict "block") is about one URL (its price, its host's toml) and is re-evaluated when the
owner adds the same URL again. A block from evidence (e.g. paid_not_delivered, via block()) is about the address: it
blocks every site of the owner paying it, wins over any private listing in trust_for, and is kept when the URL, or
another URL paying the same address, is added again.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from .sidestore import SideStore

_store = SideStore(".sites.json")
PROBE = "probe"  # blocked_by for a block the probe's checks decided
_OWN = ("id", "owner", "name", "trust", "blocked_reason", "blocked_by", "blocked_at", "blocked_evidence",
        "added_at", "probed_at", "wallets")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pay_to(site: dict) -> str | None:
    return (site.get("payment") or {}).get("pay_to")


def _probe_block(probe: dict) -> tuple[str, dict] | None:
    """(reason, evidence) when the probe says this site must never be paid, else None."""
    revoked = probe.get("credential") == "revoked"
    if probe.get("verdict") != "block" and not revoked and probe.get("trust_hint") != "blocked":
        return None
    reasons = [r for r in probe.get("verdict_reasons") or [] if r]
    if revoked and not reasons:
        reasons = ["The payee's cereal credential was revoked."]
    failed = [c for c in probe.get("checks") or [] if isinstance(c, dict) and c.get("ok") is False]
    return " ".join(reasons) or "A safety check failed.", {"verdict_reasons": reasons, "checks": failed}


def _tier(probe: dict) -> str:
    if probe.get("credential") == "valid":
        return "public"
    if probe.get("kind") == "free":
        return "free"
    return "private"


def _evidence_block(sites: dict, pay_to: str | None) -> dict | None:
    """A site of this owner blocked by evidence (not by the probe) that pays the same address."""
    if not pay_to:
        return None
    return next((s for s in sites.values() if s.get("trust") == "blocked" and s.get("blocked_by") not in (None, PROBE)
                 and _pay_to(s) == pay_to), None)


def add(owner_id: str, probe: dict) -> dict:
    """Store a probed site for this owner. {ok: True, site} or a refusal (not_accessible, site_blocked: stored as
    blocked so the owner sees why)."""
    if not owner_id:
        raise ValueError("a site always has an owner")
    if not probe.get("ok"):
        return probe  # the probe's own refusal (invalid_url, unsafe_url): nothing stored
    kind = probe.get("kind")
    if kind not in ("free", "payable"):  # unreachable, unpayable (or anything the probe did not classify)
        return {"ok": False, "refused": "not_accessible", "url": probe.get("url"), "kind": kind,
                "reason": probe.get("reason"), "probe": probe}
    now = _now()
    with _store.locked():
        store = _store.load()
        sites = store.setdefault(owner_id, {})
        prior = next((s for s in sites.values() if s.get("url") == probe.get("url")), None)
        fields = {k: v for k, v in probe.items() if k != "ok" and k not in _OWN}
        site = {**(prior or {}), **fields}
        if prior is None:
            sid = "s_" + secrets.token_hex(6)
            while any(sid in s for s in store.values()):
                sid = "s_" + secrets.token_hex(6)
            site.update(id=sid, owner=owner_id, added_at=now, wallets=[])
        site.update(name=probe.get("title") or probe.get("host") or probe.get("url"), probed_at=now)
        kept = _evidence_block(sites, _pay_to(site))
        blocked = _probe_block(probe)
        if kept:  # evidence outlives a re-probe: the site took money without delivering
            site.update(trust="blocked", blocked_reason=kept["blocked_reason"], blocked_by=kept["blocked_by"],
                        blocked_at=kept.get("blocked_at"), blocked_evidence=kept.get("blocked_evidence"))
        elif blocked:
            site.update(trust="blocked", blocked_reason=blocked[0], blocked_by=PROBE, blocked_at=now,
                        blocked_evidence=blocked[1])
        else:
            site.update(trust=_tier(probe), blocked_reason=None, blocked_by=None, blocked_at=None,
                        blocked_evidence=None)
        sites[site["id"]] = site
        _store.save(store)
    if site["trust"] == "blocked":
        return {"ok": False, "refused": "site_blocked", "reason": site["blocked_reason"], "site": site,
                "refreshed": prior is not None}
    return {"ok": True, "site": site, "refreshed": prior is not None}


def list_for(owner_id: str) -> list[dict]:
    return list(_store.load().get(owner_id, {}).values()) if owner_id else []


def get(owner_id: str, site_id: str) -> dict | None:
    return _store.load().get(owner_id, {}).get(site_id) if owner_id else None


def remove(owner_id: str, site_id: str) -> bool:
    with _store.locked():
        store = _store.load()
        if site_id not in store.get(owner_id, {}):
            return False
        del store[owner_id][site_id]
        _store.save(store)
        return True


def update(owner_id: str, site_id: str, **fields) -> dict | None:
    """Merge fields into one of this owner's sites (its id and owner never change). The site, or None if unknown."""
    with _store.locked():
        store = _store.load()
        site = store.get(owner_id, {}).get(site_id)
        if site is None:
            return None
        site.update({k: v for k, v in fields.items() if k not in ("id", "owner")})
        _store.save(store)
        return site


def block(owner_id: str, payee: str, reason: str, evidence: dict | None = None) -> list[dict]:
    """Block every site of this owner that pays `payee` (e.g. paid_not_delivered). Returns the sites changed."""
    if not owner_id or not payee:
        return []
    changed = []
    with _store.locked():
        store = _store.load()
        for site in store.get(owner_id, {}).values():
            if _pay_to(site) == payee and (site.get("trust") != "blocked" or site.get("blocked_by") == PROBE):
                site.update(trust="blocked", blocked_reason=reason, blocked_by=reason, blocked_at=_now(),
                            blocked_evidence=evidence)
                changed.append(site)
        if changed:
            _store.save(store)
    return changed


def trust_for(owner_id: str | None, payee: str) -> str | None:
    """"private" if this owner has a non-blocked private site paying `payee`, "blocked" if blocked, else None."""
    if not owner_id or not payee:
        return None
    sites = [s for s in _store.load().get(owner_id, {}).values() if _pay_to(s) == payee]
    if _evidence_block({s["id"]: s for s in sites}, payee):  # evidence about the address: wins over every listing
        return "blocked"
    if any(s.get("trust") == "private" for s in sites):  # a probe block is about one URL (its price, its host's toml)
        return "private"
    return "blocked" if any(s.get("trust") == "blocked" for s in sites) else None
