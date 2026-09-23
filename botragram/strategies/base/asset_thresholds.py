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
from botragram.enums import AssetClass

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "resolve_asset_class",
    "resolve_effective_distance_pct",
    "resolve_effective_natr_bounds",
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
) -> tuple[Decimal, Decimal | None]:
    """Calculate asset-class aware minimum and maximum NATR bounds.

    Crypto uses the configured base thresholds unchanged. TradFi CFD instruments
    (Forex, Commodities, Indices) adapt to their natural volatility scale to prevent
    false rejections of valid low-percentage market setups.

    Args:
        symbol: Trading symbol being evaluated.
        base_min_natr: Configured base minimum NATR threshold (typically crypto scale).
        base_max_natr: Optional configured base maximum shock NATR threshold.

    Returns:
        Tuple of (effective_min_natr, effective_max_natr).
    """
    asset_class = resolve_asset_class(symbol)

    if asset_class is AssetClass.FOREX:
        effective_min = min(base_min_natr, _FOREX_MIN_NATR_FLOOR)
        effective_max = (
            min(base_max_natr, _FOREX_MAX_NATR_CEILING)
            if base_max_natr is not None
            else _FOREX_MAX_NATR_CEILING
        )
        return effective_min, effective_max

    if asset_class is AssetClass.COMMODITY:
        effective_min = min(base_min_natr, _COMMODITY_MIN_NATR_FLOOR)
        effective_max = (
            min(base_max_natr, _COMMODITY_MAX_NATR_CEILING)
            if base_max_natr is not None
            else _COMMODITY_MAX_NATR_CEILING
        )
        return effective_min, effective_max

    if asset_class is AssetClass.INDEX:
        effective_min = min(base_min_natr, _INDEX_MIN_NATR_FLOOR)
        effective_max = (
            min(base_max_natr, _INDEX_MAX_NATR_CEILING)
            if base_max_natr is not None
            else _INDEX_MAX_NATR_CEILING
        )
        return effective_min, effective_max

    # AssetClass.CRYPTO uses configured base values
    return base_min_natr, base_max_natr


def resolve_effective_distance_pct(
    symbol: str,
    base_min_sl_pct: Decimal,
    base_min_trend_pct: Decimal,
) -> tuple[Decimal, Decimal]:
    """Calculate asset-class aware minimum Stop Loss and Trend distance percentages.

    Crypto uses the configured base percentages unchanged. TradFi CFD instruments
    adapt to reasonable pip and basis point scales.

    Args:
        symbol: Trading symbol being evaluated.
        base_min_sl_pct: Configured base minimum SL distance percentage.
        base_min_trend_pct: Configured base minimum trend filter distance percentage.

    Returns:
        Tuple of (effective_min_sl_pct, effective_min_trend_pct).
    """
    asset_class = resolve_asset_class(symbol)

    if asset_class is AssetClass.FOREX:
        return (
            min(base_min_sl_pct, _FOREX_MIN_SL_FLOOR),
            min(base_min_trend_pct, _FOREX_MIN_TREND_FLOOR),
        )

    if asset_class is AssetClass.COMMODITY:
        return (
            min(base_min_sl_pct, _COMMODITY_MIN_SL_FLOOR),
            min(base_min_trend_pct, _COMMODITY_MIN_TREND_FLOOR),
        )

    if asset_class is AssetClass.INDEX:
        return (
            min(base_min_sl_pct, _INDEX_MIN_SL_FLOOR),
            min(base_min_trend_pct, _INDEX_MIN_TREND_FLOOR),
        )

    # AssetClass.CRYPTO uses configured base values
    return base_min_sl_pct, base_min_trend_pct
