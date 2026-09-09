"""
Botragram

Description:
    Tests for BybitRateLimitGovernor and response header budget observation.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.exchanges.bybit.rest import (
    BybitRateLimitGovernor,
    BybitRateLimitSnapshot,
    BybitRestClient,
)


def test_governor_initial_state() -> None:
    """Verify governor defaults to unthrottled with full headroom."""
    governor = BybitRateLimitGovernor()
    assert governor.should_throttle_discovery() is False
    snapshot = governor.get_snapshot()
    assert isinstance(snapshot, BybitRateLimitSnapshot)
    assert snapshot.discovery_throttled is False
    assert snapshot.throttle_reason is None
    assert snapshot.retry_after_seconds == 0.0


def test_governor_validation() -> None:
    """Verify invalid throttle percentages are rejected."""
    with pytest.raises(ValueError, match="throttle percentage"):
        BybitRateLimitGovernor(throttle_percent=0)

    with pytest.raises(ValueError, match="throttle percentage"):
        BybitRateLimitGovernor(throttle_percent=101)


def test_governor_throttles_on_429_or_retryable_code() -> None:
    """Throttle when 429 or retryable Bybit error code 10006 is observed."""
    now = [100.0]
    governor = BybitRateLimitGovernor(clock=lambda: now[0])

    governor.observe_response(
        headers={},
        status=429,
        ret_code=10006,
        retry_after_seconds=5.0,
    )
    assert governor.should_throttle_discovery() is True
    snapshot = governor.get_snapshot()
    assert snapshot.discovery_throttled is True
    assert snapshot.throttle_reason == "retry_after"
    assert snapshot.retry_after_seconds == 5.0

    # Advance time before expiry
    now[0] = 104.0
    assert governor.should_throttle_discovery() is True

    # Advance time after expiry
    now[0] = 106.0
    assert governor.should_throttle_discovery() is False


def test_governor_throttles_on_header_headroom() -> None:
    """Throttle when remaining requests fall below safe threshold."""
    now = [100.0]
    governor = BybitRateLimitGovernor(throttle_percent=80, clock=lambda: now[0])

    # 10 limit, 5 remaining -> 50% used -> below 80% throttle threshold
    governor.observe_response(
        headers={
            "X-Bapi-Limit": "10",
            "X-Bapi-Limit-Status": "5",
        },
        status=200,
    )
    assert governor.should_throttle_discovery() is False

    # 10 limit, 2 remaining -> 80% used -> triggers throttle
    governor.observe_response(
        headers={
            "X-Bapi-Limit": "10",
            "X-Bapi-Limit-Status": "2",
        },
        status=200,
    )
    assert governor.should_throttle_discovery() is True
    snapshot = governor.get_snapshot()
    assert snapshot.discovery_throttled is True
    assert snapshot.throttle_reason == "headroom_2_of_10"

    # Replenished -> 10 limit, 9 remaining -> resumes
    governor.observe_response(
        headers={
            "X-Bapi-Limit": "10",
            "X-Bapi-Limit-Status": "9",
        },
        status=200,
    )
    assert governor.should_throttle_discovery() is False


def test_bybit_rest_client_wires_governor() -> None:
    """Verify BybitRestClient creates and exposes a rate limit governor."""
    client = BybitRestClient(base_url="https://api.bybit.com")
    assert isinstance(client.rate_limit_governor, BybitRateLimitGovernor)
