from cereal import config
from cereal.ledger import RESULT_RE, decode_memos, job_memo, job_tag


def test_job_tag_is_deterministic_and_private():
    a = job_tag("growth", "swell-brief", "news"); b = job_tag("growth", "swell-brief", "news")
    assert a == b and len(a) == 32 and "growth" not in a


def test_memo_roundtrip():
    memo = job_memo("ab12cd34", job_tag("t", "p", "k"), kind="pay")
    tx_json = {"Memos": [{"Memo": {"MemoData": memo.memo_data, "MemoType": memo.memo_type, "MemoFormat": memo.memo_format}}]}
    decoded = decode_memos(tx_json)
    assert decoded and decoded[0]["job"] == "ab12cd34" and decoded[0]["kind"] == "pay"


def test_refusal_codes_are_parsed_from_exceptions():
    assert RESULT_RE.search("Transaction failed: tefBAD_QUORUM").group(1) == "tefBAD_QUORUM"
    assert RESULT_RE.search("...tecPATH_PARTIAL...").group(1) == "tecPATH_PARTIAL"
    assert RESULT_RE.search("terNO_DELEGATE_PERMISSION").group(1) == "terNO_DELEGATE_PERMISSION"


def test_rlusd_currency_code_is_160_bit_hex():
    assert len(config.RLUSD_CURRENCY) == 40 and bytes.fromhex(config.RLUSD_CURRENCY)[:5] == b"RLUSD"
