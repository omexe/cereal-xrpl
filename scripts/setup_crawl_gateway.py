"""Create the crawl gateway's account on XRPL testnet (VENDOR_G). Never prints seeds; appends to .env, never rewrites it.

The gateway (make crawl-gateway, :8007) reads a public page for an agent and charges per page over x402 in RLUSD, for
sites that take no crypto themselves. The payment goes to the gateway, never to the site. VENDOR_G gets a faucet-funded
account, an RLUSD trust line, and a cereal vendor credential (issued by CREDENTIAL_ISSUER, accepted by VENDOR_G), so
cereal's co-signer treats it like any credentialed vendor. Safe to rerun.
"""
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xrpl.models.amounts import IssuedCurrencyAmount  # noqa: E402
from xrpl.models.requests import AccountLines  # noqa: E402
from xrpl.models.transactions import TrustSet  # noqa: E402
from xrpl.transaction import submit_and_wait  # noqa: E402
from xrpl.wallet import Wallet, generate_faucet_wallet  # noqa: E402

from cereal import config, vendors  # noqa: E402
from cereal.ledger import client  # noqa: E402

ENV = ROOT / ".env"
RLUSD_HEX = "524C555344000000000000000000000000000000"
ROLE = "VENDOR_G"

c = client()
seed = dotenv_values(ENV).get(f"{ROLE}_SEED")
if seed:
    wallet, source = Wallet.from_seed(seed), "kept"
else:
    wallet, source = generate_faucet_wallet(c), "faucet"
    with ENV.open("a") as f:  # saved the moment it exists: a later step failing must not lose the seed
        f.write(f"\n# Crawl gateway (scripts/setup_crawl_gateway.py)\n{ROLE}_SEED={wallet.seed}\n{ROLE}_ADDRESS={wallet.classic_address}\n")
    ENV.chmod(0o600)
addr = wallet.classic_address
print(f"  {ROLE} {addr} ({source})")

lines = c.request(AccountLines(account=addr, peer=config.RLUSD_ISSUER)).result.get("lines", [])
if not any(l.get("currency") == RLUSD_HEX for l in lines):
    r = submit_and_wait(TrustSet(account=addr, limit_amount=IssuedCurrencyAmount(
        currency=RLUSD_HEX, issuer=config.RLUSD_ISSUER, value="1000000")), c, wallet).result
    print(f"  trust line: {r['meta']['TransactionResult']} {r['hash']}")

issuer = config.wallet("CREDENTIAL_ISSUER")
if vendors.check(c, addr).get("status") != "valid":
    r = vendors.issue(issuer, addr, c, uri="cereal crawl gateway")
    print(f"  credential issued: {r.get('result')} {r.get('hash')}")
    r = vendors.accept(wallet, issuer.classic_address, c)
    print(f"  credential accepted: {r.get('result')} {r.get('hash')}")
print(f"  credential: {vendors.check(c, addr)}")
