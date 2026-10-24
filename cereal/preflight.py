"""Environment check: roles, balances, lock state, burn eligibility, vendor credentials. python -m cereal.preflight"""
from __future__ import annotations

from . import config, vendors
from .burn import burnable_in
from .ledger import account_info, client, ledger_index, rlusd_balance
from .lock import is_locked


def main() -> None:
    c = client()
    print(f"rpc {config.RPC_URL}  ledger {ledger_index(c)}  source tag {config.SOURCE_TAG}")
    for role in config.ROLES:
        try:
            addr = config.address(role)
        except RuntimeError as e:
            print(f"  - {role:18s} {e}"); continue
        try:
            info = account_info(c, addr)
        except Exception as e:
            print(f"  ✗ {role:18s} {addr}  {getattr(e, 'data', {}).get('error', e)}"); continue
        line = f"  ✓ {role:18s} {addr}  {int(info['Balance'])/1e6:.2f} XRP  seq {info['Sequence']}"
        try:
            line += f"  RLUSD {rlusd_balance(c, addr)}"
        except Exception:
            pass
        if role.startswith("BURNER"):
            st = is_locked(c, addr); n = burnable_in(c, addr)
            line += f"  locked={st['locked']}  burnable_in={max(n, 0)} ledgers"
        if role.startswith("VENDOR"):
            line += f"  credential={vendors.check(c, addr)['status']}"
        print(line)


if __name__ == "__main__":
    main()
