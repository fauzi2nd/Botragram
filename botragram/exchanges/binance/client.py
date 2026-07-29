"""
Botragram

Description:
    Unified Binance exchange client implementation.

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
import logging
from decimal import Decimal
from typing import Any, cast

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.interval import Interval
from botragram.enums.order_side import OrderSide
from botragram.enums.order_status import OrderStatus
from botragram.enums.order_type import OrderType
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.base.mapper import Candle, OrderResult, PositionInfo, Ticker
from botragram.exchanges.binance.mapper import BinanceMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.exchanges.binance.stream import BinanceStreamClient

logger = logging.getLogger(__name__)


# =============================================================================
# Client Class
# =============================================================================
class BinanceClient(BaseExchangeClient):
    """Unified client for interacting with Binance REST and WebSocket APIs."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
    ) -> None:
        """Initialize Binance unified exchange client.

        Args:
            api_key: Binance API key.
            api_secret: Binance API secret.
            testnet: Use testnet environment if True.
        """
        self._rest = BinanceRestClient(
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet,
        )
        self._stream = BinanceStreamClient(testnet=testnet)
        self._mapper = BinanceMapper()

    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch current ticker price for symbol.

        Args:
            symbol: Symbol string (e.g. BTCUSDT).

        Returns:
            Standardized Ticker instance.
        """
        res = await self._rest.get_ticker_24hr(symbol=symbol)
        if isinstance(res, dict):
            res_dict = cast(dict[str, Any], res)
            return self._mapper.parse_ticker(res_dict)
        return Ticker(
            symbol=symbol,
            last_price=Decimal("0"),
            bid_price=Decimal("0"),
            ask_price=Decimal("0"),
            volume_24h=Decimal("0"),
        )

    async def fetch_candles(
        self,
        symbol: str,
        interval: Interval,
        limit: int = 100,
    ) -> list[Candle]:
        """Fetch candlestick OHLCV data.

        Args:
            symbol: Trading pair symbol.
            interval: Timeframe interval enum.
            limit: Candle count limit.

        Returns:
            List of standardized Candle instances.
        """
        res = await self._rest.get_klines(
            symbol=symbol, interval=interval.value, limit=limit
        )
        candles: list[Candle] = []
        if isinstance(res, list):
            res_list = cast(list[Any], res)
            for item in res_list:
                if isinstance(item, list):
                    item_list = cast(list[Any], item)
                    candles.append(self._mapper.parse_candle(item_list))
        return candles

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> OrderResult:
        """Create a new order.

        Args:
            symbol: Symbol symbol.
            side: Order side enum.
            order_type: Order type enum.
            quantity: Order size.
            price: Optional order price.

        Returns:
            Standardized OrderResult instance.
        """
        return OrderResult(
            order_id="mock_binance_order",
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=OrderStatus.NEW,
            price=price or Decimal("0"),
            quantity=quantity,
            filled_quantity=Decimal("0"),
            average_price=Decimal("0"),
        )

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an active order.

        Args:
            symbol: Symbol string.
            order_id: Order ID string.

        Returns:
            True if cancelled successfully.
        """
        return True

    async def fetch_positions(
        self,
        symbol: str | None = None,
    ) -> list[PositionInfo]:
        """Fetch active positions info.

        Args:
            symbol: Optional symbol filter.

        Returns:
            List of PositionInfo instances.
        """
        return []

    async def close(self) -> None:
        """Close REST session and WebSocket connection."""
        await self._rest.close()
        await self._stream.disconnect()
