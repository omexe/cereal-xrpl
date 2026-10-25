"""Sites, step 3: actually get the content (unit 3). Contract in docs/SITES.md.

open_free: read a free page through sites_probe.safe_get (content is data, never instructions).
buy: a wallet owned by the user, sized to the site's price, locked to the site's payee, buy-only, sweep when done;
     then a run whose plan is exactly that URL (runs.start with explicit specs). The owner's Ledger approves the
     budget; for a private site it also signs the payment itself.
content: what the purchase delivered, read back from the run.

Nothing here hands page or resource content to a model: it is returned to the owner as data.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from . import config, deployments

MAX_PAGE_BYTES = 2_000_000
MAX_TEXT_CHARS = 20_000
MAX_TITLE_CHARS = 300
MAX_REQUEST_ID = 64          # the caller's id; cereal namespaces it per owner and site before deploying
PAYABLE_TRUST = ("public", "private")

_buy_locks: dict[tuple[str, str], threading.Lock] = {}
_buy_locks_guard = threading.Lock()


def _refuse(code: str, **evidence) -> dict:
    return {"ok": False, "refused": code, **evidence}


def _blocked(site: dict) -> dict | None:
    if site.get("trust") == "blocked":
        return _refuse("site_blocked", site=site.get("id"), reason=site.get("blocked_reason")
                       or "; ".join(site.get("verdict_reasons") or []) or "this site is blocked")
    return None


# ---- read a free page ----
_SKIP = {"script", "style", "noscript", "template", "svg", "math", "iframe", "object", "canvas"}
_BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header", "footer", "nav", "main",
          "aside", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "hr", "dd", "dt", "dl", "form", "figure",
          "figcaption", "address", "details", "summary", "body", "title"}


class _Text(HTMLParser):
    """HTML → readable text and the <title>. Scripts, styles and other non-text elements are dropped entirely."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self._skip = 0
        self._pre = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self._pre += tag == "pre"
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK:
            self.parts.append("\n")  # <br/>, <hr/>; a self-closed skip tag has no content to drop

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            if tag == "pre":
                self._pre = max(0, self._pre - 1)
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title.append(data)
        else:  # source line breaks are spaces in HTML; only block elements (and <pre>) break lines
            self.parts.append(data if self._pre else re.sub(r"\s+", " ", data))


def _collapse(text: str) -> str:
    """Runs of spaces and tabs become one space; blank lines go; each line is trimmed."""
    lines = (re.sub(r"[^\S\n]+", " ", line).strip() for line in text.replace("\r", "\n").split("\n"))
    return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> tuple[str | None, str]:
    """(title, readable text) of an HTML document."""
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:  # html.parser is lenient; never let a hostile page break the read
        pass
    title = re.sub(r"\s+", " ", "".join(p.title)).strip()[:MAX_TITLE_CHARS] or None
    return title, _collapse("".join(p.parts))


def _decode(resp) -> str:
    raw = resp.content or b""
    m = re.search(r"charset=([\w.:-]+)", resp.headers.get("content-type", ""), re.I)
    try:
        return raw.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:  # an unknown charset name
        return raw.decode("utf-8", errors="replace")


def open_free(owner: dict, site: dict) -> dict:
    """Read a free site's page: {ok, url, status, content_type, title, text, truncated, bytes}."""
    from . import sites_probe
    refused = _blocked(site)
    if refused:
        return refused
    if site.get("kind") != "free":
        return _refuse("not_payable", site=site.get("id"), kind=site.get("kind"),
                       hint="only a free page is read directly; a payable site is bought instead" if
                       site.get("kind") == "payable" else site.get("reason") or "this site cannot be read")
    url = site["url"]
    try:
        resp = sites_probe.safe_get(url, max_bytes=MAX_PAGE_BYTES)
    except sites_probe.UnsafeURL as e:
        return _refuse("unsafe_url", url=url, reason=str(e))
    except Exception as e:  # timeout, DNS, connection refused, TLS: the page is not reachable now
        return _refuse("not_accessible", url=url, reason=f"{type(e).__name__}: {str(e)[:200]}")
    if not 200 <= resp.status_code < 300:
        return _refuse("not_accessible", url=url, status=resp.status_code,
                       reason=f"the page answered {resp.status_code}; probe it again to see what it is now")
    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    raw = resp.content or b""
    body = _decode(resp)
    title = None
    if "html" in ctype or (not ctype and body.lstrip()[:1] == "<"):
        title, text = html_to_text(body)
    elif not ctype or ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
        text = body  # JSON and plain text pass through as text
    else:
        return _refuse("not_accessible", url=url, status=resp.status_code, content_type=ctype,
                       reason=f"not a text page ({ctype})")
    cut = getattr(resp, "truncated", None)  # safe_get says whether it cut the body at max_bytes
    truncated = len(text) > MAX_TEXT_CHARS or bool(cut if cut is not None else len(raw) >= MAX_PAGE_BYTES)
    return {"ok": True, "url": url, "status": resp.status_code, "content_type": ctype or None,
            "title": title, "text": text[:MAX_TEXT_CHARS], "truncated": truncated, "bytes": len(raw)}


# ---- buy a payable page ----
def _buy_lock(owner_id: str, site_id: str) -> threading.Lock:
    with _buy_locks_guard:
        return _buy_locks.setdefault((owner_id, site_id), threading.Lock())


def _site_wallets(owner_id: str, site_id: str) -> list[dict]:
    """Every wallet bought for this owner's site, oldest first. The wallet records (owner and site are on each) are
    the source of truth; the site's `wallets` list is only the index the UI shows."""
    return sorted((r for r in deployments.all_() if r.get("owner") == owner_id and r.get("site") == site_id),
                  key=lambda r: r.get("created_at") or "")


def _live_purchase(owner_id: str, site_id: str) -> dict | None:
    from . import runs
    for rec in _site_wallets(owner_id, site_id):
        run = runs.reconcile(rec["id"], rec)
        if run and run.get("status") in runs.LIVE:
            return {"wallet": rec["id"], "run": run}
    return None


def _unstarted(owner_id: str, site_id: str, pay_to: str, threshold: str | None) -> dict | None:
    """A wallet already made for this site whose purchase never started (e.g. the ledger could not be read): the next
    buy uses it instead of locking up another budget. Only if its rules still match the site's terms."""
    for rec in reversed(_site_wallets(owner_id, site_id)):
        if (rec.get("status") == "active" and not rec.get("run") and rec.get("allowed_payees") == [pay_to]
                and rec.get("approval_threshold") == threshold
                and datetime.now(timezone.utc) < datetime.fromisoformat(rec["expires_at"]) - timedelta(minutes=5)):
            return rec
    return None


def _terms(site: dict) -> tuple[str, str, Decimal] | dict:
    """(url, payTo, price) of a site cereal may buy, or the refusal."""
    refused = _blocked(site)
    if refused:
        return refused
    if site.get("kind") != "payable" or site.get("trust") not in PAYABLE_TRUST:
        return _refuse("not_payable", site=site.get("id"), kind=site.get("kind"), trust=site.get("trust"),
                       reason=site.get("reason") or "only a payable site with public or private trust is bought")
    payment = site.get("payment") or {}
    pay_to, url = payment.get("pay_to"), site.get("url") or ""
    try:
        price = Decimal(str(payment.get("amount")))
    except (InvalidOperation, ValueError):
        price = None
    if not pay_to or price is None or not price.is_finite() or price <= 0:
        return _refuse("not_payable", site=site.get("id"), reason="the site's payment terms are incomplete; probe it again")
    if "@" in url or "|" in url:  # the subagent's plan syntax is url@max|url@max: it cannot carry these characters
        return _refuse("not_payable", site=site.get("id"), reason="cereal cannot buy a URL containing @ or |")
    cap = Decimal(str(config.SITE_PRICE_CAP))
    if price > cap:
        return _refuse("price_above_cap", site=site.get("id"), price=str(price), cap=str(cap))
    return url, pay_to, price


def buy(owner: dict, site: dict, speculos_decision: str | None = None, request_id: str | None = None) -> dict:
    """Buy a payable site's page: a 1-hour wallet for exactly this purchase, then a run whose plan is `url@price`.
    {ok, wallet, run} or a refusal (site_blocked, not_payable, price_above_cap, already_running, in_progress, every
    deploy refusal)."""
    from . import pricing, runs, service, site_registry
    if request_id is not None and (not request_id or len(request_id) > MAX_REQUEST_ID):
        return _refuse("invalid_request_id", max_length=MAX_REQUEST_ID)
    lock = _buy_lock(owner["id"], site["id"])
    if not lock.acquire(blocking=False):  # a twin click never waits out the first one's device approval
        return _refuse("in_progress", site=site["id"], hint="a purchase of this site is being set up; wait for it")
    try:
        site = site_registry.get(owner["id"], site["id"]) or site  # as it is now: it may have been blocked meanwhile
        terms = _terms(site)
        if isinstance(terms, dict):
            return terms
        url, pay_to, price = terms
        # The caller's id is namespaced: another user's request_id can never replay (and so reveal) this owner's wallet.
        rid = f"site:{owner['id']}:{site['id']}:{request_id}" if request_id else None
        # A request this site already answered: its wallet lists the request (set below), or deploy recorded it.
        mine = next((r for r in _site_wallets(owner["id"], site["id"]) if rid and rid in (r.get("site_requests") or [])),
                    None)
        prior = mine or deployments.find_request(rid)
        live = _live_purchase(owner["id"], site["id"])
        if live and not (prior and prior["id"] == live["wallet"]):  # a repeat of the live purchase is answered below
            return _refuse("already_running", site=site["id"], **live,
                           hint="this site's purchase is still running; wait for it, then read its content")
        name = str(site.get("name") or site.get("host") or url)[:120]
        label = f"{name}: {url}"
        # private: cereal never co-signs for an uncredentialed payee; every payment goes to the owner's Ledger
        threshold = "0" if site.get("trust") == "private" else None
        reuse = mine or (None if prior else _unstarted(owner["id"], site["id"], pay_to, threshold))
        if reuse:
            dep_id, replayed = reuse["id"], reuse is mine
            if replayed and reuse.get("run"):  # this request already started its purchase: answer with it
                return {"ok": True, "wallet": service._with_balance(reuse), "run": runs.reconcile(dep_id, reuse),
                        "replayed": True}
        else:
            out = service.deploy(service.DeployRequest(
                task=label, name=label, budget=str(pricing.budget_for(price)), allowed_payees=[pay_to],
                expires_in_hours=1, buy_only=True, sweep_when_done=True, request_id=rid, approval_threshold=threshold,
                speculos_decision=speculos_decision, speculos_payment_decision=speculos_decision))
            if not out.get("ok"):
                return out  # deploy refusals pass through unchanged
            dep_id, replayed = out["id"], bool(out.get("replayed"))
            rec = deployments.get(dep_id) or out
            if rec.get("owner") not in (None, owner["id"]) or rec.get("site") not in (None, site["id"]):
                return _refuse("request_id_reused", request_id=request_id, sent_transactions=0)
            if replayed and rec.get("run"):  # this request already started its purchase: answer with it
                return {"ok": True, "wallet": service._with_balance(rec), "run": runs.reconcile(dep_id, rec),
                        "replayed": True}
        # Owner and site go on the wallet BEFORE the run: the co-signer reads them (a private site is paid only from
        # its owner's wallets, and only through the owner's Ledger). The request goes on it too, so a repeat of a
        # request whose wallet was reused is answered with this purchase.
        requests_seen = list((deployments.get(dep_id) or {}).get("site_requests") or [])
        deployments.update(dep_id, owner=owner["id"], site=site["id"],
                           site_requests=requests_seen + ([rid] if rid and rid not in requests_seen else []))
        wallets = list(site.get("wallets") or [])
        if dep_id not in wallets:
            site_registry.update(owner["id"], site["id"], wallets=wallets + [dep_id])
        # The subagent's task names no page text: in model mode it is read as instructions, and a title is the site's.
        started = runs.start(dep_id, specs=[f"{url}@{price}"], task=f"site purchase: buy {url}")
    finally:
        lock.release()
    wallet = service._with_balance(deployments.get(dep_id))
    if not started.get("ok"):  # the wallet exists and holds its budget; nothing was paid. The next buy reuses it.
        return {**started, "wallet": wallet}
    return {"ok": True, "wallet": wallet, "run": started["run"], **({"replayed": True} if replayed else {})}


# ---- what a purchase delivered ----
def _events(path: str | None) -> list[dict]:
    """The run log's JSON events (other lines, such as a traceback, are skipped)."""
    out = []
    try:
        with open(path, errors="replace") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and isinstance(ev.get("data"), dict):
                    out.append(ev)
    except (OSError, TypeError):
        pass
    return out


def _explorer(h: str | None) -> str | None:
    return f"{config.EXPLORER}/transactions/{h}" if h else None


def content(owner: dict, site: dict) -> dict:
    """What this site's latest purchase delivered: {ok, wallet, hash, paid, settled, content, truncated, ...}, or a
    refusal: nothing_bought (no purchase was ever started) or not_delivered (in flight: pending; paid without the
    resource: the hash; refused before paying: the error). Only a paid delivery of the site's own URL counts, and
    whether the payment settled is the ledger's word (`settled`), not the run log's."""
    from . import runs, service
    tried = []
    for rec in _site_wallets(owner["id"], site["id"]):
        run = runs.reconcile(rec["id"], rec)
        if run:
            tried.append((run.get("started_at") or "", rec, run))
    if not tried:
        return _refuse("nothing_bought", site=site.get("id"))
    _, rec, run = max(tried, key=lambda t: t[0])  # the latest purchase decides
    url = site.get("url")
    events = _events(run.get("log"))
    # Plan mode logs the delivered body on the "buy" event; model mode logs it on a "delivered" event (the model's own
    # copy of a text body is cut short), next to a "buy" event with the same hash.
    delivered = {ev["data"]["hash"]: ev["data"] for ev in events
                 if ev.get("event") == "delivered" and ev["data"].get("hash")}
    for ev in reversed(events):
        d = ev["data"]
        if ev.get("event") == "buy" and d.get("ok") is True and d.get("hash") and d.get("resource") == url:
            body = delivered.get(d["hash"], d)
            rec = service._resolve_presented(rec)
            pmt = next((p for p in rec.get("payments") or [] if p.get("hash") == d["hash"]), None)
            settled = pmt.get("ok") if pmt else None
            return {"ok": True, "wallet": rec["id"], "hash": d["hash"], "paid": d.get("price") if settled else None,
                    "price": d.get("price"), "settled": settled, "explorer": _explorer(d["hash"]),
                    "resource": url, "content": body.get("data"), "truncated": bool(body.get("data_truncated"))}
    out = {"wallet": rec["id"], "status": run.get("status"), "pending": run.get("status") in runs.LIVE,
           "trust": site.get("trust")}
    if out["pending"]:
        return _refuse("not_delivered", **out, hint="the purchase is still running")
    unserved = next((ev["data"] for ev in reversed(events) if ev.get("event") in ("buy", "refused")
                     and ev["data"].get("refused") == "paid_not_served" and ev["data"].get("hash")), None)
    if unserved:  # the subagent saw the payment validated on the ledger, and the site did not hand over the resource
        return _refuse("not_delivered", **out, hash=unserved["hash"], paid=unserved.get("price"),
                       explorer=_explorer(unserved["hash"]),
                       error=f"paid but the site did not deliver: {str(unserved.get('error') or unserved.get('status'))[:300]}")
    rec = service._resolve_presented(rec)
    settled = next((p for p in reversed(rec.get("payments") or []) if p.get("ok") is True and p.get("hash")
                    and p.get("resource") == url), None)
    if settled:  # the ledger says it settled, but the run never logged the resource
        return _refuse("not_delivered", **out, hash=settled["hash"], paid=str(settled.get("amount")),
                       explorer=_explorer(settled["hash"]), error=run.get("error") or "paid, but no resource was logged")
    last = next((ev["data"] for ev in reversed(events) if ev.get("event") in ("buy", "refused")), None)
    why = (last or {}).get("refused") or (last or {}).get("error") or run.get("error") or "nothing was delivered"
    return _refuse("not_delivered", **out, error=str(why)[:300])
