"""
Botragram

Description:
    Derivatives Open Interest indicators and market regime classification.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OpenInterestRegime, SignalType
from botragram.models import Candle

__all__ = [
    "OpenInterestConfluence",
    "calculate_oi_change",
    "calculate_oi_sma",
    "classify_oi_regime",
    "evaluate_oi_confluence",
]

_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DECIMAL_HUNDRED: Final[Decimal] = Decimal("100")


# =============================================================================
# Data Models
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class OpenInterestConfluence:
    """Evaluated confluence between a trading signal and derivatives Open Interest."""

    regime: OpenInterestRegime
    oi_delta: Decimal
    oi_change_pct: Decimal
    is_confirmed: bool
    is_warning: bool
    reason: str


# =============================================================================
# Indicator Calculations
# =============================================================================
def calculate_oi_change(
    *,
    candles: Sequence[Candle],
    period: int = 1,
) -> tuple[Decimal, Decimal] | None:
    """Calculate absolute and percentage Open Interest change across candles.

    Args:
        candles: Candles ordered from oldest to newest.
        period: Number of periods back to compare with the latest candle.

    Returns:
        A tuple of (oi_delta, oi_change_pct) or None if insufficient OI data.
    """
    if len(candles) <= period or period <= 0:
        return None

    current_candle = candles[-1]
    previous_candle = candles[-(1 + period)]

    if current_candle.open_interest is None or previous_candle.open_interest is None:
        return None

    current_oi = current_candle.open_interest
    previous_oi = previous_candle.open_interest

    delta = current_oi - previous_oi
    if previous_oi <= _DECIMAL_ZERO:
        change_pct = _DECIMAL_ZERO
    else:
        change_pct = delta / previous_oi

    return (delta, change_pct)


def calculate_oi_sma(
    *,
    candles: Sequence[Candle],
    period: int = 20,
) -> Decimal | None:
    """Calculate Simple Moving Average of Open Interest over recent candles.

    Args:
        candles: Candles ordered from oldest to newest.
        period: Number of recent candles to average.

    Returns:
        Average Open Interest as Decimal, or None if insufficient valid OI data.
    """
    if len(candles) < period or period <= 0:
        return None

    recent_candles = candles[-period:]
    oi_values: list[Decimal] = []
    for candle in recent_candles:
        if candle.open_interest is None:
            return None
        oi_values.append(candle.open_interest)

    return sum(oi_values, _DECIMAL_ZERO) / Decimal(period)


def classify_oi_regime(
    *,
    price_delta: Decimal,
    oi_delta: Decimal,
    price_tolerance: Decimal = _DECIMAL_ZERO,
    oi_tolerance: Decimal = _DECIMAL_ZERO,
) -> OpenInterestRegime:
    """Classify the derivatives market regime from price and Open Interest delta.

    Args:
        price_delta: Change in price (close - open or current - previous).
        oi_delta: Change in Open Interest across the corresponding period.
        price_tolerance: Minimum absolute price movement to qualify as directional.
        oi_tolerance: Minimum absolute OI movement to qualify as directional.

    Returns:
        Classified OpenInterestRegime enum.
    """
    if abs(price_delta) <= price_tolerance or abs(oi_delta) <= oi_tolerance:
        return OpenInterestRegime.NEUTRAL

    if price_delta > _DECIMAL_ZERO:
        if oi_delta > _DECIMAL_ZERO:
            return OpenInterestRegime.LONG_BUILDUP
        return OpenInterestRegime.SHORT_COVERING

    if oi_delta > _DECIMAL_ZERO:
        return OpenInterestRegime.SHORT_BUILDUP
    return OpenInterestRegime.LONG_LIQUIDATION


def evaluate_oi_confluence(
    *,
    signal_type: SignalType,
    candles: Sequence[Candle],
    min_change_pct: Decimal = _DECIMAL_ZERO,
) -> OpenInterestConfluence | None:
    """Evaluate whether derivatives Open Interest confirms a trading signal.

    Args:
        signal_type: Generated candidate signal (BUY, SELL, or HOLD).
        candles: Candles ordered from oldest to newest.
        min_change_pct: Minimum positive OI change percentage required for confirmation.

    Returns:
        OpenInterestConfluence result, or None if signal is HOLD or OI data missing.
    """
    if signal_type is SignalType.HOLD:
        return None

    oi_change = calculate_oi_change(candles=candles, period=1)
    if oi_change is None:
        return None

    oi_delta, oi_change_pct = oi_change
    latest_candle = candles[-1]
    price_delta = latest_candle.close_price - latest_candle.open_price

    regime = classify_oi_regime(price_delta=price_delta, oi_delta=oi_delta)
    pct_formatted = f"{oi_change_pct * _DECIMAL_HUNDRED:+.2f}%"

    if signal_type is SignalType.BUY:
        if regime is OpenInterestRegime.LONG_BUILDUP:
            is_confirmed = oi_change_pct >= min_change_pct
            return OpenInterestConfluence(
                regime=regime,
                oi_delta=oi_delta,
                oi_change_pct=oi_change_pct,
                is_confirmed=is_confirmed,
                is_warning=False,
                reason=f"Bullish Long Buildup: OI expanded {pct_formatted}",
            )
        if regime is OpenInterestRegime.SHORT_COVERING:
            return OpenInterestConfluence(
                regime=regime,
                oi_delta=oi_delta,
                oi_change_pct=oi_change_pct,
                is_confirmed=False,
                is_warning=True,
                reason=f"Warning: Short Covering squeeze {pct_formatted}",
            )
        if regime is OpenInterestRegime.SHORT_BUILDUP:
            return OpenInterestConfluence(
                regime=regime,
                oi_delta=oi_delta,
                oi_change_pct=oi_change_pct,
                is_confirmed=False,
                is_warning=True,
                reason=f"Warning: Contradictory Short Buildup on Buy {pct_formatted}",
            )
        return OpenInterestConfluence(
            regime=regime,
            oi_delta=oi_delta,
            oi_change_pct=oi_change_pct,
            is_confirmed=False,
            is_warning=False,
            reason=f"Neutral/Liquidation OI flow {pct_formatted}",
        )

    if signal_type is SignalType.SELL:
        if regime is OpenInterestRegime.SHORT_BUILDUP:
            is_confirmed = oi_change_pct >= min_change_pct
            return OpenInterestConfluence(
                regime=regime,
                oi_delta=oi_delta,
                oi_change_pct=oi_change_pct,
                is_confirmed=is_confirmed,
                is_warning=False,
                reason=f"Bearish Short Buildup: OI expanded {pct_formatted}",
            )
        if regime is OpenInterestRegime.LONG_LIQUIDATION:
            return OpenInterestConfluence(
                regime=regime,
                oi_delta=oi_delta,
                oi_change_pct=oi_change_pct,
                is_confirmed=False,
                is_warning=True,
                reason=f"Warning: Long Liquidation flush {pct_formatted}",
            )
        if regime is OpenInterestRegime.LONG_BUILDUP:
            return OpenInterestConfluence(
                regime=regime,
                oi_delta=oi_delta,
                oi_change_pct=oi_change_pct,
                is_confirmed=False,
                is_warning=True,
                reason=f"Warning: Contradictory Long Buildup on Sell {pct_formatted}",
            )
        return OpenInterestConfluence(
            regime=regime,
            oi_delta=oi_delta,
            oi_change_pct=oi_change_pct,
            is_confirmed=False,
            is_warning=False,
            reason=f"Neutral/Covering OI flow {pct_formatted}",
        )

    return None
