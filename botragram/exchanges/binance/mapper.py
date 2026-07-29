"""
Botragram

Description:
    Binance exchange data mapper implementation.

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
from typing import Any

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.order_side import OrderSide
from botragram.enums.order_status import OrderStatus
from botragram.enums.order_type import OrderType
from botragram.enums.position_side import PositionSide
from botragram.exchanges.base.mapper import (
    BaseExchangeMapper,
    Candle,
    OrderResult,
    PositionInfo,
    Ticker,
)
from botragram.utils.decimal import to_decimal


# =============================================================================
# Mapper Implementation Class
# =============================================================================
class BinanceMapper(BaseExchangeMapper):
    """Data mapper for converting Binance API payloads to standard models."""

    def parse_candle(self, raw_data: Any) -> Candle:
        """Parse Binance kline list [open_time, open, high, low, close, volume, ...].

        Args:
            raw_data: List payload from Binance klines API.

        Returns:
            Standardized Candle object.
        """
        return Candle(
            timestamp_ms=int(raw_data[0]),
            open_price=to_decimal(raw_data[1]),
            high_price=to_decimal(raw_data[2]),
            low_price=to_decimal(raw_data[3]),
            close_price=to_decimal(raw_data[4]),
            volume=to_decimal(raw_data[5]),
        )

    def parse_ticker(self, raw_data: Any) -> Ticker:
        """Parse Binance 24hr ticker dict payload.

        Args:
            raw_data: Dict payload from Binance ticker API.

        Returns:
            Standardized Ticker object.
        """
        symbol = str(raw_data.get("symbol", ""))
        last_price = to_decimal(raw_data.get("lastPrice", "0"))
        bid_price = to_decimal(raw_data.get("bidPrice", "0"))
        ask_price = to_decimal(raw_data.get("askPrice", "0"))
        volume_24h = to_decimal(raw_data.get("volume", "0"))
        return Ticker(
            symbol=symbol,
            last_price=last_price,
            bid_price=bid_price,
            ask_price=ask_price,
            volume_24h=volume_24h,
        )

    def parse_order(self, raw_data: Any) -> OrderResult:
        """Parse Binance order dict payload.

        Args:
            raw_data: Dict payload from Binance order API.

        Returns:
            Standardized OrderResult object.
        """
        order_id = str(raw_data.get("orderId", ""))
        symbol = str(raw_data.get("symbol", ""))
        raw_side = str(raw_data.get("side", "BUY")).upper()
        side = OrderSide.BUY if raw_side == "BUY" else OrderSide.SELL

        raw_type = str(raw_data.get("type", "MARKET")).upper()
        order_type = (
            OrderType.LIMIT if raw_type == "LIMIT" else OrderType.MARKET
        )

        raw_status = str(raw_data.get("status", "NEW")).upper()
        status_map = {
            "NEW": OrderStatus.NEW,
            "FILLED": OrderStatus.FILLED,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "CANCELED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.EXPIRED,
        }
        status = status_map.get(raw_status, OrderStatus.NEW)

        price = to_decimal(raw_data.get("price", "0"))
        quantity = to_decimal(raw_data.get("origQty", "0"))
        filled_qty = to_decimal(raw_data.get("executedQty", "0"))
        avg_price = to_decimal(raw_data.get("price", "0"))

        return OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
            price=price,
            quantity=quantity,
            filled_quantity=filled_qty,
            average_price=avg_price,
        )

    def parse_position(self, raw_data: Any) -> PositionInfo:
        """Parse Binance position risk dict payload.

        Args:
            raw_data: Dict payload from Binance positionRisk API.

        Returns:
            Standardized PositionInfo object.
        """
        symbol = str(raw_data.get("symbol", ""))
        raw_side = str(raw_data.get("positionSide", "BOTH")).upper()
        if raw_side == "LONG":
            side = PositionSide.LONG
        elif raw_side == "SHORT":
            side = PositionSide.SHORT
        else:
            side = PositionSide.BOTH

        amt = to_decimal(raw_data.get("positionAmt", "0"))
        entry_price = to_decimal(raw_data.get("entryPrice", "0"))
        mark_price = to_decimal(raw_data.get("markPrice", "0"))
        unrealized_pnl = to_decimal(raw_data.get("unRealizedProfit", "0"))
        leverage = int(raw_data.get("leverage", 1))

        return PositionInfo(
            symbol=symbol,
            position_side=side,
            size=abs(amt),
            entry_price=entry_price,
            mark_price=mark_price,
            unrealized_pnl=unrealized_pnl,
            leverage=leverage,
        )
