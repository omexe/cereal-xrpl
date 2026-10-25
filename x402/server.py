"""A vendor's x402 paywall on XRPL testnet: per-item RLUSD prices, settled by the t54 facilitator.

    X402_ITEMS="agenda:0.25,speakers:0.25"  X402_VENDOR="Vendor A"  XRPL_PAY_TO=<vendor address>  X402_PORT=8000
    python x402/server.py

Sites-feature test modes (make vendor-d / vendor-e / vendor-f):
    X402_PREFIX=research        items are served at /research/<item> instead of /swell/<item>
    X402_TOML_ADDRESS=<addr>    the address /.well-known/xrp-ledger.toml lists (default XRPL_PAY_TO; a different one
                                is the "payment redirected to someone else" scam the probe must block)
    X402_DELIVERY=fail          take the payment, then answer 500 (the delivery check must flag it)
Free pages at /free/<page> and a paywall that only takes USDC on Base Sepolia at /usdc/<item> (cereal can't pay it).

GET /catalog is free: what this vendor sells and at what price (discovery). GET /swell/<item> answers 402 with the
binding price; the facilitator verifies and submits the presented payment (cereal's subagents present one co-signed by
the subagent and cereal). RLUSD is named by its 40-hex code; the facilitator rejects the symbol "RLUSD".
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from x402_xrpl.server import require_payment

load_dotenv()

RLUSD_HEX = "524C555344000000000000000000000000000000"
RLUSD_ISSUER = os.getenv("RLUSD_TESTNET_ISSUER", "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV")
VENDOR = os.getenv("X402_VENDOR", "Vendor A")
PAY_TO = os.getenv("XRPL_PAY_TO")
ITEMS = dict(x.split(":") for x in os.getenv("X402_ITEMS", "agenda:0.25,speakers:0.25,market-data:0.25,xrpl-research:0.25").split(",") if ":" in x)
PREFIX = os.getenv("X402_PREFIX", "swell")
TOML_ADDRESS = os.getenv("X402_TOML_ADDRESS") or PAY_TO
DELIVERY = os.getenv("X402_DELIVERY", "ok")
SAMPLE = {  # sample data, not an official agenda; no real people
    "market-data": {
        "sample": True, "title": "Market research brief",
        "summary": "Illustrative market-sizing data for the Cereal presentation. These are fictional companies and estimates, not live HubSpot or Crunchbase data.",
        "findings": ["Sample target segment: 120 midsize software companies with 50–250 employees.",
                     "Sample demand: 42 of 120 accounts express interest in automated payment operations.",
                     "Sample annual opportunity: 120 accounts × $2,000 per account = $240,000.",
                     "Next research step: validate company counts, buyer interviews, and willingness to pay against primary sources."],
    },
    "xrpl-research": {
        "sample": True, "title": "XRPL ecosystem research brief",
        "summary": "Fictional research dataset for demonstrating paid source access. No founder, funding, or product claim here is verified real-world research.",
        "findings": ["Sample product: Ledger Grove, a fictional business-payments application.",
                     "Sample documentation coverage: payment creation, vendor verification, and transaction reconciliation.",
                     "Sample founder: Alex Example; sample financing: a fictional $2 million seed round.",
                     "Source verification checklist: official product documentation, founder profiles, and dated investor announcements."],
    },
    "agenda": {"event": "XRPL Swell hackathon, NYC (sample data)",
               "sessions": [{"time": "Sun 12:30", "title": "Submissions close"}, {"time": "Sun 14:15", "title": "Pitches"}]},
    "speakers": {"event": "XRPL Swell hackathon, NYC (sample data)",
                 "speakers": [{"name": "sample speaker 1", "talk": "agentic finance"},
                              {"name": "sample speaker 2", "talk": "payments on XRPL"}]},
    "report": {"title": "XRPL agent payments, market notes (sample data)",
               "sections": ["x402 on XRPL testnet settles in RLUSD through a facilitator",
                            "agents pay per request; budgets live in the payer's wallet"]},
}

app = FastAPI()

for item, price in ITEMS.items():  # one paywall per item, each with its own price
    app.middleware("http")(
        require_payment(
            path=f"/{PREFIX}/{item}",
            price=price,
            pay_to_address=PAY_TO,
            facilitator_url=os.getenv("XRPL_FACILITATOR_URL"),
            network="xrpl:1",
            asset=RLUSD_HEX,
            issuer=RLUSD_ISSUER,
            description=f"{VENDOR}: {item} (sample data), per request",
            source_tag=int(os.getenv("XRPL_SOURCE_TAG", "20260601")),
        )
    )


@app.get("/catalog")
async def catalog():
    """Free: what this vendor sells and the price of each item. The 402 on the item itself is the binding quote."""
    return {"vendor": VENDOR, "pay_to": PAY_TO, "network": "xrpl:1", "asset": "RLUSD",
            "items": [{"item": i, "path": f"/{PREFIX}/{i}", "price": p} for i, p in ITEMS.items()]}


@app.get(f"/{PREFIX}/{{item}}")
async def resource(item: str):
    """Paid endpoint (the paywall above answers 402 until a payment settles)."""
    if item not in ITEMS:
        raise HTTPException(404, "not sold here")
    if DELIVERY == "fail":  # test mode: the payment already settled (the middleware settles first); deliver nothing
        raise HTTPException(500, "temporarily unavailable")
    return {"vendor": VENDOR, "item": item, "data": SAMPLE.get(item, {}), "note": "sample data served after an x402 payment"}


@app.get("/.well-known/xrp-ledger.toml", response_class=PlainTextResponse)
async def xrp_ledger_toml():
    """The XRPL standard way for a site to say which accounts are its own (paired with the account's Domain field)."""
    return f'[[ACCOUNTS]]\naddress = "{TOML_ADDRESS}"\ndesc = "{VENDOR} payments"\n' if TOML_ADDRESS else ""


@app.get("/free/{page}", response_class=HTMLResponse)
async def free_page(page: str):
    """Free: an ordinary web page, no paywall."""
    return (f"<!doctype html><html><head><title>{VENDOR}: {page} (free)</title></head><body><h1>{VENDOR} {page}</h1>"
            f"<p>Free sample page. Paid items: {', '.join(f'/{PREFIX}/{i}' for i in ITEMS)}.</p></body></html>")


@app.get("/usdc/{item}")
async def usdc_only(item: str):
    """A paywall cereal cannot pay: it only accepts USDC on Base Sepolia (x402 v2 shape, no XRPL option)."""
    return JSONResponse(status_code=402, content={"x402Version": 2, "error": "payment required", "accepts": [{
        "scheme": "exact", "network": "eip155:84532", "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        "amount": "100000", "payTo": "0x000000000000000000000000000000000000dEaD", "maxTimeoutSeconds": 60,
        "extra": {"name": "USDC", "version": "2"}}], "resource": {"url": f"/usdc/{item}", "description": f"{VENDOR}: {item} in USDC"}})


@app.get("/health")
async def health():
    """Free endpoint."""
    return {"status": "ok", "vendor": VENDOR, "pay_to": PAY_TO, "items": ITEMS}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("X402_PORT", "8000")))
