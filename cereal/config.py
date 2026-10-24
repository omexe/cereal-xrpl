"""Environment, roles and constants. Seeds are read from .env and never logged or returned to an LLM."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from xrpl.wallet import Wallet

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

RPC_URL = os.getenv("QUICKNODE_XRPL_HTTP") or os.getenv("XRPL_TESTNET_RPC_URL") or "https://s.altnet.rippletest.net:51234/"
WS_URL = os.getenv("QUICKNODE_XRPL_WS") or os.getenv("XRPL_TESTNET_WS_URL") or "wss://s.altnet.rippletest.net:51233"
EXPLORER = "https://testnet.xrpl.org"
SOURCE_TAG = int(os.getenv("CEREAL_SOURCE_TAG", "20260601"))
TAG_HMAC_KEY = os.getenv("CEREAL_TAG_HMAC_KEY", "change-me").encode()
COSIGN_URL = os.getenv("COSIGN_URL", "http://localhost:8001/cosign")
RLUSD_ISSUER = os.getenv("RLUSD_TESTNET_ISSUER", "rQhWct2fv4Vc4KRjRgMrxa8xPN9Zx9iLKV")
RLUSD_CURRENCY = "524C555344000000000000000000000000000000"  # "RLUSD" as a 160-bit currency code
VENDOR_CREDENTIAL_TYPE = "cereal:vendor:data"
APPROVAL_WINDOW_LEDGERS = 75  # ≈ 5 minutes at ~4 s per ledger
LEDGER_ADDRESS = os.getenv("LEDGER_ADDRESS")  # the owner's Ledger device account (recovery signer, weight 2); from ledger/ getAddress
JOBS_FILE = ROOT / "jobs.json"  # cereal's private mapping: job → sentence, tag → team/project/task (gitignored)
DEPLOYMENTS_FILE = Path(os.getenv("CEREAL_DEPLOYMENTS_FILE") or ROOT / "deployments.json")  # Part 1 records (gitignored)
KEYS_DIR = ROOT / "keys" / "subagents"  # Part 1: one key file per subagent (gitignored, mode 600)
SERVICE_URL = os.getenv("CEREAL_SERVICE_URL", "http://localhost:8001")
MAX_SUBAGENT_BUDGET = float(os.getenv("MAX_SUBAGENT_BUDGET", "5"))
MAX_OUTSTANDING_BUDGET = float(os.getenv("MAX_OUTSTANDING_BUDGET", "10"))
MAX_ACTIVE_SUBAGENTS = int(os.getenv("MAX_ACTIVE_SUBAGENTS", "5"))
# Part 3 (on by default when a device is configured): the owner's Ledger is a weight-2 recovery signer on every
# subwallet, and approves every subagent's budget on the device before anything touches the ledger.
LEDGER_RECOVERY = os.getenv("CEREAL_LEDGER_RECOVERY", "1" if LEDGER_ADDRESS else "0") == "1"
DEVICE_FUNDING = os.getenv("CEREAL_DEVICE_FUNDING", "1" if LEDGER_ADDRESS else "0") == "1"
DEVICE_DECISION = os.getenv("CEREAL_DEVICE_DECISION", "approve")  # Speculos driver: approve | reject | manual
SPECULOS_URL = os.getenv("SPECULOS_URL", "http://127.0.0.1:5000")
# Part 4: the vendors' x402 paywalls (x402/server.py; vendor B = the revoked vendor, for the refusal beat)
X402_VENDOR_A_URL = os.getenv("X402_VENDOR_A_URL", "http://localhost:8000")
X402_VENDOR_B_URL = os.getenv("X402_VENDOR_B_URL", "http://localhost:8002")
DEVICE_WINDOW_LEDGERS = int(os.getenv("CEREAL_DEVICE_WINDOW_LEDGERS", "150"))  # time for a human to press approve
REQUIRE_VENDOR_CREDENTIAL = os.getenv("CEREAL_REQUIRE_VENDOR_CREDENTIAL", "1") == "1"  # Part 2 (on by default)

ROLES = ["TREASURY", "AGENT", "CEREAL_COSIGN", "BURNER_1", "BURNER_2", "BURNER_3",
         "VENDOR_A", "VENDOR_B", "CREDENTIAL_ISSUER"]


def wallet(role: str) -> Wallet:
    """Wallet for a role from <ROLE>_SEED. Raises if missing. Never print the result's seed."""
    seed = os.getenv(f"{role}_SEED")
    if not seed:
        raise RuntimeError(f"{role}_SEED missing in .env (run scripts/setup_pool.py)")
    return Wallet.from_seed(seed)


def address(role: str) -> str:
    return os.getenv(f"{role}_ADDRESS") or wallet(role).classic_address
