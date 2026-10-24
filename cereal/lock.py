"""Step 1: lock a burner. TrustSet → SignerListSet (2-of-2) → AccountSet(asfDisableMaster), atomically in one Batch.

Order matters: the master key can only be disabled once a signer list exists. The burner's master key signs
this one transaction and must not be used again (drop the seed from memory; the pool script keeps it only
until the lock lands). Fallback: sequential=True sends the three transactions one by one.
"""
from __future__ import annotations

from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import AccountSet, Batch, SignerListSet, TrustSet
from xrpl.models.transactions.account_set import AccountSetAsfFlag
from xrpl.models.transactions.batch import BatchFlag
from xrpl.models.transactions.signer_list_set import SignerEntry
from xrpl.models.transactions.transaction import Transaction
from xrpl.transaction import sign
from xrpl.wallet import Wallet

from . import config
from .ledger import account_info, account_objects, job_memo, prepare, rlusd, sign_submit, stamp, submit_capture


def lock_transactions(burner_addr: str, agent_addr: str, cosign_addr: str, budget: str,
                      recovery_addr: str | None = None) -> list[Transaction]:
    """Signer list {agent 1, cereal 1, [owner's Ledger 2]}, quorum 2.

    With a recovery signer the device alone (weight 2) can sweep and burn without cereal; the agent alone and
    cereal alone still cannot spend. The device multi-signs natively (empty SigningPubKey → multisign prefix).
    """
    entries = [SignerEntry(account=agent_addr, signer_weight=1), SignerEntry(account=cosign_addr, signer_weight=1)]
    if recovery_addr:
        entries.append(SignerEntry(account=recovery_addr, signer_weight=2))
    return [
        TrustSet(account=burner_addr, limit_amount=rlusd(budget)),
        SignerListSet(account=burner_addr, signer_quorum=2, signer_entries=entries),
        AccountSet(account=burner_addr, set_flag=AccountSetAsfFlag.ASF_DISABLE_MASTER),
    ]


def lock_burner(burner: Wallet, agent_addr: str, cosign_addr: str, budget: str, c: JsonRpcClient,
                *, job_id: str = "", tag: str = "", sequential: bool = True,
                recovery_addr: str | None = config.LEDGER_ADDRESS) -> dict | list[dict]:
    """Default is sequential (three transactions, ~12 s): verified on testnet. The Batch form (sequential=False)
    returned tesSUCCESS for the outer transaction while all three inner transactions were rolled back
    (tx 887475D2…, Oct 24): attempt it only for the primitives count, and let the state check decide."""
    acct = burner.classic_address
    memos = [job_memo(job_id, tag, kind="lock")] if job_id else []
    txs = lock_transactions(acct, agent_addr, cosign_addr, budget, recovery_addr)
    if sequential:
        results = []
        for tx in txs:
            r = sign_submit(stamp(tx, memos), burner, c)
            results.append(r)
            if not r["ok"]:
                break
        return results
    seq = int(account_info(c, acct)["Sequence"])
    inner = [Transaction.from_dict({**tx.to_dict(), "sequence": seq + 1 + i, "fee": "0", "signing_pub_key": ""})
             for i, tx in enumerate(txs)]
    batch = Batch(account=acct, raw_transactions=inner, flags=BatchFlag.TF_ALL_OR_NOTHING, sequence=seq,
                  source_tag=config.SOURCE_TAG, memos=memos or None)
    r = submit_capture(sign(prepare(batch, c), burner), c)
    # The outer Batch can be tesSUCCESS while its inner transactions were rolled back (tfAllOrNothing):
    # judge the lock by the ledger state, not by the outer result, and fall back to sequential.
    if r.get("ok") and is_locked(c, acct)["locked"]:
        return r
    r["note"] = "outer batch applied but inner transactions did not take effect; falling back to sequential"
    return [r] + lock_burner(burner, agent_addr, cosign_addr, budget, c, job_id=job_id, tag=tag,
                             sequential=True, recovery_addr=recovery_addr)


def is_locked(c: JsonRpcClient, burner_addr: str) -> dict:
    """Acceptance check for step 1."""
    info = account_info(c, burner_addr)
    lists = account_objects(c, burner_addr, "signer_list")
    master_disabled = bool(int(info.get("Flags", 0)) & 0x00100000)  # lsfDisableMaster
    quorum = lists[0].get("SignerQuorum") if lists else None
    signers = [(e["SignerEntry"]["Account"], e["SignerEntry"]["SignerWeight"]) for e in lists[0].get("SignerEntries", [])] if lists else []
    return {"master_disabled": master_disabled, "signer_quorum": quorum, "signers": signers,
            "locked": master_disabled and quorum == 2}
