"""Step 3: an agent payment. The agent signs as one multisig signer; cereal co-signs; the ledger needs both.

Also the two refusals the demo shows: the agent submitting alone (tefBAD_QUORUM) and over budget (tecPATH_PARTIAL).
"""
from __future__ import annotations

import requests
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import Payment
from xrpl.models.transactions.transaction import Transaction
from xrpl.transaction import sign
from xrpl.wallet import Wallet

from . import config
from .ledger import job_memo, multisign_submit, prepare, rlusd, stamp


def build_payment(burner_addr: str, vendor_addr: str, amount: str, job_id: str, tag: str,
                  invoice_id: str | None = None) -> Payment:
    tx = Payment(account=burner_addr, destination=vendor_addr, amount=rlusd(amount), invoice_id=invoice_id)
    return stamp(tx, [job_memo(job_id, tag, kind="pay")])


def agent_sign(tx: Transaction, agent: Wallet, c: JsonRpcClient) -> Transaction:
    """Prepare with a fee sized for two signers and sign as a multisig signer (SigningPubKey stays empty)."""
    return sign(prepare(tx, c, signers_count=2), agent, multisign=True)


def request_cosign(job_id: str, agent_signed: Transaction, url: str = config.COSIGN_URL, timeout: int = 90,
                   deployment: bool = False) -> dict:
    """POST the agent-signed transaction to cereal. Returns the service's result (hash or refusal)."""
    key = "deployment_id" if deployment else "job_id"
    r = requests.post(url, json={key: job_id, "tx": agent_signed.to_xrpl()}, timeout=timeout)
    return r.json()


def pay(job: dict, vendor_addr: str, amount: str, agent: Wallet, c: JsonRpcClient, invoice_id: str | None = None) -> dict:
    tx = build_payment(job["burner"], vendor_addr, amount, job["id"], job["tag"], invoice_id)
    return request_cosign(job["id"], agent_sign(tx, agent, c))


def refusal_single_signer(job: dict, vendor_addr: str, amount: str, agent: Wallet, c: JsonRpcClient) -> dict:
    """The jailbreak beat: the agent signs alone and submits. Expected result: tefBAD_QUORUM."""
    tx = build_payment(job["burner"], vendor_addr, amount, job["id"], job["tag"])
    return multisign_submit(tx, [agent], c, quorum_signers=2)
