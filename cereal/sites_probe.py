"""Sites, step 1: look at a URL before any money moves (owner: unit 1). Contract in docs/SITES.md.

probe(url) answers what the site is and whether cereal could pay it, from the site itself and the ledger, and never
pays. safe_get() is the only way cereal code fetches a user-given URL: http(s) only, no private addresses unless the
origin is in config.SITE_ALLOW_ORIGINS, bounded size and time, redirects re-checked hop by hop.

Known limit of the SSRF guard: the host is resolved and checked, then requests resolves it again to connect. A DNS
server that answers a public address to the check and a private one to the connect (DNS rebinding) wins that race.
Acceptable for the hackathon; the fix is to connect to the checked IP and pin Host/SNI to the name.

Everything a site sends (402 bodies, titles, its xrp-ledger.toml) is untrusted data: parsed, truncated, never obeyed.
"""
from __future__ import annotations

import base64
import html
import ipaddress
import json
import re
import socket
import time
import tomllib
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urldefrag, urljoin, urlsplit

import requests
from xrpl.core.addresscodec import is_valid_classic_address
from xrpl.models.requests import AccountInfo, AccountLines, AccountTx
from xrpl.utils import ripple_time_to_datetime

from . import config, vendors
from .ledger import client
from .pay import pick_rlusd_requirement

USER_AGENT = "cereal-sites/1"
MAX_REDIRECTS = 3
PROBE_MAX_BYTES = 512_000      # enough for a 402 body or a page's <head>
PROBE_TIMEOUT = 15.0
TOML_MAX_BYTES = 64_000
TOML_TIMEOUT = 8.0
NEW_ACCOUNT_SECONDS = 24 * 3600
MAX_URL_LENGTH = 2048          # what a user may type
MAX_WIRE_URL_LENGTH = 16_384   # what safe_get accepts (percent-encoding can multiply a URL's length by 6)
# headers that must not follow a redirect to another origin
_CREDENTIAL_HEADERS = ("authorization", "proxy-authorization", "cookie", "payment-signature", "x-payment")


class UnsafeURL(Exception):
    """The URL is not one cereal will fetch (scheme, private address, too many redirects). str() is the plain reason."""


class RedirectProblem(UnsafeURL):
    """The site's own redirects are broken (a loop, too many hops, an unreadable Location): probe says unreachable."""


class _Malformed(ValueError):
    """Not a URL cereal can read at all (probe answers invalid_url)."""


class _LedgerError(Exception):
    """A ledger read that failed (the check becomes ok: null)."""


# ---- URL parsing and the SSRF guard ----------------------------------------------------------------------------

def _origin(scheme: str, host: str, port: int, *, display: bool = False) -> str:
    h = f"[{host}]" if ":" in host else host
    if display and (scheme, port) in (("http", 80), ("https", 443)):
        return f"{scheme}://{h}"
    return f"{scheme}://{h}:{port}"


def _parse(url: str, max_len: int = MAX_URL_LENGTH) -> tuple[str, str, int]:
    """(scheme, host, port) of an absolute URL. _Malformed if it is not a URL; UnsafeURL if cereal won't open it."""
    if not isinstance(url, str) or not url:
        raise _Malformed("Give a web address, like https://example.com.")
    if len(url) > max_len:
        raise _Malformed(f"That address is longer than {max_len} characters.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise _Malformed("A web address cannot contain spaces or control characters.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise _Malformed("That address has a port or host cereal cannot read.") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeURL(f"cereal only opens http:// and https:// addresses, not {scheme or 'this kind of'}: addresses.")
    host = parts.hostname or ""
    if not host:
        raise _Malformed("That address has no host name.")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURL("cereal does not open addresses with a user name or password in them.")
    return scheme, host, port or (443 if scheme == "https" else 80)


def _allowed_origins() -> set[str]:
    out = set()
    for o in config.SITE_ALLOW_ORIGINS:
        try:
            out.add(_origin(*_parse(o)))
        except (UnsafeURL, _Malformed):
            continue
    return out


def _ip_problem(ip_text: str) -> str | None:
    """Why this address is not public, or None if it is."""
    ip = ipaddress.ip_address(ip_text.split("%", 1)[0])  # drop an IPv6 zone id
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_unspecified:
        return "an unspecified"
    if ip.is_loopback:
        return "a loopback"
    if ip.is_link_local:
        return "a link-local (cloud metadata)"
    if ip.is_multicast:
        return "a multicast"
    if ip.is_private:
        return "a private"
    if ip.is_reserved:
        return "a reserved"
    if not ip.is_global:
        return "a non-public"
    return None


def _wire_host(host: str) -> str:
    """The ASCII name requests will connect to. Resolving anything else (e.g. getaddrinfo's own IDNA 2003 encoding of
    a Unicode host) would check one name and connect to another."""
    if host.isascii():
        return host
    try:
        return requests.models.PreparedRequest._get_idna_encoded_host(host)
    except (UnicodeError, ValueError):
        raise _Malformed(f"{host} is not a valid internationalized host name.") from None


def _check_target(url: str, *, redirect: bool = False) -> str:
    """Raise UnsafeURL unless cereal may fetch this URL; returns its normalized origin (scheme://host:port)."""
    try:
        # a URL requests percent-encoded (a stored probe URL, a redirect) can be far longer than what a user types
        scheme, host, port = _parse(url, max_len=MAX_WIRE_URL_LENGTH)
        host = _wire_host(host)
    except _Malformed as e:
        raise (RedirectProblem(f"The site redirected to an address cereal cannot read: {e}") if redirect
               else UnsafeURL(str(e))) from None
    origin = _origin(scheme, host, port)
    if origin in _allowed_origins():
        return origin  # a local test merchant (config.SITE_ALLOW_ORIGINS)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise requests.exceptions.ConnectionError(f"Could not find {host}: the DNS lookup failed.") from None
    if not infos:
        raise requests.exceptions.ConnectionError(f"Could not find {host}: the DNS lookup returned nothing.")
    for info in infos:
        ip = str(info[4][0])
        problem = _ip_problem(ip)
        if problem:
            what = f"{host} is" if ip == host else f"{host} resolves to {ip},"
            raise UnsafeURL(f"{what} {problem} address; cereal only opens public addresses.")
    return origin


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # no proxies from the environment, and never send ~/.netrc credentials to a user-given host
    return s


def _read_body(resp: requests.Response, max_bytes: int, deadline: float) -> None:
    buf = bytearray()
    truncated = False
    try:
        for chunk in resp.iter_content(chunk_size=16_384):
            if time.monotonic() > deadline:
                raise requests.exceptions.Timeout("The site took too long to send its page.")
            if not chunk:
                continue
            room = max_bytes - len(buf)
            if len(chunk) > room:
                buf += chunk[:room]
                truncated = True
                break
            buf += chunk
    finally:
        resp.close()
    resp._content = bytes(buf)
    resp._content_consumed = True
    resp.truncated = truncated


def safe_get(url: str, *, headers: dict | None = None, max_bytes: int = 2_000_000, timeout: float = 20.0):
    """GET a user-given URL safely. Returns a requests.Response whose .content is at most max_bytes.
    Raises UnsafeURL for URLs cereal must not fetch.

    Every hop (the URL and up to 3 redirects) must be http(s) and resolve only to public addresses, unless its
    origin is in config.SITE_ALLOW_ORIGINS. `timeout` bounds the whole call, not each socket read. The response
    also carries `.truncated` (the body was cut at max_bytes) and `.history` (the redirect responses, bodies unread).
    Network failures raise requests exceptions (ConnectionError, Timeout, ...), as requests.get would.
    """
    deadline = time.monotonic() + timeout
    sent = {k: v for k, v in (headers or {}).items() if k.lower() != "user-agent"}
    sent["User-Agent"] = USER_AGENT
    history: list[requests.Response] = []
    session = _session()
    try:
        current = url
        origin = _check_target(current)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests.exceptions.Timeout(f"The site did not answer within {timeout:g} seconds.")
            resp = session.get(current, headers=sent, allow_redirects=False, stream=True,
                               timeout=(remaining, remaining))
            target = session.get_redirect_target(resp) if resp.is_redirect else None
            if not target:
                _read_body(resp, max_bytes, deadline)
                resp.history = history
                return resp
            resp.close()
            history.append(resp)
            if len(history) > MAX_REDIRECTS:
                raise RedirectProblem(f"The site redirected more than {MAX_REDIRECTS} times.")
            try:
                current = urldefrag(urljoin(resp.url, target))[0]
            except ValueError:
                raise RedirectProblem("The site redirected to an address cereal cannot read.") from None
            next_origin = _check_target(current, redirect=True)
            if next_origin != origin:  # credentials meant for one site never follow a redirect to another
                sent = {k: v for k, v in sent.items() if k.lower() not in _CREDENTIAL_HEADERS}
            origin = next_origin
    finally:
        session.close()


# ---- reading what the site answered ---------------------------------------------------------------------------

def _clean(text, limit: int = 200) -> str | None:
    """Untrusted text from a site, made safe to show: one line, no control characters, bounded."""
    if text is None:
        return None
    s = re.sub(r"\s+", " ", "".join(ch for ch in str(text) if ch.isprintable() or ch.isspace())).strip()
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return s or None


def _text(resp: requests.Response) -> str:
    m = re.search(r"charset=([\w.:-]+)", resp.headers.get("content-type", ""), re.I)
    try:
        return resp.content.decode(m.group(1) if m else "utf-8", errors="replace")
    except LookupError:
        return resp.content.decode("utf-8", errors="replace")


def _title(resp: requests.Response) -> str | None:
    ctype = resp.headers.get("content-type", "").lower()
    head = _text(resp)[:200_000]
    if "html" not in ctype and not head.lstrip()[:1] == "<":
        return None
    # two bounded searches, not one lazy regex: a page of unclosed <title> tags must not cost quadratic time
    m = re.search(r"<title\b[^>]{0,200}>", head, re.I)
    if not m:
        return None
    end = re.search(r"</title\s*>", head[m.end(): m.end() + 4000], re.I)
    return _clean(html.unescape(head[m.end(): m.end() + end.start()])) if end else None


def _amount(v) -> str:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return _clean(v, 40) or ""
    if not d.is_finite() or not -40 <= d.adjusted() <= 40:  # '1e999999' would print a million digits
        return _clean(v, 40) or ""
    return "0" if d == 0 else format(d.normalize(), "f")


_NETWORKS = {
    "xrpl:0": "XRPL mainnet", "xrpl:1": "XRPL testnet", "xrpl:2": "XRPL devnet",
    "eip155:1": "Ethereum", "eip155:11155111": "Ethereum Sepolia", "eip155:8453": "Base", "eip155:84532": "Base Sepolia",
    "eip155:137": "Polygon", "eip155:80002": "Polygon Amoy", "eip155:43114": "Avalanche", "eip155:43113": "Avalanche Fuji",
    "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp": "Solana", "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1": "Solana devnet",
    "base": "Base", "base-sepolia": "Base Sepolia", "ethereum": "Ethereum", "sepolia": "Ethereum Sepolia",
    "polygon": "Polygon", "polygon-amoy": "Polygon Amoy", "avalanche": "Avalanche", "avalanche-fuji": "Avalanche Fuji",
    "solana": "Solana", "solana-devnet": "Solana devnet",
}
_KNOWN_TOKENS = {"0x036cbd53842c5426634e7929541ec2318f3dcf7e": "USDC", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
                 "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC", "0x1c7d4b196cb0c7b01d743fbc6116a902379c7238": "USDC"}


def _currency_name(asset: str) -> str:
    a = asset.strip()
    if re.fullmatch(r"[0-9A-Fa-f]{40}", a):
        raw = bytes.fromhex(a).strip(b"\0")
        try:
            name = raw.decode("ascii")
            if name and name.isprintable():
                return name
        except UnicodeDecodeError:
            pass
        return f"{a[:8]}…"
    return _clean(a, 24) or "an unnamed asset"


def _asset_name(opt: dict) -> str:
    extra = opt.get("extra") if isinstance(opt.get("extra"), dict) else {}
    asset = str(opt.get("asset") or opt.get("currency") or "")
    network = str(opt.get("network") or "")
    if network.startswith("xrpl"):
        if not asset or asset.upper() == "XRP":
            return "XRP"
        name = _currency_name(asset)
        issuer = extra.get("issuer") or opt.get("issuer")
        if issuer and issuer != config.RLUSD_ISSUER:
            return f"{name} (issuer {_clean(issuer, 40)})"
        return name
    if asset.lower() in _KNOWN_TOKENS:
        return _KNOWN_TOKENS[asset.lower()]
    if isinstance(extra.get("name"), str) and extra["name"].strip():
        return _clean(extra["name"], 24)
    if len(asset) > 14:
        return f"{asset[:6]}…{asset[-4:]}"
    return _clean(asset, 24) or "an unnamed asset"


def _label(opt: dict) -> str:
    network = _clean(opt.get("network"), 60) or "an unnamed network"
    name = _NETWORKS.get(network)
    return f"{_asset_name(opt)} on {name} ({network})" if name else f"{_asset_name(opt)} on {network}"


def _normalize_option(opt: dict) -> dict:
    """x402 v1 options name the price maxAmountRequired; v2 names it amount."""
    if "amount" not in opt and "maxAmountRequired" in opt:
        opt = {**opt, "amount": opt["maxAmountRequired"]}
    return opt


def _decode_header(value: str | None) -> dict | None:
    if not value:
        return None
    for decode in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            raw = value.strip()
            data = json.loads(decode(raw + "=" * (-len(raw) % 4)))
        except (ValueError, TypeError, RecursionError):  # RecursionError: hostile, deeply nested JSON
            continue
        if isinstance(data, dict):
            return data
    return None


def _payment_required(resp: requests.Response) -> dict | None:
    """The 402's x402 document: v2 PAYMENT-REQUIRED header (base64 JSON) first, else the JSON body (v1 or v2)."""
    candidates = [_decode_header(resp.headers.get("PAYMENT-REQUIRED"))]
    try:
        body = json.loads(_text(resp))
        candidates.append(body if isinstance(body, dict) else None)
    except (ValueError, RecursionError):
        pass
    for doc in candidates:
        if doc and isinstance(doc.get("accepts"), list) and doc["accepts"]:
            return doc
    return next((d for d in candidates if d), None)


def _why_not_rlusd(opt: dict) -> str | None:
    """For an RLUSD-on-xrpl:1 option cereal still can't pay, why (None for options that are something else)."""
    if str(opt.get("network")) != "xrpl:1" or str(opt.get("asset", "")).upper() != config.RLUSD_CURRENCY:
        return None
    extra = opt.get("extra") if isinstance(opt.get("extra"), dict) else {}
    if extra.get("issuer") != config.RLUSD_ISSUER:
        return f"its RLUSD option names issuer {_clean(extra.get('issuer'), 40) or '(none)'}, not RLUSD's issuer {config.RLUSD_ISSUER}"
    if opt.get("scheme") != "exact":
        return f"its RLUSD option uses the {_clean(opt.get('scheme'), 20) or 'unnamed'} scheme; cereal pays exact prices only"
    if not extra.get("invoiceId"):
        return "its RLUSD option has no invoiceId, which cereal needs to bind the payment to this purchase"
    return "its RLUSD option is incomplete (price, payee or timeout missing)"


# Bot walls: services sites use to keep automated visitors out. cereal names them so the owner knows why, and never
# tries to get past one (a bot check is the site saying "no agents").
_WALL_BODIES = [
    ("Cloudflare", re.compile(r"challenge-platform|cf-turnstile|cf_chl_|<title>Just a moment\.\.\.</title>", re.I)),
    ("DataDome", re.compile(r"captcha-delivery\.com|datadome", re.I)),
    ("HUMAN (PerimeterX)", re.compile(r"px-captcha|perimeterx|_pxhd", re.I)),
    ("Imperva", re.compile(r"_Incapsula_Resource|incapsula incident", re.I)),
    ("Akamai", re.compile(r"Reference&#32;&#35;|akamai", re.I)),
]


def bot_wall(resp: requests.Response) -> str | None:
    """The bot-protection service that answered instead of the site ("Cloudflare", "DataDome", ...), "a captcha" for an
    unnamed one, or None when the answer is the site itself."""
    h = resp.headers
    if h.get("cf-mitigated", "").lower() == "challenge":
        return "Cloudflare"
    if h.get("x-datadome") or h.get("x-dd-b"):
        return "DataDome"
    if resp.status_code < 400:
        return None
    if "akamaighost" in h.get("server", "").lower() and resp.status_code == 403:
        return "Akamai"
    body = _text(resp)[:64_000]
    for name, pattern in _WALL_BODIES:
        if pattern.search(body):
            return name
    if re.search(r"captcha", body, re.I):
        return "a captcha"
    return None


def _unreachable_reason(resp: requests.Response) -> str:
    code = resp.status_code
    wall = bot_wall(resp)
    if wall:
        host = urlsplit(resp.url or "").hostname or "This site"
        what = "a captcha" if wall == "a captcha" else f"{wall}'s bot check"
        return (f"{host} blocks automated agents with {what} (a captcha only a person in a browser can pass). "
                "cereal does not try to get around it.")
    if code == 401:
        return "The site answered 401: it needs a login."
    if code == 403:
        return "The site answered 403: it refused the request (usually a login wall or a bot block)."
    if code == 404:
        return "The site answered 404: there is no page at this address."
    if code == 429:
        return "The site answered 429: it is rate-limiting requests."
    if code >= 500:
        return f"The site answered {code}: a server error."
    if 300 <= code < 400:
        return f"The site answered {code}, a redirect with no usable destination."
    return f"The site answered {code}, which is not a page or a paywall."


def _failure_reason(e: requests.RequestException, timeout: float) -> str:
    if isinstance(e, requests.exceptions.Timeout) or "timed out" in str(e).lower():
        return f"The site did not answer within {timeout:g} seconds."
    if isinstance(e, requests.exceptions.SSLError):
        return "The site's TLS certificate could not be verified."
    msg = str(e)
    if msg.startswith("Could not find "):
        return msg
    if isinstance(e, requests.exceptions.ConnectionError):
        return "Could not connect to the site."
    return f"The request failed ({type(e).__name__})."


# ---- ledger reads (any failure → ok: null, never a crash) -----------------------------------------------------

def _ledger_problem(e: Exception) -> str:
    # The exception's class only: an RPC error message can contain the provider URL, and with it an API key.
    return f"Could not read the ledger ({type(e).__name__}), so cereal cannot tell."


def _account(c, addr: str) -> dict | None:
    """The account's AccountRoot, or None if it does not exist on testnet."""
    res = c.request(AccountInfo(account=addr, ledger_index="validated"))
    if res.is_successful():
        return res.result["account_data"]
    if res.result.get("error") == "actNotFound":
        return None
    raise _LedgerError(str(res.result.get("error") or "error"))


def _rlusd_line(c, addr: str) -> dict | None:
    res = c.request(AccountLines(account=addr, peer=config.RLUSD_ISSUER, ledger_index="validated"))
    if not res.is_successful():
        raise _LedgerError(str(res.result.get("error") or "error"))
    for line in res.result.get("lines") or []:
        if line.get("currency") in (config.RLUSD_CURRENCY, "RLUSD") and line.get("account") == config.RLUSD_ISSUER:
            return line
    return None


def _first_seen(c, addr: str) -> datetime | None:
    """When the account's earliest transaction this server knows of closed (its creation, for a new account)."""
    res = c.request(AccountTx(account=addr, forward=True, limit=1))
    if not res.is_successful():
        raise _LedgerError(str(res.result.get("error") or "error"))
    txs = res.result.get("transactions") or []
    if not txs:
        return None
    t = txs[0]
    if t.get("close_time_iso"):
        return datetime.fromisoformat(str(t["close_time_iso"]).replace("Z", "+00:00"))
    date = (t.get("tx_json") or t.get("tx") or {}).get("date")
    if date is None:
        raise _LedgerError("no close time")
    return ripple_time_to_datetime(int(date))


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return "just now"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} minutes ago"
    if seconds < 48 * 3600:
        n = round(seconds / 3600)
        return f"{n} hour{'s' if n != 1 else ''} ago"
    return f"{round(seconds / 86400)} days ago"


def _norm_host(h: str) -> str:
    h = h.strip().lower()
    if "://" in h:
        h = urlsplit(h).hostname or ""
    h = h.split("/", 1)[0].rstrip(".")
    return h[4:] if h.startswith("www.") else h


def _toml_accounts(origin: str) -> tuple[str, list[str]]:
    """('found', addresses) | ('empty', []) | ('missing' | 'unreachable' | 'invalid', [])."""
    try:
        r = safe_get(f"{origin}/.well-known/xrp-ledger.toml", max_bytes=TOML_MAX_BYTES, timeout=TOML_TIMEOUT)
    except Exception:  # noqa: BLE001 — unsafe, unreachable or broken: either way there is no proof to read
        return "unreachable", []
    if not 200 <= r.status_code < 300:
        return "missing", []
    try:
        doc = tomllib.loads(r.content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, RecursionError):
        return "invalid", []
    accounts = doc.get("ACCOUNTS")
    addrs = [a["address"].strip() for a in accounts if isinstance(a, dict) and isinstance(a.get("address"), str)] \
        if isinstance(accounts, list) else []
    return ("found", addrs) if addrs else ("empty", [])


def _check(name: str, ok: bool | None, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def _domain_check(origin: str, host: str, pay_to: str, account: dict | None, account_known: bool,
                  toml: tuple[str, list[str]]) -> dict:
    state, listed = toml
    toml_url = f"{origin}/.well-known/xrp-ledger.toml"
    domain = None
    if account_known and account and account.get("Domain"):
        try:
            domain = _clean(bytes.fromhex(account["Domain"]).decode("utf-8", errors="replace"), 120)
        except ValueError:
            domain = None
    if state == "found" and pay_to not in listed:
        shown = ", ".join(_clean(a, 40) for a in listed[:3]) + (" …" if len(listed) > 3 else "")
        return _check("domain_proof", False, f"This site's xrp-ledger.toml lists {shown} but not {pay_to}, the address it "
                                             f"asks you to pay: the payment would go to someone the site does not claim.")
    if domain and _norm_host(domain) != _norm_host(host):
        return _check("domain_proof", False, f"The address {pay_to} says it belongs to {domain}, not {host}.")
    if not account_known:
        return _check("domain_proof", None, "Could not read the address's Domain field from the ledger, so cereal cannot "
                                            "confirm it belongs to this site.")
    if state == "found":
        if domain:
            return _check("domain_proof", True, f"{toml_url} lists {pay_to}, and the address's Domain is {domain}.")
        return _check("domain_proof", None, f"{toml_url} lists {pay_to}, but the address names no domain, so only the "
                                            f"site vouches for the link.")
    why = {"missing": "There is no xrp-ledger.toml", "unreachable": "Could not fetch xrp-ledger.toml",
           "invalid": "The xrp-ledger.toml is not valid TOML", "empty": "The xrp-ledger.toml lists no accounts"}[state]
    if domain:
        return _check("domain_proof", None, f"{why} at {origin}; the address names {domain} as its domain, but the site "
                                            f"does not confirm it.")
    return _check("domain_proof", None, f"{why} at {origin}, and the address names no domain: cereal cannot link "
                                        f"{pay_to} to this site.")


def _checks(payment: dict, origin: str, host: str) -> tuple[list[dict], str | None]:
    """The automatic checks of docs/SITES.md, in order, and the payee's credential status."""
    with ThreadPoolExecutor(max_workers=1) as pool:  # the site's toml downloads while the ledger is read
        toml = pool.submit(_toml_accounts, origin)
        return _run_checks(payment, origin, host, toml)


def _run_checks(payment: dict, origin: str, host: str, toml: Future) -> tuple[list[dict], str | None]:
    pay_to, amount = payment["pay_to"], payment["amount"]
    out = [_check("asset", True, f"RLUSD from issuer {payment['issuer']} on {payment['network']}, exact scheme.")]

    cap = Decimal(str(config.SITE_PRICE_CAP))
    try:
        price = Decimal(amount)
    except (InvalidOperation, ValueError):
        price = None
    if price is None or not price.is_finite() or price <= 0:
        out.append(_check("price", False, f"The price ({amount or 'none'}) is not a positive amount."))
    elif price > cap:
        out.append(_check("price", False, f"The price, {amount} RLUSD, is above the {_amount(cap)} RLUSD cap for one "
                                          f"site purchase."))
    else:
        out.append(_check("price", True, f"{amount} RLUSD (cap {_amount(cap)})"))

    try:
        c = client()
    except Exception as e:  # noqa: BLE001 — a client that cannot even be built is still "could not tell"
        c, client_error = None, e
    else:
        client_error = None

    valid_address = is_valid_classic_address(pay_to)
    account, account_known = None, False
    if not valid_address:
        out.append(_check("payee_exists", False, f"The payee, {pay_to}, is not a valid XRPL address."))
    else:
        try:
            if c is None:
                raise client_error
            account, account_known = _account(c, pay_to), True
        except Exception as e:  # noqa: BLE001
            out.append(_check("payee_exists", None, _ledger_problem(e)))
        else:
            out.append(_check("payee_exists", True, f"{pay_to} exists on XRPL testnet.") if account else
                       _check("payee_exists", False, f"The address it asks you to pay, {pay_to}, does not exist on "
                                                     f"XRPL testnet."))
    if not valid_address or (account_known and account is None):
        out.append(_check("payee_rlusd", False, f"{pay_to} has no account, so it has no RLUSD trust line and cannot be paid."))
    elif not account_known:
        out.append(_check("payee_rlusd", None, "Could not read the payee's account, so cereal cannot tell if it takes RLUSD."))
    else:
        try:
            line = _rlusd_line(c, pay_to)
        except Exception as e:  # noqa: BLE001
            out.append(_check("payee_rlusd", None, _ledger_problem(e)))
        else:
            if line is None:
                out.append(_check("payee_rlusd", False, f"{pay_to} has no RLUSD trust line, so it cannot be paid in RLUSD."))
            elif line.get("freeze_peer"):
                out.append(_check("payee_rlusd", False, f"The RLUSD issuer froze {pay_to}'s trust line, so it cannot be paid."))
            else:
                try:
                    room = Decimal(str(line.get("limit", "0"))) - Decimal(str(line.get("balance", "0")))
                except (InvalidOperation, ValueError):
                    room = None
                if room is not None and price is not None and price.is_finite() and room < price:
                    out.append(_check("payee_rlusd", False, f"{pay_to}'s RLUSD trust line is full (limit "
                                                            f"{line.get('limit')}), so it cannot receive {amount} RLUSD."))
                else:
                    out.append(_check("payee_rlusd", True, f"{pay_to} has an RLUSD trust line to {config.RLUSD_ISSUER}."))

    # an invalid address certainly has no account (known: none), so only the site's toml can still speak
    out.append(_domain_check(origin, host, pay_to, account, account_known or not valid_address, toml.result()))

    if not valid_address or (account_known and account is None):
        out.append(_check("payee_history", False, f"{pay_to} has no history: the account does not exist."))
    elif not account_known:
        out.append(_check("payee_history", None, "Could not read the payee's account, so cereal cannot tell its age."))
    else:
        try:
            first = _first_seen(c, pay_to)
        except Exception as e:  # noqa: BLE001
            out.append(_check("payee_history", None, _ledger_problem(e)))
        else:
            if first is None:
                out.append(_check("payee_history", False, f"{pay_to} has no transactions on record."))
            else:
                age = (datetime.now(timezone.utc) - first).total_seconds()
                when = f"{first:%Y-%m-%d %H:%M} UTC"
                if age < NEW_ACCOUNT_SECONDS:
                    out.append(_check("payee_history", False, f"The address is new: created {_ago(age)} ({when})."))
                else:
                    out.append(_check("payee_history", True, f"On the ledger since {when} ({_ago(age)})."))

    cred_status = None
    try:
        if c is None:
            raise client_error
        cred = vendors.check(c, pay_to) if valid_address else {"status": "none"}
        cred_status = str(cred.get("status") or "none")
    except Exception as e:  # noqa: BLE001
        out.append(_check("credential", None, _ledger_problem(e)))
    else:
        if cred_status == "valid":
            out.append(_check("credential", True, f"{pay_to} holds a valid cereal vendor credential: a public site."))
        elif cred_status == "revoked":
            rev = cred.get("revocation") or {}
            why = f" (reason: {_clean(rev['reason'], 80)})" if rev.get("reason") else ""
            tx = f"; revocation tx {rev['hash']}" if rev.get("hash") else ""
            out.append(_check("credential", False, f"cereal revoked this payee's vendor credential{why}{tx}."))
        elif cred_status == "pending":
            out.append(_check("credential", False, "cereal issued a vendor credential the payee has not accepted: "
                                                   "private only."))
        elif cred_status == "expired":
            out.append(_check("credential", False, "The payee's cereal vendor credential expired: private only."))
        else:
            out.append(_check("credential", False, "No cereal vendor credential: private only (only your wallets, and "
                                                   "your Ledger signs every payment)."))
    return out, cred_status


def _verdict(checks: list[dict], cred_status: str | None) -> tuple[str, list[str]]:
    """block if any blocking check failed, else warn if any warned, else ok (docs/SITES.md). Reasons: blocks first."""
    blocks, warns = [], []
    for ch in checks:
        if ch["ok"] is True:
            continue
        if ch["ok"] is None or ch["name"] == "payee_history":
            warns.append(ch["detail"])
        elif ch["name"] == "credential":
            if cred_status == "revoked":  # none/pending/expired: not a failure, just private only
                blocks.append(ch["detail"])
        else:
            blocks.append(ch["detail"])
    return ("block" if blocks else "warn" if warns else "ok"), blocks + warns


# ---- probe -------------------------------------------------------------------------------------------------------

def _refusal(code: str, reason: str) -> dict:
    return {"ok": False, "refused": code, "reason": reason}


def _with_scheme(url: str) -> str:
    """'example.com/x' means https://…, 'localhost:8004/x' means http://… when that origin is an allowed local test
    merchant; 'file:/…' or 'javascript:…' keep their scheme (and are refused)."""
    if "://" in url or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:(?!\d)", url):
        return url
    try:
        if _origin(*_parse(f"http://{url}")) in _allowed_origins():
            return f"http://{url}"
    except (UnsafeURL, _Malformed):
        pass
    return f"https://{url}"


ARCHIVE_API = "https://archive.org/wayback/available"


def archived_copy(url: str, timeout: float = 8.0) -> dict | None:
    """The Internet Archive's latest snapshot of a page: {url, timestamp (ISO date), source}, or None. A public archive
    is a legitimate way to read a page whose live site blocks agents; it is a dated copy, never the live site."""
    try:
        resp = safe_get(f"{ARCHIVE_API}?url={quote(url, safe='')}", max_bytes=64_000, timeout=timeout)
        snap = (resp.json().get("archived_snapshots") or {}).get("closest") or {}
    except Exception:  # the archive is a convenience: any failure just means no copy is offered
        return None
    ts = str(snap.get("timestamp") or "")
    if not snap.get("available") or str(snap.get("status")) != "200" or not re.fullmatch(r"\d{14}", ts):
        return None
    snap_url = str(snap.get("url") or "")
    if not snap_url.startswith(("http://web.archive.org/", "https://web.archive.org/")):
        return None
    return {"url": "https://" + snap_url.split("://", 1)[1], "source": "Internet Archive",
            "timestamp": f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"}


def probe(url: str) -> dict:
    """What a site is and whether cereal could pay it. Never pays, never signs.

    Returns {ok: True, url, origin, host, kind, status, title, payment, accepts, reason, credential, checks, verdict,
    verdict_reasons, trust_hint} as specified in docs/SITES.md, or a refusal {ok: False, refused: invalid_url |
    unsafe_url, reason}."""
    if not isinstance(url, str) or not url.strip():
        return _refusal("invalid_url", "Give a web address, like https://example.com.")
    try:
        url = urldefrag(_with_scheme(url.strip()))[0]
        _wire_host(_parse(url)[1])
    except _Malformed as e:
        return _refusal("invalid_url", str(e))
    except UnsafeURL as e:
        return _refusal("unsafe_url", str(e))
    except ValueError:
        return _refusal("invalid_url", "cereal cannot read that address.")

    def where(u: str) -> tuple[str, str]:
        """(display origin, host) of a URL that already passed the guard; requests may have percent-encoded it, so
        this does not re-apply the input length rules."""
        p = urlsplit(u)
        scheme, host = p.scheme.lower(), p.hostname or ""
        try:
            port = p.port
        except ValueError:
            port = None
        return _origin(scheme, host, port or (443 if scheme == "https" else 80), display=True), host

    def result(kind: str, final_url: str, status: int | None, **kw) -> dict:
        origin, host = where(final_url)
        out = {"ok": True, "url": final_url, "origin": origin, "host": host,
               "kind": kind, "status": status, "title": None, "payment": None, "accepts": [], "reason": None,
               "credential": None, "checks": [], "verdict": "block", "verdict_reasons": [], "trust_hint": "none",
               "blocked_by": None, "archive": None}
        out.update(kw)
        if kind in ("unpayable", "unreachable"):
            out["verdict_reasons"] = [out["reason"]]
        return out

    try:
        resp = safe_get(url, max_bytes=PROBE_MAX_BYTES, timeout=PROBE_TIMEOUT)
    except RedirectProblem as e:  # the site's redirects are broken: not unsafe, just not reachable
        return result("unreachable", url, None, reason=str(e))
    except UnsafeURL as e:
        return _refusal("unsafe_url", str(e))
    except requests.RequestException as e:
        return result("unreachable", url, None, reason=_failure_reason(e, PROBE_TIMEOUT))

    final = resp.url or url
    code = resp.status_code
    wall = bot_wall(resp)
    if wall:  # the bot wall's page ("Just a moment...") is not the site: no title; offer a public archived copy
        return result("unreachable", final, code, reason=_unreachable_reason(resp), blocked_by=wall,
                      archive=archived_copy(final))
    if 200 <= code < 300:
        return result("free", final, code, title=_title(resp), verdict="ok", trust_hint="free")
    if code != 402:
        return result("unreachable", final, code, title=_title(resp), reason=_unreachable_reason(resp))

    doc = _payment_required(resp) or {}
    options = [_normalize_option(o) for o in doc.get("accepts") or [] if isinstance(o, dict)][:20]
    accepts = [{"network": _clean(o.get("network"), 60), "asset": _clean(o.get("asset") or o.get("currency"), 80),
                "amount": _amount(o.get("amount")), "scheme": _clean(o.get("scheme"), 20), "label": _label(o)}
               for o in options]
    chosen, req = None, None
    for o in options:
        try:
            req = pick_rlusd_requirement({"accepts": [o]})
        except (KeyError, ValueError, TypeError, AttributeError):  # vendor data: e.g. "extra" that is not an object
            req = None
        if req is not None:
            chosen = o
            break
    if req is None:
        if not options:
            reason = "The site asks for payment (402) but lists no x402 payment options cereal can read."
        else:
            near = next((w for w in map(_why_not_rlusd, options) if w), None)
            if near:
                reason = f"The site takes RLUSD on XRPL testnet, but {near}."
            else:
                wants = " or ".join(dict.fromkeys(a["label"] for a in accepts))
                reason = f"This paywall only takes {wants}; cereal pays RLUSD on XRPL testnet (xrpl:1)."
        return result("unpayable", final, code, accepts=accepts, reason=reason)

    resource = doc.get("resource")
    resource = resource if isinstance(resource, dict) else {}
    extra = req.extra or {}
    payment = {"network": req.network, "asset": req.asset, "issuer": extra.get("issuer"), "amount": _amount(req.amount),
               "pay_to": _clean(req.pay_to, 60) or "",
               "resource": _clean(resource.get("url") or chosen.get("resource"), 500),
               "description": _clean(resource.get("description") or chosen.get("description"), 300),
               "invoice_id": _clean(req.invoice_id(), 100)}
    checks, cred_status = _checks(payment, *where(final))
    verdict, reasons = _verdict(checks, cred_status)
    trust = "blocked" if verdict == "block" else "public" if cred_status == "valid" else "private"
    return result("payable", final, code, payment=payment, accepts=accepts, credential=cred_status, checks=checks,
                  verdict=verdict, verdict_reasons=reasons, trust_hint=trust)
