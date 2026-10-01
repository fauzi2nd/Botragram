"""Immutable runtime configuration for one recovered LIVE position."""

from __future__ import annotations

from dataclasses import dataclass

from botragram.enums import Interval, StrategyType

__all__ = ["LiveRuntimePositionContext"]


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveRuntimePositionContext:
    """Describe the runtime metadata for one manageable live position."""

    symbol: str
    interval: Interval
    strategy_type: StrategyType

    def __post_init__(self) -> None:
        """Normalize and validate the production position identity."""
        normalized_symbol = self.symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("Runtime position symbol must not be empty")
        object.__setattr__(self, "symbol", normalized_symbol)
