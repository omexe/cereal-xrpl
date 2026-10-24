"""Testnet tests are opt-in: they spend testnet funds and take minutes. Run with --run-testnet (make acceptance)."""
import os

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-testnet", action="store_true", default=False, help="run live XRPL testnet tests")


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
