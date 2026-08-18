"""Immutable outcome of one LIVE portfolio safety recovery pass."""

from __future__ import annotations

from dataclasses import dataclass

from botragram.enums import (
    LivePortfolioRecoveryStatus,
    LivePortfolioRecoveryUnsafeReason,
)
from botragram.models.position import Position

__all__ = ["LivePortfolioRecoveryResult"]


@dataclass(slots=True, kw_only=True, frozen=True)
class LivePortfolioRecoveryResult:
    """Describe recovered LIVE positions without authorizing runtime activation."""

    status: LivePortfolioRecoveryStatus
    recovered_positions: tuple[Position, ...]
    unsafe_reason: LivePortfolioRecoveryUnsafeReason | None = None
    unsafe_symbol: str | None = None

    def __post_init__(self) -> None:
        """Validate that status, positions, and unsafe details agree."""
        if self.status is LivePortfolioRecoveryStatus.NO_POSITIONS:
            self._require_safe_result(position_count=0)
            return

        if self.status is LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE:
            self._require_safe_result(position_count=1)
            return

        if self.status is LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE:
            if len(self.recovered_positions) < 2:
                raise ValueError("Multiple-position recovery requires two positions")
            self._require_no_unsafe_details()
            return

        if self.status is LivePortfolioRecoveryStatus.UNSAFE:
            if self.unsafe_reason is None:
                raise ValueError("Unsafe portfolio recovery requires an unsafe reason")
            return

        raise ValueError(f"Unsupported portfolio recovery status: {self.status!r}")

    def _require_safe_result(self, *, position_count: int) -> None:
        """Require an exact safe result position count without unsafe details."""
        if len(self.recovered_positions) != position_count:
            raise ValueError(
                "Portfolio recovery status does not match recovered position count"
            )
        self._require_no_unsafe_details()

    def _require_no_unsafe_details(self) -> None:
        """Reject unsafe details attached to a safe portfolio result."""
        if self.unsafe_reason is not None or self.unsafe_symbol is not None:
            raise ValueError("Safe portfolio recovery must not include unsafe details")
