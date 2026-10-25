"""Testnet tests are opt-in: they spend testnet funds and take minutes. Run with --run-testnet (make acceptance)."""
import os

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-testnet", action="store_true", default=False, help="run live XRPL testnet tests")


def pytest_ignore_collect(collection_path, config):
    # Live modules resolve configured wallet roles at import time. Skip them before
    # import so the default offline suite needs neither .env nor wallet credentials.
    if collection_path.name.endswith("_testnet.py"):
        return not (config.getoption("--run-testnet") or os.getenv("CEREAL_RUN_TESTNET") == "1")
    return None


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-testnet") or os.getenv("CEREAL_RUN_TESTNET") == "1":
        return
    skip = pytest.mark.skip(reason="live testnet test: run with --run-testnet (make acceptance)")
    for item in items:
        if "testnet" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_model_calls_unless_marked(request, monkeypatch):
    """Tests never call a model (even with OPENROUTER_API_KEY / ANTHROPIC_API_KEY in .env) unless marked `llm`.
    Testnet tests start services and subagents that inherit this environment, so they stay deterministic too."""
    if request.node.get_closest_marker("llm") is None:
        monkeypatch.setenv("CEREAL_LLM", "off")
    monkeypatch.setenv("CEREAL_SWEEPER", "0")  # test services never sweep or retire in the background


@pytest.fixture(autouse=True)
def _private_lock_dir(tmp_path_factory, monkeypatch):
    """Offline tests take cereal's machine-wide locks in a private directory: they never wait behind a live service
    (or another worker's testnet run) on /tmp/cereal-treasury.lock, and they leave no lock files behind."""
    from cereal import xlock
    private = tmp_path_factory.getbasetemp()
    monkeypatch.setattr(xlock, "LOCK_DIR", private)
    monkeypatch.setenv("CEREAL_LOCK_DIR", str(private))  # child processes a test starts inherit it
