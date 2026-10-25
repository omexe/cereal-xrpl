"""Sites, each user's private list (owner: unit 2). Contract in docs/SITES.md.

Stored next to the record file (<records>.sites.json), per owner. Trust tiers: "public" (the payee holds a valid
cereal credential: cereal co-signs within the wallet's rules), "private" (only this owner's wallets may pay it, and
every payment needs the owner's Ledger), "free" (no paywall), "blocked" (never paid; reason and evidence kept).

Store: {"u_<owner>": {"s_<id>": site}}, written atomically under a machine-wide lock (cereal/sidestore.py). A site is
the probe's fields plus {id, owner, name, trust, blocked_reason, blocked_by, blocked_at, blocked_evidence, added_at,
probed_at, wallets}. Nothing here grants trust on the ledger: "private" only lets the owner's own Ledger sign payments
to that payee from the owner's own wallets (cereal never co-signs them; see service._cosign_deployment).

Blocks:
- a probe block (verdict "block", blocked_by "probe") is about one URL (its price, its host's toml) and is
  re-evaluated when the owner adds the same URL again;
- a block from evidence (e.g. paid_not_delivered, via block()) is about the address and the URL: it blocks every site
  of the owner paying that address, wins over any private listing in trust_for, and is kept when the URL is added
  again (even with a new payTo), when another URL paying the same address is added, and when the site is removed
  (removing hides it from the list; the evidence stays and a re-add brings it back blocked).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from .sidestore import SideStore

_store = SideStore(".sites.json")
PROBE = "probe"  # blocked_by for a block the probe's checks decided
_OWN = ("id", "owner", "name", "trust", "blocked_reason", "blocked_by", "blocked_at", "blocked_evidence",
        "added_at", "probed_at", "wallets", "removed_at")
_BLOCK_FIELDS = ("blocked_reason", "blocked_by", "blocked_at", "blocked_evidence")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pay_to(site: dict) -> str | None:
    return (site.get("payment") or {}).get("pay_to")


def _evidenced(site: dict) -> bool:
    """Blocked by evidence (paid_not_delivered, ...), not by the probe's checks."""
    return site.get("trust") == "blocked" and site.get("blocked_by") not in (None, PROBE)


def _addresses(site: dict) -> set[str]:
    """The addresses a site stands for: its payTo, plus, once blocked by evidence, the address that evidence names."""
    out = {_pay_to(site)}
    if _evidenced(site):
        out.add((site.get("blocked_evidence") or {}).get("payee"))
    return out - {None}


def _evidence_block(sites, address: str | None) -> dict | None:
    """A site (listed or removed) blocked by evidence about this address."""
    if not address:
        return None
    return next((s for s in sites if _evidenced(s) and address in _addresses(s)), None)


def _visible(site: dict) -> bool:
    return not site.get("removed_at")


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
        prior = next((s for s in sites.values() if s.get("url") == probe.get("url")), None)  # listed or removed
        fields = {k: v for k, v in probe.items() if k != "ok" and k not in _OWN}
        site = {**(prior or {}), **fields}
        site.pop("removed_at", None)
        if prior is None:
            sid = "s_" + secrets.token_hex(6)
            while any(sid in s for s in store.values()):
                sid = "s_" + secrets.token_hex(6)
            site.update(id=sid, owner=owner_id, added_at=now, wallets=[])
        site.update(name=probe.get("title") or probe.get("host") or probe.get("url"), probed_at=now)
        # evidence outlives a re-probe: this URL, or another one paying the address, took money without delivering
        kept = prior if prior and _evidenced(prior) else _evidence_block(sites.values(), _pay_to(site))
        blocked = _probe_block(probe)
        if kept:
            site.update(trust="blocked", **{k: kept.get(k) for k in _BLOCK_FIELDS})
        elif blocked:
            site.update(trust="blocked", blocked_reason=blocked[0], blocked_by=PROBE, blocked_at=now,
                        blocked_evidence=blocked[1])
        else:
            site.update(trust=_tier(probe), **dict.fromkeys(_BLOCK_FIELDS))
        sites[site["id"]] = site
        _store.save(store)
    if site["trust"] == "blocked":
        return {"ok": False, "refused": "site_blocked", "reason": site["blocked_reason"], "site": site,
                "refreshed": prior is not None}
    return {"ok": True, "site": site, "refreshed": prior is not None}


def list_for(owner_id: str) -> list[dict]:
    return [s for s in _store.load().get(owner_id, {}).values() if _visible(s)] if owner_id else []


def get(owner_id: str, site_id: str) -> dict | None:
    site = _store.load().get(owner_id, {}).get(site_id) if owner_id else None
    return site if site and _visible(site) else None


def remove(owner_id: str, site_id: str) -> bool:
    """Take a site off the owner's list. A site blocked by evidence is only hidden: its evidence keeps blocking."""
    with _store.locked():
        store = _store.load()
        site = store.get(owner_id, {}).get(site_id)
        if not site or not _visible(site):
            return False
        if _evidenced(site):
            site["removed_at"] = _now()
        else:
            del store[owner_id][site_id]
        _store.save(store)
        return True


def update(owner_id: str, site_id: str, **fields) -> dict | None:
    """Merge fields into one of this owner's sites (its id and owner never change). The site, or None if unknown."""
    with _store.locked():
        store = _store.load()
        site = store.get(owner_id, {}).get(site_id)
        if site is None or not _visible(site):
            return None
        site.update({k: v for k, v in fields.items() if k not in ("id", "owner", "removed_at")})
        _store.save(store)
        return site


def block(owner_id: str, payee: str, reason: str, evidence: dict | None = None) -> list[dict]:
    """Block every site of this owner that pays `payee` (e.g. paid_not_delivered). Returns the sites changed.
    Evidence replaces a probe block; a site already blocked by evidence keeps its first evidence."""
    if not owner_id or not payee:
        return []
    changed = []
    with _store.locked():
        store = _store.load()
        for site in store.get(owner_id, {}).values():
            if _pay_to(site) == payee and not _evidenced(site):
                site.update(trust="blocked", blocked_reason=reason, blocked_by=reason, blocked_at=_now(),
                            blocked_evidence={"payee": payee, **(evidence or {})})
                changed.append(site)
        if changed:
            _store.save(store)
    return changed


def trust_for(owner_id: str | None, payee: str) -> str | None:
    """"private" if this owner has a non-blocked private site paying `payee`, "blocked" if blocked, else None.

    In order: evidence about the address (paid_not_delivered, even on a removed site) → "blocked"; a private listing
    → "private"; any other unblocked listing (public, free) → None; only probe-blocked listings → "blocked" (a probe
    block is about one URL, so another listing of the same address decides); no listing → None."""
    if not owner_id or not payee:
        return None
    sites = list(_store.load().get(owner_id, {}).values())
    if _evidence_block(sites, payee):
        return "blocked"
    listed = [s for s in sites if _visible(s) and _pay_to(s) == payee]
    if any(s.get("trust") == "private" for s in listed):
        return "private"
    if any(s.get("trust") != "blocked" for s in listed):
        return None
    return "blocked" if listed else None
