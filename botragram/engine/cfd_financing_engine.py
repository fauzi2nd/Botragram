"""
Botragram

Description:
    TradFi CFD financing engine for rollover swap and margin boundary rules.

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
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.cfd_sizing_engine import CfdSizingEngine
from botragram.engine.market_calendar import MarketCalendarEngine
from botragram.enums import AssetClass, PositionSide
from botragram.models import (
    CfdFinancingSchedule,
    CfdMarginRequirement,
    CfdOvernightSwapEstimate,
)

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "CfdFinancingEngine",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DAYS_PER_YEAR: Final[Decimal] = Decimal("360")
_DEFAULT_MAINTENANCE_RATIO: Final[Decimal] = Decimal("0.05")


# =============================================================================
# CFD Financing Engine Class
# =============================================================================
class CfdFinancingEngine:
    """Overnight rollover swap tracking and margin requirement validation."""

    __slots__ = (
        "_calendar",
        "_sizing",
    )

    def __init__(
        self,
        calendar: MarketCalendarEngine | None = None,
        sizing: CfdSizingEngine | None = None,
    ) -> None:
        """Initialize the CFD financing engine."""
        self._calendar = calendar if calendar is not None else MarketCalendarEngine()
        self._sizing = (
            sizing if sizing is not None else CfdSizingEngine(calendar=self._calendar)
        )

    def get_financing_schedule(self, symbol: str) -> CfdFinancingSchedule:
        """Return the authoritative financing interest schedule for a symbol."""
        spec = self._sizing.get_contract_spec(symbol)
        asset_class = spec.asset_class

        if asset_class is AssetClass.FOREX:
            return CfdFinancingSchedule(
                symbol=symbol,
                asset_class=asset_class,
                swap_long_apr=Decimal("-0.0350"),
                swap_short_apr=Decimal("0.0050"),
                rollover_cutoff_hour_utc=21,
                triple_swap_day=2,
                max_leverage=spec.max_leverage,
            )

        if asset_class is AssetClass.COMMODITY:
            return CfdFinancingSchedule(
                symbol=symbol,
                asset_class=asset_class,
                swap_long_apr=Decimal("-0.0450"),
                swap_short_apr=Decimal("-0.0150"),
                rollover_cutoff_hour_utc=21,
                triple_swap_day=2,
                max_leverage=spec.max_leverage,
            )

        if asset_class is AssetClass.INDEX:
            return CfdFinancingSchedule(
                symbol=symbol,
                asset_class=asset_class,
                swap_long_apr=Decimal("-0.0500"),
                swap_short_apr=Decimal("-0.0200"),
                rollover_cutoff_hour_utc=21,
                triple_swap_day=4,
                max_leverage=spec.max_leverage,
            )

        return CfdFinancingSchedule(
            symbol=symbol,
            asset_class=AssetClass.CRYPTO,
            swap_long_apr=Decimal("-0.0800"),
            swap_short_apr=Decimal("-0.0800"),
            rollover_cutoff_hour_utc=21,
            triple_swap_day=4,
            max_leverage=spec.max_leverage,
        )

    def is_triple_swap_rollover(self, symbol: str, at: datetime) -> bool:
        """Return True if the given timestamp falls on a triple swap rollover day."""
        schedule = self.get_financing_schedule(symbol)
        utc_dt = at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)
        return utc_dt.weekday() == schedule.triple_swap_day

    def estimate_overnight_swap(
        self,
        *,
        symbol: str,
        side: PositionSide,
        lots: Decimal,
        price: Decimal,
        at: datetime | None = None,
    ) -> CfdOvernightSwapEstimate:
        """Estimate the overnight rollover swap interest charge or credit."""
        if lots <= _DECIMAL_ZERO:
            raise ValueError("lots must be positive")
        if price <= _DECIMAL_ZERO:
            raise ValueError("price must be positive")

        current_time = (
            datetime.now(timezone.utc)
            if at is None
            else (at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc))
        )
        schedule = self.get_financing_schedule(symbol)
        spec = self._sizing.get_contract_spec(symbol)
        notional = lots * spec.contract_size * price

        effective_apr = (
            schedule.swap_long_apr
            if side is PositionSide.LONG
            else schedule.swap_short_apr
        )
        daily_swap = notional * (effective_apr / _DAYS_PER_YEAR)
        is_triple = current_time.weekday() == schedule.triple_swap_day
        multiplier = 3 if is_triple else 1
        total_swap = daily_swap * Decimal(multiplier)

        rollover_time = datetime.combine(
            current_time.date(),
            time(schedule.rollover_cutoff_hour_utc, 0),
            tzinfo=timezone.utc,
        )

        return CfdOvernightSwapEstimate(
            symbol=symbol,
            side=side,
            lots=lots,
            notional=notional,
            daily_swap_amount=daily_swap,
            days_multiplier=multiplier,
            total_swap_charge=total_swap,
            effective_apr=effective_apr,
            is_triple_swap=is_triple,
            rollover_time=rollover_time,
        )

    def calculate_margin_requirement(
        self,
        *,
        symbol: str,
        lots: Decimal,
        price: Decimal,
        leverage: int,
        free_margin: Decimal,
        maintenance_margin_ratio: Decimal = _DEFAULT_MAINTENANCE_RATIO,
    ) -> CfdMarginRequirement:
        """Calculate required margin, maintenance margin, and capital sufficiency."""
        if lots <= _DECIMAL_ZERO:
            raise ValueError("lots must be positive")
        if price <= _DECIMAL_ZERO:
            raise ValueError("price must be positive")
        if leverage <= 0:
            raise ValueError("leverage must be positive")
        if free_margin < _DECIMAL_ZERO:
            raise ValueError("free_margin cannot be negative")

        effective_lev = self.validate_leverage(symbol, leverage)
        spec = self._sizing.get_contract_spec(symbol)
        notional = lots * spec.contract_size * price

        required_margin = notional / Decimal(effective_lev)
        maintenance_margin = notional * maintenance_margin_ratio
        is_sufficient = free_margin >= required_margin

        return CfdMarginRequirement(
            symbol=symbol,
            lots=lots,
            notional=notional,
            leverage=effective_lev,
            required_margin=required_margin,
            maintenance_margin=maintenance_margin,
            is_sufficient=is_sufficient,
            free_margin_available=free_margin,
        )

    def validate_leverage(self, symbol: str, requested_leverage: int) -> int:
        """Cap requested leverage to the symbol's asset class ceiling."""
        if requested_leverage <= 0:
            raise ValueError("requested_leverage must be positive")
        schedule = self.get_financing_schedule(symbol)
        return min(schedule.max_leverage, requested_leverage)
