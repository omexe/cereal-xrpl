"""Step 8: burn a burner. Payment remainder → treasury, TrustSet to zero, AccountDelete (fail_hard).

All three are multi-signed by the agent and cereal. AccountDelete needs Sequence + 256 < current ledger and no
trust lines, so the pool is created early and the RLUSD line is zeroed first.
"""
from __future__ import annotations

from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import AccountDelete, Payment, TrustSet
from xrpl.wallet import Wallet

from .ledger import account_info, job_memo, ledger_index, multisign_submit, rlusd, rlusd_balance, stamp

TF_SET_NO_RIPPLE = 0x00020000


def burnable_in(c: JsonRpcClient, burner_addr: str) -> int:
    """Ledgers until AccountDelete is allowed (<= 0 means now)."""
    seq = int(account_info(c, burner_addr)["Sequence"])
    return (seq + 256) - ledger_index(c) + 1


def burn(burner_addr: str, treasury_addr: str, agent: Wallet, cosign: Wallet, c: JsonRpcClient,
         job_id: str = "", tag: str = "") -> list[tuple[str, dict]]:
    memos = [job_memo(job_id, tag, kind="burn")] if job_id else []
    steps: list[tuple[str, dict]] = []
    remaining = rlusd_balance(c, burner_addr)
    from xrpl.models.requests import AccountLines
    has_line = bool(c.request(AccountLines(account=burner_addr)).result.get("lines"))
    if remaining > 0:
        tx = stamp(Payment(account=burner_addr, destination=treasury_addr, amount=rlusd(remaining)), memos)
        r = multisign_submit(tx, [agent, cosign], c)
        steps.append(("sweep", r))
        if not r["ok"]:
            return steps
    # Close the line with NoRipple SET: for an account without DefaultRipple that is the default state, and only a
    # line in default state (zero balance, zero limits, default flags) is deleted. Without it the line survives with
    # lsfLowReserve and AccountDelete fails with tecHAS_OBLIGATIONS (seen on testnet Oct 24, burner r4J4evbR…).
    if has_line:
        r = multisign_submit(stamp(TrustSet(account=burner_addr, limit_amount=rlusd("0"), flags=TF_SET_NO_RIPPLE), memos),
                             [agent, cosign], c)
        steps.append(("trustset_zero", r))
        if not r["ok"]:
            return steps
    r = multisign_submit(stamp(AccountDelete(account=burner_addr, destination=treasury_addr), memos),
                         [agent, cosign], c, fail_hard=True)
    steps.append(("account_delete", r))
    return steps
