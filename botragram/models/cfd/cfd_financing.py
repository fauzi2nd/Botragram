"""
Botragram

Description:
    TradFi CFD financing, rollover swap, and margin requirement domain models.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import AssetClass, PositionSide

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "CfdFinancingSchedule",
    "CfdMarginRequirement",
    "CfdOvernightSwapEstimate",
]

_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Financing Schedule Model
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class CfdFinancingSchedule:
    """Overnight financing interest and rollover schedule for a CFD symbol."""

    symbol: str
    asset_class: AssetClass
    swap_long_apr: Decimal
    swap_short_apr: Decimal
    rollover_cutoff_hour_utc: int = 21
    triple_swap_day: int = 2
    max_leverage: int = 100

    def __post_init__(self) -> None:
        """Validate financing schedule parameters."""
        if not self.symbol.strip():
            raise ValueError("CfdFinancingSchedule requires a valid symbol")
        if not (0 <= self.rollover_cutoff_hour_utc <= 23):
            raise ValueError("rollover_cutoff_hour_utc must be between 0 and 23")
        if not (0 <= self.triple_swap_day <= 6):
            raise ValueError(
                "triple_swap_day must be between 0 (Monday) and 6 (Sunday)"
            )
        if self.max_leverage <= 0:
            raise ValueError("max_leverage must be positive")


# =============================================================================
# Overnight Swap Estimate Model
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class CfdOvernightSwapEstimate:
    """Estimated overnight financing charge/credit for holding a CFD position."""

    symbol: str
    side: PositionSide
    lots: Decimal
    notional: Decimal
    daily_swap_amount: Decimal
    days_multiplier: int
    total_swap_charge: Decimal
    effective_apr: Decimal
    is_triple_swap: bool
    rollover_time: datetime

    def __post_init__(self) -> None:
        """Validate estimate parameters."""
        if not self.symbol.strip():
            raise ValueError("CfdOvernightSwapEstimate requires a valid symbol")
        if self.lots <= _DECIMAL_ZERO:
            raise ValueError("lots must be positive")
        if self.notional <= _DECIMAL_ZERO:
            raise ValueError("notional must be positive")
        if self.days_multiplier <= 0:
            raise ValueError("days_multiplier must be positive")
        if self.rollover_time.tzinfo is None:
            raise ValueError("rollover_time must be timezone-aware")


# =============================================================================
# Margin Requirement Model
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class CfdMarginRequirement:
    """Margin requirement calculation and sufficiency check for CFD trading."""

    symbol: str
    lots: Decimal
    notional: Decimal
    leverage: int
    required_margin: Decimal
    maintenance_margin: Decimal
    is_sufficient: bool
    free_margin_available: Decimal

    def __post_init__(self) -> None:
        """Validate margin requirement parameters."""
        if not self.symbol.strip():
            raise ValueError("CfdMarginRequirement requires a valid symbol")
        if self.lots <= _DECIMAL_ZERO:
            raise ValueError("lots must be positive")
        if self.notional <= _DECIMAL_ZERO:
            raise ValueError("notional must be positive")
        if self.leverage <= 0:
            raise ValueError("leverage must be positive")
        if self.required_margin <= _DECIMAL_ZERO:
            raise ValueError("required_margin must be positive")
        if self.maintenance_margin <= _DECIMAL_ZERO:
            raise ValueError("maintenance_margin must be positive")
        if self.free_margin_available < _DECIMAL_ZERO:
            raise ValueError("free_margin_available cannot be negative")
