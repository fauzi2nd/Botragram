"""
Botragram

Description:
    Base exchange data mapper and standardized payload models.

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
from decimal import Decimal
from typing import Any

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.order_side import OrderSide
from botragram.enums.order_status import OrderStatus
from botragram.enums.order_type import OrderType
from botragram.enums.position_side import PositionSide


# =============================================================================
# Data Models
# =============================================================================
@dataclass(slots=True)
class Candle:
    """Standardized candlestick (OHLCV) model."""

    timestamp_ms: int
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal


@dataclass(slots=True)
class Ticker:
    """Standardized ticker model."""

    symbol: str
    last_price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    volume_24h: Decimal


@dataclass(slots=True)
class OrderResult:
    """Standardized order response model."""

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    price: Decimal
    quantity: Decimal
    filled_quantity: Decimal
    average_price: Decimal


@dataclass(slots=True)
class PositionInfo:
    """Standardized position information model."""

    symbol: str
    position_side: PositionSide
    size: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    leverage: int


# =============================================================================
# Base Mapper Class
# =============================================================================
class BaseExchangeMapper:
    """Base mapper for converting raw exchange responses to standard models."""

    def parse_candle(self, raw_data: Any) -> Candle:
        """Parse raw candle data into Candle object.

        Args:
            raw_data: Raw payload from exchange REST/WS.

        Returns:
            Standardized Candle object.
        """
        raise NotImplementedError("parse_candle must be implemented by subclass")

    def parse_ticker(self, raw_data: Any) -> Ticker:
        """Parse raw ticker payload into Ticker object.

        Args:
            raw_data: Raw payload from exchange REST/WS.

        Returns:
            Standardized Ticker object.
        """
        raise NotImplementedError("parse_ticker must be implemented by subclass")

    def parse_order(self, raw_data: Any) -> OrderResult:
        """Parse raw order response into OrderResult object.

        Args:
            raw_data: Raw payload from exchange REST/WS.

        Returns:
            Standardized OrderResult object.
        """
        raise NotImplementedError("parse_order must be implemented by subclass")

    def parse_position(self, raw_data: Any) -> PositionInfo:
        """Parse raw position response into PositionInfo object.

        Args:
            raw_data: Raw payload from exchange REST/WS.

        Returns:
            Standardized PositionInfo object.
        """
        raise NotImplementedError(
            "parse_position must be implemented by subclass"
        )
