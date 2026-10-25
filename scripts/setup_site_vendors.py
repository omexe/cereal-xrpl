"""Create the test merchants for the Sites feature on XRPL testnet. Never prints seeds; appends to .env, never rewrites it.

    VENDOR_D  honest x402 RLUSD site, NOT credentialed by cereal (a "private site" in someone's list)
    VENDOR_E  takes the payment and never delivers (the delivery check flags it)

Each gets a faucet-funded account, an RLUSD trust line (so it can be paid) and its Domain field set to "localhost",
the host its xrp-ledger.toml is served from (x402/server.py /.well-known/xrp-ledger.toml). Safe to rerun.
"""
from pathlib import Path

from dotenv import dotenv_values
from xrpl.clients import JsonRpcClient
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.requests import AccountInfo, AccountLines
from xrpl.models.transactions import AccountSet, TrustSet
from xrpl.transaction import submit_and_wait
from xrpl.wallet import Wallet, generate_faucet_wallet

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
RLUSD_HEX = "524C555344000000000000000000000000000000"
DOMAIN = "localhost"

values = {k: v for k, v in dotenv_values(ENV).items() if v}
issuer = values.get("RLUSD_TESTNET_ISSUER") or "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV"
client = JsonRpcClient(values.get("QUICKNODE_XRPL_HTTP") or values.get("XRPL_TESTNET_RPC_URL")
                       or "https://s.altnet.rippletest.net:51234/")
for role in ("VENDOR_D", "VENDOR_E"):
    if values.get(f"{role}_SEED"):
        wallet, source = Wallet.from_seed(values[f"{role}_SEED"]), "kept"
    else:
        wallet, source = generate_faucet_wallet(client), "faucet"
        with ENV.open("a") as f:  # saved the moment it exists: a later step failing must not lose the seed
            f.write(f"\n# Sites test merchant (scripts/setup_site_vendors.py)\n{role}_SEED={wallet.seed}\n"
                    f"{role}_ADDRESS={wallet.classic_address}\n")
        ENV.chmod(0o600)
    addr = wallet.classic_address
    lines = client.request(AccountLines(account=addr, peer=issuer)).result.get("lines", [])
    if not any(l.get("currency") == RLUSD_HEX for l in lines):
        r = submit_and_wait(TrustSet(account=addr, limit_amount=IssuedCurrencyAmount(
            currency=RLUSD_HEX, issuer=issuer, value="1000000")), client, wallet).result
        print(f"  {role} trust line: {r['meta']['TransactionResult']} {r['hash']}")
    info = client.request(AccountInfo(account=addr)).result["account_data"]
    if bytes.fromhex(info.get("Domain", "")).decode(errors="replace") != DOMAIN:
        r = submit_and_wait(AccountSet(account=addr, domain=DOMAIN.encode().hex()), client, wallet).result
        print(f"  {role} domain: {r['meta']['TransactionResult']} {r['hash']}")
    print(f"  {role:9s} {addr}  ({source})")

