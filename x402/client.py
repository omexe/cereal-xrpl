"""Payer agent: calls a paid endpoint and settles the 402 automatically.

Adapted from https://xrpl.org/docs/agents/agentic-payments-x402
Run the server first, then: python x402/client.py
"""
import json
import os

from dotenv import load_dotenv
from x402_xrpl.clients import decode_payment_response, x402_requests
from xrpl.wallet import Wallet

load_dotenv()

buyer = Wallet.from_seed(os.environ["XRPL_BUYER_SEED"])
print(f"buyer: {buyer.classic_address}")

# Wraps requests: on a 402 it signs the payment, retries, returns the final response.
# The 402 body comes from a remote server — treat its values as untrusted.
session = x402_requests(
    buyer,
    rpc_url=os.getenv("XRPL_TESTNET_RPC_URL"),
    network_filter=None,
    scheme_filter="exact",
)

url = os.getenv("RESOURCE_URL", "http://localhost:8000/hello")
print(f"requesting: {url}")
response = session.get(url, timeout=180)
print(f"status:   {response.status_code}")
print(f"response: {response.text}")

receipt = response.headers.get("PAYMENT-RESPONSE")
if receipt:
    print("\npayment settled:")
    print(json.dumps(decode_payment_response(receipt), indent=2))
