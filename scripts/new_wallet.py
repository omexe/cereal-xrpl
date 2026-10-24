"""Create and fund a fresh XRPL testnet wallet, then print its address and seed.

Run twice to get a buyer and a merchant wallet. Paste the values into .env.
Never commit seeds.
"""
from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet

TESTNET_RPC = "https://s.altnet.rippletest.net:51234/"

client = JsonRpcClient(TESTNET_RPC)
wallet = generate_faucet_wallet(client, debug=True)

print("\nfunded testnet wallet")
print(f"  address: {wallet.classic_address}")
print(f"  seed:    {wallet.seed}   <- keep secret")
print(f"  explorer: https://testnet.xrpl.org/accounts/{wallet.classic_address}")
