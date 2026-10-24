"""cereal: disposable, budget-exact XRPL wallets for AI agents. See docs/PROJECT.md."""
import importlib.util as _u

if _u.find_spec("xrpl") is None:  # run with the system Python instead of the project venv
    raise SystemExit("cereal needs the project's virtual environment. From the cereal-xrpl folder, either:\n"
                     "  source .venv/bin/activate        (then python -m cereal... works)\n"
                     "  .venv/bin/python -m cereal...    (one-off)\n"
                     "  make <target>                    (e.g. make retire, make beats)\n"
                     "No .venv yet? Run: make setup")
