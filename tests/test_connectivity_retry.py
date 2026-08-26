"""Validate connectivity classification and bounded retry timing."""

from __future__ import annotations

from socket import gaierror

import pytest

from botragram.app.connectivity import is_transient_connectivity_error
from botragram.utils.retry import CappedExponentialBackoff


@pytest.mark.parametrize(
    "error",
    [
        ConnectionError("connection reset"),
        TimeoutError("request timed out"),
        gaierror(11001, "host not found"),
    ],
)
def test_connectivity_classifier_accepts_transient_network_errors(
    error: BaseException,
) -> None:
    """Recognize transport failures without matching unstable error messages."""
    assert is_transient_connectivity_error(error)


def test_connectivity_classifier_walks_wrapped_error_chain() -> None:
    """Preserve transient identity after an application-boundary wrapper."""
    inner = ConnectionError("connection reset")
    outer = RuntimeError("operation failed")
    outer.__cause__ = inner

    assert is_transient_connectivity_error(outer)


def test_connectivity_classifier_rejects_non_transient_protocol_error() -> None:
    """Do not retry malformed application state as a network outage."""
    assert not is_transient_connectivity_error(ValueError("invalid payload"))


def test_capped_exponential_backoff_is_bounded() -> None:
    """Double retry delay until the configured cap and never exceed it."""
    backoff = CappedExponentialBackoff(
        initial_delay_seconds=1.0,
        maximum_delay_seconds=8.0,
        jitter_ratio=0.0,
        random_source=lambda: 0.5,
    )

    assert tuple(backoff.get_delay(attempt=value) for value in range(1, 7)) == (
        1.0,
        2.0,
        4.0,
        8.0,
        8.0,
        8.0,
    )


def test_capped_exponential_backoff_applies_symmetric_jitter() -> None:
    """Apply deterministic jitter while retaining the maximum bound."""
    low = CappedExponentialBackoff(
        initial_delay_seconds=10.0,
        maximum_delay_seconds=60.0,
        jitter_ratio=0.2,
        random_source=lambda: 0.0,
    )
    high = CappedExponentialBackoff(
        initial_delay_seconds=10.0,
        maximum_delay_seconds=60.0,
        jitter_ratio=0.2,
        random_source=lambda: 1.0,
    )

    assert low.get_delay(attempt=1) == 8.0
    assert high.get_delay(attempt=4) == 60.0
