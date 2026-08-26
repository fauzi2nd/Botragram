"""
Botragram

Description:
    Deterministic capped exponential-backoff policy for async retry owners.

Python:
    3.14+
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from random import SystemRandom

__all__ = ["CappedExponentialBackoff"]


def _system_random_fraction() -> float:
    """Return process-independent jitter without mutable application state."""
    return SystemRandom().random()


@dataclass(slots=True, kw_only=True, frozen=True)
class CappedExponentialBackoff:
    """Calculate bounded retry delays with symmetric jitter."""

    initial_delay_seconds: float = 1.0
    maximum_delay_seconds: float = 60.0
    jitter_ratio: float = 0.2
    random_source: Callable[[], float] = field(
        default=_system_random_fraction,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate retry timing and jitter bounds."""
        if self.initial_delay_seconds <= 0:
            raise ValueError("Initial retry delay must be greater than zero")
        if self.maximum_delay_seconds < self.initial_delay_seconds:
            raise ValueError("Maximum retry delay must cover the initial delay")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("Retry jitter ratio must be within 0..1")

    def get_delay(self, *, attempt: int) -> float:
        """Return one capped jittered delay for a one-based attempt number.

        Args:
            attempt: One-based retry attempt number.

        Returns:
            A finite delay no greater than the configured maximum.

        Raises:
            ValueError: If the attempt or injected random sample is invalid.
        """
        if attempt <= 0:
            raise ValueError("Retry attempt must be greater than zero")

        exponent = min(attempt - 1, 63)
        base_delay = min(
            self.initial_delay_seconds * (2.0**exponent),
            self.maximum_delay_seconds,
        )
        sample = self.random_source()
        if not isfinite(sample) or not 0 <= sample <= 1:
            raise ValueError("Retry random sample must be finite within 0..1")
        multiplier = 1 + self.jitter_ratio * ((2 * sample) - 1)
        return min(self.maximum_delay_seconds, base_delay * multiplier)
