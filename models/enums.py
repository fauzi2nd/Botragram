"""
Trading Bot

Module:
    models.enums

Description:
    Shared enumerations used throughout the trading bot.

Python:
    3.14
"""

from __future__ import annotations

from enum import StrEnum, unique

__all__ = [
    "ExchangeType",
    "MarketType",
    "Timeframe",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "TimeInForce",
    "PositionSide",
    "MarginMode",
    "SignalType",
    "RiskLevel",
    "TrendDirection",
    "TrendStrength",
    "MarketState",
    "VolatilityLevel",
    "VolumeStrength",
    "PriceSource",
]

# =============================================================================
# Exchange
# =============================================================================


@unique
class ExchangeType(StrEnum):
    """Supported exchanges."""

    BINANCE = "binance"
    BITGET = "bitget"
    BYBIT = "bybit"
    OKX = "okx"


@unique
class MarketType(StrEnum):
    """Supported market types."""

    SPOT = "spot"
    LINEAR = "linear"
    INVERSE = "inverse"
    OPTION = "option"


@unique
class Timeframe(StrEnum):
    """Supported candle timeframes."""

    MINUTE_1 = "1m"
    MINUTE_3 = "3m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"

    HOUR_1 = "1h"
    HOUR_2 = "2h"
    HOUR_4 = "4h"
    HOUR_6 = "6h"
    HOUR_12 = "12h"

    DAY_1 = "1d"
    DAY_3 = "3d"

    WEEK_1 = "1w"

    MONTH_1 = "1M"


# =============================================================================
# Orders
# =============================================================================


@unique
class OrderSide(StrEnum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"


@unique
class OrderType(StrEnum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"

    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"

    TAKE_PROFIT_MARKET = "take_profit_market"
    TAKE_PROFIT_LIMIT = "take_profit_limit"

    TRAILING_STOP = "trailing_stop"


@unique
class OrderStatus(StrEnum):
    """CCXT-compatible order status."""

    OPEN = "open"
    CLOSED = "closed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REJECTED = "rejected"


@unique
class TimeInForce(StrEnum):
    """Order execution policy."""

    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    POST_ONLY = "post_only"


# =============================================================================
# Positions
# =============================================================================


@unique
class PositionSide(StrEnum):
    """Position direction."""

    LONG = "long"
    SHORT = "short"


@unique
class MarginMode(StrEnum):
    """Margin mode."""

    CROSS = "cross"
    ISOLATED = "isolated"


# =============================================================================
# Strategy
# =============================================================================


@unique
class SignalType(StrEnum):
    """Trading signal."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@unique
class RiskLevel(StrEnum):
    """Risk level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# =============================================================================
# Analysis
# =============================================================================


@unique
class TrendDirection(StrEnum):
    """Trend direction."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    SIDEWAYS = "sideways"


@unique
class TrendStrength(StrEnum):
    """Trend strength."""

    VERY_WEAK = "very_weak"
    WEAK = "weak"
    NORMAL = "normal"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


@unique
class MarketCondition(StrEnum):
    """Current market condition."""

    TRENDING = "trending"
    RANGING = "ranging"
    BREAKOUT = "breakout"
    REVERSAL = "reversal"
    VOLATILE = "volatile"


@unique
class VolatilityLevel(StrEnum):
    """Volatility level."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


@unique
class VolumeStrength(StrEnum):
    """Volume strength."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


# =============================================================================
# Indicators
# =============================================================================


@unique
class PriceSource(StrEnum):
    """Price source for indicator calculations."""

    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"

    HL2 = "hl2"
    HLC3 = "hlc3"
    OHLC4 = "ohlc4"
    HLCC4 = "hlcc4"