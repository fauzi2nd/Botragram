"""Durable runtime limits for future autonomous LIVE entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

__all__ = ["RuntimeRiskLimits"]


@dataclass(slots=True, kw_only=True, frozen=True)
class RuntimeRiskLimits:
    """Describe one durable, audited runtime canary-limit snapshot."""

    max_open_positions: int
    max_position_size_usdt: Decimal
    updated_at: datetime
    updated_by: str

    def __post_init__(self) -> None:
        """Validate positive limits and normalized audit provenance."""
        if (
            isinstance(self.max_open_positions, bool)
            or self.max_open_positions <= 0
        ):
            raise ValueError("Runtime maximum open positions must be positive")
        if (
            not self.max_position_size_usdt.is_finite()
            or self.max_position_size_usdt <= Decimal("0")
        ):
            raise ValueError("Runtime maximum position size must be finite and positive")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("Runtime risk-limit timestamp must be timezone-aware")

        normalized_actor = self.updated_by.strip()
        if not normalized_actor:
            raise ValueError("Runtime risk-limit audit actor must not be empty")

        object.__setattr__(self, "updated_at", self.updated_at.astimezone(UTC))
        object.__setattr__(self, "updated_by", normalized_actor)
