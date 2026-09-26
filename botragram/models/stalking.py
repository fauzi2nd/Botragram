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
from dataclasses import dataclass, field
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

__all__ = [
    "StalkingFunnelReport",
    "StalkingSetup",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class StalkingFunnelReport:
    """Telemetry report for candidate stalking observation and execution funnel."""

    scanned_count: int = 0
    zone_candidates: int = 0
    rejected_before_register: int = 0
    registered: int = 0
    reversal_confirmed: int = 0
    retest_touched: int = 0
    triggered: int = 0
    invalidated: int = 0
    expired: int = 0
    rejections_by_reason: dict[str, int] = field(
        default_factory=dict[str, int]
    )
    average_stalking_bars: Decimal = Decimal("0.0")

    @property
    def candidate_to_entry_conversion_pct(self) -> Decimal:
        """Percentage of zone candidates that successfully converted to entry."""
        if self.zone_candidates == 0:
            return Decimal("0.0")
        return (
            Decimal(self.triggered) / Decimal(self.zone_candidates) * Decimal("100")
        ).quantize(Decimal("0.1"))

    @property
    def registered_to_entry_conversion_pct(self) -> Decimal:
        """Percentage of registered setups that triggered an entry."""
        if self.registered == 0:
            return Decimal("0.0")
        return (
            Decimal(self.triggered) / Decimal(self.registered) * Decimal("100")
        ).quantize(Decimal("0.1"))

    @property
    def invalidated_pct(self) -> Decimal:
        """Percentage of registered setups invalidated without loss."""
        if self.registered == 0:
            return Decimal("0.0")
        return (
            Decimal(self.invalidated) / Decimal(self.registered) * Decimal("100")
        ).quantize(Decimal("0.1"))

    @property
    def expired_pct(self) -> Decimal:
        """Percentage of registered setups expired after max bars."""
        if self.registered == 0:
            return Decimal("0.0")
        return (
            Decimal(self.expired) / Decimal(self.registered) * Decimal("100")
        ).quantize(Decimal("0.1"))

    def format_funnel_summary(self) -> str:
        """Format clean radar summary matching operational requirements."""
        lines = [
            "PIER STALKING FUNNEL",
            f"Scanned                  : {self.scanned_count}",
            f"Zone candidates          : {self.zone_candidates}",
            f"Rejected before register : {self.rejected_before_register}",
            f"Registered               : {self.registered}",
            f"Reversal confirmed       : {self.reversal_confirmed}",
            f"Retest touched           : {self.retest_touched}",
            f"Triggered                : {self.triggered}",
            f"Invalidated              : {self.invalidated} ({self.invalidated_pct}%)",
            f"Expired                  : {self.expired} ({self.expired_pct}%)",
            (f"Conversion (cand -> entry): {self.candidate_to_entry_conversion_pct}%"),
            f"Avg stalking bars        : {self.average_stalking_bars:.1f}",
        ]
        if self.rejections_by_reason:
            lines.append("Rejections Breakdown:")
            for reason, count in sorted(
                self.rejections_by_reason.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"  {reason:<23}: {count}")
        return "\n".join(lines)


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
    last_processed_candle_close_time: datetime | None = None
    reversal_confirmed: bool = False

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
        if (
            self.last_processed_candle_close_time is not None
            and self.last_processed_candle_close_time.tzinfo is None
        ):
            raise ValueError(
                "Stalking last_processed_candle_close_time must be timezone-aware"
            )
