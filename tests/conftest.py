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
