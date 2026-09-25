"""
Botragram

Description:
    Domain model for candidate setup stalking and observation.

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
from datetime import datetime
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    Interval,
    PositionSide,
    StalkingStatus,
    StrategyType,
)

__all__ = ["StalkingSetup"]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class StalkingSetup:
    """Immutable domain model for candidate setup observation."""

    symbol: str
    side: PositionSide
    pattern_name: str
    anchor_price: Decimal
    invalidation_price: Decimal
    target_retest_price: Decimal
    htf_zone_label: str
    current_bar: int
    max_bars: int
    started_at: datetime
    updated_at: datetime
    status: StalkingStatus
    strategy_type: StrategyType = StrategyType.PINBAR_ENGULFING_EMA_RSI
    interval: Interval = Interval.M5
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    confidence: Decimal = Decimal("0.80")

    def __post_init__(self) -> None:
        """Validate invariant boundaries."""
        if not self.symbol.strip():
            raise ValueError("Stalking symbol must not be empty")
        if self.anchor_price <= Decimal("0"):
            raise ValueError("Anchor price must be positive")
        if self.invalidation_price <= Decimal("0"):
            raise ValueError("Invalidation price must be positive")
        if self.target_retest_price <= Decimal("0"):
            raise ValueError("Target retest price must be positive")
        if self.current_bar < 0:
            raise ValueError("Current bar must be non-negative")
        if self.max_bars <= 0:
            raise ValueError("Max bars must be positive")
        if self.confidence < Decimal("0") or self.confidence > Decimal("1"):
            raise ValueError("Stalking confidence must be between 0 and 1")
