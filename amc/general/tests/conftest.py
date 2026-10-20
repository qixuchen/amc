"""Shared pytest setup for amc/general tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

GENERAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = GENERAL_ROOT.parents[1]
for _root in (GENERAL_ROOT, REPO_ROOT, Path(__file__).resolve().parent):
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "unit: fast unit tests, no external services")
