"""Vendor A: a paid data endpoint that charges RLUSD per request via x402 on XRPL testnet (t54 facilitator).

Adapted from https://xrpl.org/docs/agents/agentic-payments-x402. The facilitator verifies the presented payment and
submits it; cereal's subagents present a payment co-signed by the subagent and cereal (their subwallet is 2-of-2).
Run: python x402/server.py  (serves on :8000; X402_PORT to change)
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from x402_xrpl.server import require_payment

load_dotenv()

RLUSD_ISSUER = os.getenv("RLUSD_TESTNET_ISSUER", "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV")
PRICE = os.getenv("X402_PRICE_RLUSD", "0.25")

app = FastAPI()

# Requests to the paid paths without a valid payment get a 402 with payment requirements (RLUSD on xrpl:1).
app.middleware("http")(
    require_payment(
        path=["/swell/agenda", "/swell/speakers"],
        price=PRICE,
        pay_to_address=os.getenv("XRPL_PAY_TO"),  # VENDOR_A (holds a cereal vendor credential)
        facilitator_url=os.getenv("XRPL_FACILITATOR_URL"),
        network="xrpl:1",  # xrpl:1 = testnet, xrpl:0 = mainnet
        asset="524C555344000000000000000000000000000000",  # RLUSD; IOU codes must be 3 chars or 40-hex
        issuer=RLUSD_ISSUER,
        description="Swell NYC agenda and speakers (sample data), per request",
        source_tag=int(os.getenv("XRPL_SOURCE_TAG", "20260601")),
    )
)

AGENDA = {"event": "XRPL Swell hackathon, NYC", "days": ["Sat Oct 24", "Sun Oct 25"],
          "sessions": [{"time": "Sun 12:30", "title": "Submissions close"}, {"time": "Sun 14:15", "title": "Pitches"}]}
SPEAKERS = {"event": "XRPL Swell hackathon, NYC", "speakers": [{"name": "sample speaker", "talk": "agentic finance"}]}


@app.get("/swell/agenda")
async def agenda():
    """Paid endpoint."""
    return {"data": AGENDA, "note": "sample data served after an x402 payment"}


@app.get("/swell/speakers")
async def speakers():
    """Paid endpoint."""
    return {"data": SPEAKERS, "note": "sample data served after an x402 payment"}


@app.get("/health")
async def health():
    """Free endpoint."""
    return {"status": "ok", "price_rlusd": PRICE, "pay_to": os.getenv("XRPL_PAY_TO")}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("X402_PORT", "8000")))
