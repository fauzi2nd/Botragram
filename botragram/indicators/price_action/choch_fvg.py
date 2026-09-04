"""
Botragram

Description:
    Smart Money Concepts (SMC) CHoCH (Change of Character) and
    Fair Value Gap (FVG) price action indicator.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "ChochFvgResult",
    "FvgZone",
    "calculate_choch_fvg",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE = Decimal("1")
_DECIMAL_TWO = Decimal("2")
_BASE_CONFIDENCE = Decimal("0.70")
_CONFIDENCE_BONUS = Decimal("0.10")


# =============================================================================
# Result Models
# =============================================================================
@dataclass(slots=True, frozen=True)
class FvgZone:
    """Represents an active Fair Value Gap (imbalance) price zone."""

    is_bullish: bool
    top: Decimal
    bottom: Decimal
    midpoint: Decimal
    formed_index: int
    mitigated: bool


@dataclass(slots=True, frozen=True)
class ChochFvgResult:
    """Calculated CHoCH structure shifts and FVG mitigations."""

    has_bullish_choch: bool
    has_bearish_choch: bool
    bullish_fvg_active: bool
    bearish_fvg_active: bool
    retesting_bullish_fvg: bool
    retesting_bearish_fvg: bool
    liquidity_swept: bool
    volume_confirmed: bool
    displacement_confirmed: bool
    confidence: Decimal
    last_swing_high: Decimal | None
    last_swing_low: Decimal | None
    active_fvg: FvgZone | None


# =============================================================================
# Calculation Functions
# =============================================================================
def _find_swing_levels(
    high_prices: Sequence[Decimal],
    low_prices: Sequence[Decimal],
    swing_window: int,
) -> tuple[Decimal | None, Decimal | None]:
    """Identify the most recent confirmed swing high and swing low."""
    n = len(high_prices)
    last_high: Decimal | None = None
    last_low: Decimal | None = None

    for i in range(swing_window, n - swing_window):
        window_highs = high_prices[i - swing_window : i + swing_window + 1]
        window_lows = low_prices[i - swing_window : i + swing_window + 1]

        if high_prices[i] == max(window_highs) and any(
            high_prices[i] > val for val in window_highs
        ):
            last_high = high_prices[i]

        if low_prices[i] == min(window_lows) and any(
            low_prices[i] < val for val in window_lows
        ):
            last_low = low_prices[i]

    return last_high, last_low


def _detect_fvg_zones(
    high_prices: Sequence[Decimal],
    low_prices: Sequence[Decimal],
    close_prices: Sequence[Decimal],
    lookback: int,
    min_gap_ratio: Decimal = Decimal("0.0015"),
) -> list[FvgZone]:
    """Scan recent candles to extract active and unmitigated FVG zones."""
    n = len(high_prices)
    start_idx = max(2, n - lookback)
    fvg_zones: list[FvgZone] = []

    for i in range(start_idx, n):
        # Bullish FVG: Low of candle i > High of candle i-2
        if low_prices[i] > high_prices[i - 2]:
            bottom = high_prices[i - 2]
            top = low_prices[i]
            gap = top - bottom
            midpoint = (top + bottom) / _DECIMAL_TWO

            if midpoint > _DECIMAL_ZERO and (gap / midpoint) < min_gap_ratio:
                continue

            # Check if subsequent candles before n mitigated below bottom
            mitigated = any(low_prices[k] <= bottom for k in range(i + 1, n))
            fvg_zones.append(
                FvgZone(
                    is_bullish=True,
                    top=top,
                    bottom=bottom,
                    midpoint=midpoint,
                    formed_index=i,
                    mitigated=mitigated,
                )
            )

        # Bearish FVG: High of candle i < Low of candle i-2
        elif high_prices[i] < low_prices[i - 2]:
            bottom = high_prices[i]
            top = low_prices[i - 2]
            gap = top - bottom
            midpoint = (top + bottom) / _DECIMAL_TWO

            if midpoint > _DECIMAL_ZERO and (gap / midpoint) < min_gap_ratio:
                continue

            # Check if subsequent candles before n mitigated above top
            mitigated = any(high_prices[k] >= top for k in range(i + 1, n))
            fvg_zones.append(
                FvgZone(
                    is_bullish=False,
                    top=top,
                    bottom=bottom,
                    midpoint=midpoint,
                    formed_index=i,
                    mitigated=mitigated,
                )
            )

    return fvg_zones


def calculate_choch_fvg(
    *,
    high_prices: Sequence[Decimal],
    low_prices: Sequence[Decimal],
    close_prices: Sequence[Decimal],
    open_prices: Sequence[Decimal],
    volumes: Sequence[Decimal],
    swing_window: int = 5,
    fvg_lookback: int = 20,
    volume_period: int = 20,
    volume_multiplier: Decimal = Decimal("1.2"),
    min_body_ratio: Decimal = Decimal("0.50"),
    min_gap_ratio: Decimal = Decimal("0.0015"),
) -> ChochFvgResult:
    """Calculate CHoCH structure shift, liquidity sweeps, and FVG mitigations."""
    if min_gap_ratio < _DECIMAL_ZERO:
        raise ValueError("Minimum gap ratio must not be negative")

    n = len(close_prices)
    if n < max(swing_window * 2 + 1, volume_period + 1):
        raise ValueError(
            f"CHoCH + FVG requires at least "
            f"{max(swing_window * 2 + 1, volume_period + 1)} candles"
        )

    last_swing_high, last_swing_low = _find_swing_levels(
        high_prices=high_prices,
        low_prices=low_prices,
        swing_window=swing_window,
    )

    latest_close = close_prices[-1]
    latest_open = open_prices[-1]
    latest_high = high_prices[-1]
    latest_low = low_prices[-1]
    latest_vol = volumes[-1]

    # Calculate candle body ratio (displacement quality)
    total_range = latest_high - latest_low
    candle_body = abs(latest_close - latest_open)
    body_ratio = (
        candle_body / total_range if total_range > _DECIMAL_ZERO else _DECIMAL_ZERO
    )
    displacement_confirmed = body_ratio >= min_body_ratio

    # Calculate average volume
    recent_vols = volumes[-(volume_period + 1) : -1]
    avg_vol = (
        sum(recent_vols) / Decimal(str(len(recent_vols)))
        if recent_vols
        else _DECIMAL_ZERO
    )
    volume_confirmed = (
        latest_vol >= (avg_vol * volume_multiplier) if avg_vol > _DECIMAL_ZERO else True
    )

    # Detect Liquidity Sweeps in recent window
    sweep_window = min(swing_window * 2, n - 1)
    liquidity_swept = False

    if last_swing_low is not None:
        # Bullish sweep: Low dipped below last swing low but closed above it
        for idx in range(n - sweep_window, n):
            if low_prices[idx] < last_swing_low <= close_prices[idx]:
                liquidity_swept = True
                break

    if not liquidity_swept and last_swing_high is not None:
        # Bearish sweep: High pierced above last swing high but closed below it
        for idx in range(n - sweep_window, n):
            if high_prices[idx] > last_swing_high >= close_prices[idx]:
                liquidity_swept = True
                break

    # Detect Structure Shift (CHoCH)
    has_bullish_choch = False
    has_bearish_choch = False

    if last_swing_high is not None and latest_close > last_swing_high:
        has_bullish_choch = True

    if last_swing_low is not None and latest_close < last_swing_low:
        has_bearish_choch = True

    # Scan FVG zones
    fvg_zones = _detect_fvg_zones(
        high_prices=high_prices,
        low_prices=low_prices,
        close_prices=close_prices,
        lookback=fvg_lookback,
        min_gap_ratio=min_gap_ratio,
    )

    active_bullish_fvgs = [f for f in fvg_zones if f.is_bullish and not f.mitigated]
    active_bearish_fvgs = [f for f in fvg_zones if not f.is_bullish and not f.mitigated]

    retesting_bullish_fvg = False
    retesting_bearish_fvg = False
    active_fvg: FvgZone | None = None

    # Check if latest candle is retesting an active FVG with rejection confirmation
    if active_bullish_fvgs:
        target_fvg = active_bullish_fvgs[-1]
        # Price must touch the FVG zone and close above/at the bottom
        if latest_low <= target_fvg.top and latest_close >= target_fvg.bottom:
            candle_span = latest_high - latest_low
            lower_wick = min(latest_open, latest_close) - latest_low
            is_rejection = (
                lower_wick >= (candle_span * Decimal("0.25"))
                if candle_span > _DECIMAL_ZERO
                else False
            )
            # Bullish confirmation: closed green or formed a lower rejection wick
            if latest_close >= latest_open or is_rejection:
                retesting_bullish_fvg = True
                active_fvg = target_fvg

    if active_bearish_fvgs and not retesting_bullish_fvg:
        target_fvg = active_bearish_fvgs[-1]
        # Price must touch the FVG zone and close below/at the top
        if latest_high >= target_fvg.bottom and latest_close <= target_fvg.top:
            candle_span = latest_high - latest_low
            upper_wick = latest_high - max(latest_open, latest_close)
            is_rejection = (
                upper_wick >= (candle_span * Decimal("0.25"))
                if candle_span > _DECIMAL_ZERO
                else False
            )
            # Bearish confirmation: closed red or formed an upper rejection wick
            if latest_close <= latest_open or is_rejection:
                retesting_bearish_fvg = True
                active_fvg = target_fvg

    # Confidence calculation
    confidence = _BASE_CONFIDENCE
    if liquidity_swept:
        confidence += _CONFIDENCE_BONUS
    if volume_confirmed:
        confidence += _CONFIDENCE_BONUS
    if displacement_confirmed:
        confidence += _CONFIDENCE_BONUS
    confidence = min(confidence, _DECIMAL_ONE)

    return ChochFvgResult(
        has_bullish_choch=has_bullish_choch,
        has_bearish_choch=has_bearish_choch,
        bullish_fvg_active=bool(active_bullish_fvgs),
        bearish_fvg_active=bool(active_bearish_fvgs),
        retesting_bullish_fvg=retesting_bullish_fvg,
        retesting_bearish_fvg=retesting_bearish_fvg,
        liquidity_swept=liquidity_swept,
        volume_confirmed=volume_confirmed,
        displacement_confirmed=displacement_confirmed,
        confidence=confidence,
        last_swing_high=last_swing_high,
        last_swing_low=last_swing_low,
        active_fvg=active_fvg,
    )
