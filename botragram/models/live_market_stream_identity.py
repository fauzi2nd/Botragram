"""
Botragram

Description:
    Immutable identity for one live market-stream subscription.

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
from dataclasses import dataclass

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.models.live_runtime_position_context import LiveRuntimePositionContext

__all__ = ["LiveMarketStreamIdentity"]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class LiveMarketStreamIdentity:
    """Identify one market-stream subscription by normalized symbol and interval.

    This identity is intentionally independent from the current live-position
    identity.  It does not authorize multiple positions for one symbol.
    """

    symbol: str
    interval: Interval

    def __post_init__(self) -> None:
        """Normalize and validate the stream symbol."""
        normalized_symbol = self.symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Live market stream symbol must not be empty")

        object.__setattr__(self, "symbol", normalized_symbol)

    @classmethod
    def from_runtime_context(
        cls,
        *,
        context: LiveRuntimePositionContext,
    ) -> LiveMarketStreamIdentity:
        """Create a stream identity from one recovered runtime context.

        Args:
            context: The immutable context that requires a ticker stream.

        Returns:
            The corresponding market-stream identity.
        """
        return cls(symbol=context.symbol, interval=context.interval)
