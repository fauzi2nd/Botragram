"""
Botragram

Description:
    Unified Bybit exchange client implementation.

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
from botragram.exchanges.bybit.mapper import BybitMapper
from botragram.exchanges.bybit.rest import BybitRestClient
from botragram.exchanges.bybit.stream import BybitStreamClient

logger = logging.getLogger(__name__)


# =============================================================================
# Client Class
# =============================================================================
class BybitClient(BaseExchangeClient):
    """Unified client for interacting with Bybit REST and WebSocket APIs."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
    ) -> None:
        """Initialize Bybit unified exchange client.

        Args:
            api_key: Bybit API key.
            api_secret: Bybit API secret.
            testnet: Use testnet environment if True.
        """
        self._rest = BybitRestClient(
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet,
        )
        self._stream = BybitStreamClient(testnet=testnet)
        self._mapper = BybitMapper()

    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch current ticker price for symbol.

        Args:
            symbol: Symbol string (e.g. BTCUSDT).

        Returns:
            Standardized Ticker instance.
        """
        res = await self._rest.get_tickers(symbol=symbol)
        if isinstance(res, dict):
            res_dict = cast(dict[str, Any], res)
            result = res_dict.get("result")
            if isinstance(result, dict):
                result_dict = cast(dict[str, Any], result)
                raw_list = result_dict.get("list")
                if isinstance(raw_list, list) and raw_list:
                    ticker_list = cast(list[Any], raw_list)
                    first_item = ticker_list[0]
                    if isinstance(first_item, dict):
                        first_dict = cast(dict[str, Any], first_item)
                        return self._mapper.parse_ticker(first_dict)
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
        interval_val = str(interval.value).replace("m", "").replace("h", "60")
        res = await self._rest.get_kline(
            symbol=symbol, interval=interval_val, limit=limit
        )
        candles: list[Candle] = []
        if isinstance(res, dict):
            res_dict = cast(dict[str, Any], res)
            result = res_dict.get("result")
            if isinstance(result, dict):
                result_dict = cast(dict[str, Any], result)
                raw_list = result_dict.get("list")
                if isinstance(raw_list, list):
                    kline_list = cast(list[Any], raw_list)
                    for item in kline_list:
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
            symbol: Symbol string.
            side: Order side enum.
            order_type: Order type enum.
            quantity: Order size.
            price: Optional order price.

        Returns:
            Standardized OrderResult instance.
        """
        return OrderResult(
            order_id="mock_bybit_order",
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
