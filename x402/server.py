"""A vendor's x402 paywall on XRPL testnet: per-item RLUSD prices, settled by the t54 facilitator.

    X402_ITEMS="agenda:0.25,speakers:0.25"  X402_VENDOR="Vendor A"  XRPL_PAY_TO=<vendor address>  X402_PORT=8000
    python x402/server.py

GET /catalog is free: what this vendor sells and at what price (discovery). GET /swell/<item> answers 402 with the
binding price; the facilitator verifies and submits the presented payment (cereal's subagents present one co-signed by
the subagent and cereal). RLUSD is named by its 40-hex code; the facilitator rejects the symbol "RLUSD".
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from x402_xrpl.server import require_payment

load_dotenv()

RLUSD_HEX = "524C555344000000000000000000000000000000"
RLUSD_ISSUER = os.getenv("RLUSD_TESTNET_ISSUER", "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV")
VENDOR = os.getenv("X402_VENDOR", "Vendor A")
PAY_TO = os.getenv("XRPL_PAY_TO")
ITEMS = dict(x.split(":") for x in os.getenv("X402_ITEMS", "agenda:0.25,speakers:0.25,market-data:0.25,xrpl-research:0.25").split(",") if ":" in x)
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
}

app = FastAPI()

for item, price in ITEMS.items():  # one paywall per item, each with its own price
    app.middleware("http")(
        require_payment(
            path=f"/swell/{item}",
            price=price,
            pay_to_address=PAY_TO,
            facilitator_url=os.getenv("XRPL_FACILITATOR_URL"),
            network="xrpl:1",
            asset=RLUSD_HEX,
            issuer=RLUSD_ISSUER,
            description=f"{VENDOR}: Swell {item} (sample data), per request",
            source_tag=int(os.getenv("XRPL_SOURCE_TAG", "20260601")),
        )
    )


@app.get("/catalog")
async def catalog():
    """Free: what this vendor sells and the price of each item. The 402 on the item itself is the binding quote."""
    return {"vendor": VENDOR, "pay_to": PAY_TO, "network": "xrpl:1", "asset": "RLUSD",
            "items": [{"item": i, "path": f"/swell/{i}", "price": p} for i, p in ITEMS.items()]}


@app.get("/swell/{item}")
async def resource(item: str):
    """Paid endpoint (the paywall above answers 402 until a payment settles)."""
    if item not in ITEMS:
        raise HTTPException(404, "not sold here")
    return {"vendor": VENDOR, "item": item, "data": SAMPLE.get(item, {}), "note": "sample data served after an x402 payment"}


@app.get("/health")
async def health():
    """Free endpoint."""
    return {"status": "ok", "vendor": VENDOR, "pay_to": PAY_TO, "items": ITEMS}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("X402_PORT", "8000")))
