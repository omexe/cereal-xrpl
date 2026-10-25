"""Sites, step 1: look at a URL before any money moves (owner: unit 1). Contract in docs/SITES.md.

probe(url) answers what the site is and whether cereal could pay it, from the site itself and the ledger, and never
pays. safe_get() is the only way cereal code fetches a user-given URL: http(s) only, no private addresses unless the
origin is in config.SITE_ALLOW_ORIGINS, bounded size and time, redirects re-checked hop by hop.
"""
from __future__ import annotations


class UnsafeURL(Exception):
    """The URL is not one cereal will fetch (scheme, private address, too many redirects). str() is the plain reason."""


def safe_get(url: str, *, headers: dict | None = None, max_bytes: int = 2_000_000, timeout: float = 20.0):
    """GET a user-given URL safely. Returns a requests.Response whose .content is at most max_bytes.
    Raises UnsafeURL for URLs cereal must not fetch."""
    raise NotImplementedError


def probe(url: str) -> dict:
    """What a site is and whether cereal could pay it. Never pays, never signs.

    Returns {ok: True, url, origin, host, kind, status, title, payment, accepts, reason, credential, checks, verdict,
    verdict_reasons, trust_hint} as specified in docs/SITES.md, or a refusal {ok: False, refused: invalid_url |
    unsafe_url, reason}."""
    raise NotImplementedError
