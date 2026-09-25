"""
Botragram

Description:
    Asset-class aware volatility and risk threshold resolver for trading strategies.

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
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.market_calendar import MarketCalendarEngine
from botragram.enums import AssetClass, Interval

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "resolve_asset_class",
    "resolve_effective_distance_pct",
    "resolve_effective_natr_bounds",
    "resolve_timeframe_scale_factor",
]

# =============================================================================
# Constants
# =============================================================================
_CALENDAR_ENGINE: Final[MarketCalendarEngine] = MarketCalendarEngine()

# Dead Market Minimum NATR Floors per Asset Class
_FOREX_MIN_NATR_FLOOR: Final[Decimal] = Decimal("0.0001")
_COMMODITY_MIN_NATR_FLOOR: Final[Decimal] = Decimal("0.0004")
_INDEX_MIN_NATR_FLOOR: Final[Decimal] = Decimal("0.0002")

# Extreme Volatility Shock Maximum NATR Ceilings per Asset Class
_FOREX_MAX_NATR_CEILING: Final[Decimal] = Decimal("0.0050")
_COMMODITY_MAX_NATR_CEILING: Final[Decimal] = Decimal("0.0150")
_INDEX_MAX_NATR_CEILING: Final[Decimal] = Decimal("0.0150")

# Minimum Stop Loss Distance Floors per Asset Class
_FOREX_MIN_SL_FLOOR: Final[Decimal] = Decimal("0.0010")
_COMMODITY_MIN_SL_FLOOR: Final[Decimal] = Decimal("0.0020")
_INDEX_MIN_SL_FLOOR: Final[Decimal] = Decimal("0.0015")

# Minimum Trend Distance Floors per Asset Class
_FOREX_MIN_TREND_FLOOR: Final[Decimal] = Decimal("0.0005")
_COMMODITY_MIN_TREND_FLOOR: Final[Decimal] = Decimal("0.0010")
_INDEX_MIN_TREND_FLOOR: Final[Decimal] = Decimal("0.0010")


# =============================================================================
# Resolver Functions
# =============================================================================
def resolve_timeframe_scale_factor(
    interval: Interval | None,
    base_interval: Interval = Interval.M15,
) -> Decimal:
    """Calculate volatility scaling factor based on the square root of time.

    Baseline is 15-minute timeframe (900 seconds). Shorter timeframes (e.g. 5m, 1m)
    have smaller natural candle ranges and require proportional threshold compression
    (sigma proportional to sqrt(dt)). Longer timeframes (e.g. 1h, 4h) scale upward.

    Args:
        interval: Timeframe interval of the current candle, or None for no scaling.
        base_interval: Reference timeframe for 1.0x baseline scaling (default: 15m).

    Returns:
        Decimal scaling factor (e.g. 1.0 for 15m, ~0.57735 for 5m, 2.0 for 1h).
    """
    if interval is None or interval.seconds == base_interval.seconds:
        return Decimal("1.0")
    ratio = interval.seconds / base_interval.seconds
    return Decimal(f"{ratio**0.5:.6f}")


def resolve_asset_class(symbol: str) -> AssetClass:
    """Return the authoritative asset class for a trading symbol.

    Args:
        symbol: The instrument symbol name (e.g. 'EURUSD', 'BTCUSDT', 'XAUUSD').

    Returns:
        The matching AssetClass enum member.
    """
    return _CALENDAR_ENGINE.classify_asset(symbol)


def resolve_effective_natr_bounds(
    symbol: str,
    base_min_natr: Decimal,
    base_max_natr: Decimal | None = None,
    interval: Interval | None = None,
) -> tuple[Decimal, Decimal | None]:
    """Calculate asset-class and timeframe aware NATR volatility bounds.

    Crypto uses the configured base thresholds scaled by the timeframe factor.
    TradFi CFD instruments (Forex, Commodities, Indices) adapt to their natural
    volatility scale and timeframe to prevent false rejections of valid setups.

    Args:
        symbol: Trading symbol being evaluated.
        base_min_natr: Configured base minimum NATR threshold (typically 15m scale).
        base_max_natr: Optional configured base maximum shock NATR threshold.
        interval: Optional candle timeframe interval for auto-adaptive scaling.

    Returns:
        Tuple of (effective_min_natr, effective_max_natr).
    """
    scale = resolve_timeframe_scale_factor(interval)
    scaled_min_natr = base_min_natr * scale
    scaled_max_natr = base_max_natr * scale if base_max_natr is not None else None

    asset_class = resolve_asset_class(symbol)

    if asset_class is AssetClass.FOREX:
        effective_min = min(scaled_min_natr, _FOREX_MIN_NATR_FLOOR * scale)
        effective_max = (
            min(scaled_max_natr, _FOREX_MAX_NATR_CEILING * scale)
            if scaled_max_natr is not None
            else _FOREX_MAX_NATR_CEILING * scale
        )
        return effective_min, effective_max

    if asset_class is AssetClass.COMMODITY:
        effective_min = min(scaled_min_natr, _COMMODITY_MIN_NATR_FLOOR * scale)
        effective_max = (
            min(scaled_max_natr, _COMMODITY_MAX_NATR_CEILING * scale)
            if scaled_max_natr is not None
            else _COMMODITY_MAX_NATR_CEILING * scale
        )
        return effective_min, effective_max

    if asset_class is AssetClass.INDEX:
        effective_min = min(scaled_min_natr, _INDEX_MIN_NATR_FLOOR * scale)
        effective_max = (
            min(scaled_max_natr, _INDEX_MAX_NATR_CEILING * scale)
            if scaled_max_natr is not None
            else _INDEX_MAX_NATR_CEILING * scale
        )
        return effective_min, effective_max

    # AssetClass.CRYPTO uses scaled base values
    return scaled_min_natr, scaled_max_natr


def resolve_effective_distance_pct(
    symbol: str,
    base_min_sl_pct: Decimal,
    base_min_trend_pct: Decimal,
    interval: Interval | None = None,
) -> tuple[Decimal, Decimal]:
    """Calculate asset-class and timeframe aware SL and Trend distance percentages.

    Crypto uses the configured base percentages scaled by the timeframe factor.
    TradFi CFD instruments adapt to reasonable pip and basis point scales.

    Args:
        symbol: Trading symbol being evaluated.
        base_min_sl_pct: Configured base minimum SL distance percentage.
        base_min_trend_pct: Configured base minimum trend filter distance percentage.
        interval: Optional candle timeframe interval for auto-adaptive scaling.

    Returns:
        Tuple of (effective_min_sl_pct, effective_min_trend_pct).
    """
    scale = resolve_timeframe_scale_factor(interval)
    scaled_min_sl_pct = base_min_sl_pct * scale
    scaled_min_trend_pct = base_min_trend_pct * scale

    asset_class = resolve_asset_class(symbol)

    if asset_class is AssetClass.FOREX:
        return (
            min(scaled_min_sl_pct, _FOREX_MIN_SL_FLOOR * scale),
            min(scaled_min_trend_pct, _FOREX_MIN_TREND_FLOOR * scale),
        )

    if asset_class is AssetClass.COMMODITY:
        return (
            min(scaled_min_sl_pct, _COMMODITY_MIN_SL_FLOOR * scale),
            min(scaled_min_trend_pct, _COMMODITY_MIN_TREND_FLOOR * scale),
        )

    if asset_class is AssetClass.INDEX:
        return (
            min(scaled_min_sl_pct, _INDEX_MIN_SL_FLOOR * scale),
            min(scaled_min_trend_pct, _INDEX_MIN_TREND_FLOOR * scale),
        )

    # AssetClass.CRYPTO uses scaled base values
    return scaled_min_sl_pct, scaled_min_trend_pct
