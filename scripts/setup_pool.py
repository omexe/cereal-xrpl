"""Create or load cereal's testnet roles and write them to .env. Never prints seeds.

Roles: TREASURY, AGENT, CEREAL_COSIGN, BURNER_1..3, VENDOR_A, VENDOR_B, VENDOR_C, CREDENTIAL_ISSUER.
Existing <ROLE>_SEED values in .env are kept; missing ones are faucet-funded.
Also writes <ROLE>_ADDRESS and the XRPL_BUYER_SEED / XRPL_PAY_TO keys the x402 scripts expect.
Run early: burners must be >=256 ledgers old before AccountDelete works.
"""
from pathlib import Path

from dotenv import dotenv_values
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet, generate_faucet_wallet

ROLES = ["TREASURY", "AGENT", "CEREAL_COSIGN", "BURNER_1", "BURNER_2", "BURNER_3",
         "VENDOR_A", "VENDOR_B", "VENDOR_C", "CREDENTIAL_ISSUER"]
ROOT = Path(__file__).resolve().parents[1]
ENV, EXAMPLE = ROOT / ".env", ROOT / ".env.example"

values = {k: v for k, v in dotenv_values(EXAMPLE).items() if v is not None}
values.update({k: v for k, v in (dotenv_values(ENV) if ENV.exists() else {}).items() if v})
client = JsonRpcClient(values.get("XRPL_TESTNET_RPC_URL") or "https://s.altnet.rippletest.net:51234/")

for role in ROLES:
    key = f"{role}_SEED"
    if values.get(key) and not values[key].startswith("sYour"):
        wallet, source = Wallet.from_seed(values[key]), "kept"
    else:
        wallet, source = generate_faucet_wallet(client), "faucet"
        values[key] = wallet.seed
    values[f"{role}_ADDRESS"] = wallet.classic_address
    print(f"  {role:18s} {wallet.classic_address}  ({source})")

if not values.get("XRPL_BUYER_SEED") or values["XRPL_BUYER_SEED"].startswith("sYour"):
    values["XRPL_BUYER_SEED"] = values["AGENT_SEED"]
values["XRPL_PAY_TO"] = values["VENDOR_A_ADDRESS"]

ENV.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
ENV.chmod(0o600)
print(f"\nwrote {ENV} (mode 600). explorer: https://testnet.xrpl.org/accounts/<address>")
