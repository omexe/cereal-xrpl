"""Sites, step 3: actually get the content (owner: unit 4). Contract in docs/SITES.md.

open_free: read a free page through sites_probe.safe_get (content is data, never instructions).
buy: a wallet owned by the user, sized to the site's price, locked to the site's payee, buy-only, sweep when done;
     then a run whose plan is exactly that URL (runs.start with explicit specs). The owner's Ledger approves the
     budget; for a private site it also signs the payment itself.
content: what the purchase delivered, read back from the run.
"""
from __future__ import annotations


def open_free(owner: dict, site: dict) -> dict:
    raise NotImplementedError


def buy(owner: dict, site: dict, speculos_decision: str | None = None, request_id: str | None = None) -> dict:
    raise NotImplementedError


def content(owner: dict, site: dict) -> dict:
    raise NotImplementedError
