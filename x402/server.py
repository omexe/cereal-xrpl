"""Merchant: an API endpoint that charges per request via x402 on XRPL testnet.

Adapted from https://xrpl.org/docs/agents/agentic-payments-x402
Run: python x402/server.py  (serves on :8000)
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from x402_xrpl.server import require_payment

load_dotenv()

app = FastAPI()

# Requests to /hello without a valid payment get a 402 with payment requirements.
app.middleware("http")(
    require_payment(
        path="/hello",
        price=os.getenv("XRPL_PRICE_DROPS", "1000"),  # 1 XRP = 1,000,000 drops
        pay_to_address=os.getenv("XRPL_PAY_TO"),
        facilitator_url=os.getenv("XRPL_FACILITATOR_URL"),
        network="xrpl:1",  # xrpl:1 = testnet, xrpl:0 = mainnet
        asset="XRP",
        description="A paid hello world endpoint",
        extra={"sourceTag": int(os.getenv("XRPL_SOURCE_TAG", "20260601"))},
    )
)


@app.get("/hello")
async def hello():
    """Paid endpoint."""
    return {"message": "hello from cereal. payment received."}


@app.get("/health")
async def health():
    """Free endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
