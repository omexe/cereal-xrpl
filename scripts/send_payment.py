"""Send a plain XRP payment on testnet and print the explorer link.

Usage: python scripts/send_payment.py <destination_address> <amount_xrp>
Reads XRPL_BUYER_SEED from .env.
"""
import os
import sys

from dotenv import load_dotenv
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import Payment
from xrpl.transaction import submit_and_wait
from xrpl.utils import xrp_to_drops
from xrpl.wallet import Wallet

load_dotenv()

if len(sys.argv) != 3:
    sys.exit("usage: python scripts/send_payment.py <destination> <amount_xrp>")

destination, amount_xrp = sys.argv[1], sys.argv[2]
client = JsonRpcClient(os.getenv("XRPL_TESTNET_RPC_URL", "https://s.altnet.rippletest.net:51234/"))
sender = Wallet.from_seed(os.environ["XRPL_BUYER_SEED"])

tx = Payment(
    account=sender.classic_address,
    destination=destination,
    amount=xrp_to_drops(float(amount_xrp)),
)
result = submit_and_wait(tx, client, sender).result

status = result["meta"]["TransactionResult"]
print(f"result: {status}")
print(f"explorer: https://testnet.xrpl.org/transactions/{result['hash']}")
