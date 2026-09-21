"""Global pytest fixtures and test environment isolation."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

__all__ = ["isolate_process_environment"]


@pytest.fixture(autouse=True)
def isolate_process_environment() -> Generator[None, None, None]:
    """Isolate process environment variables across all test cases.

    Snapshots the process environment prior to test execution and restores it
    on teardown, preventing any leaked state from dotenv or os.environ mutation.
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
