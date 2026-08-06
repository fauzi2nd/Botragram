"""
Botragram

Description:
    Binance Spot exchange client implementation.

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
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast

# =============================================================================
# Third-Party Imports
# =============================================================================
import aiohttp

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, OrderSide, OrderType
from botragram.exchanges.base import BaseExchangeClient
from botragram.exchanges.base.mapper import (
    ExchangePayload,
    ExchangeSequencePayload,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import Account, Candle, Order, Position, Ticker, Trade

__all__ = [
    "BinanceExchangeClient",
]


# =============================================================================
# Type Aliases
# =============================================================================
type RequestValue = str | int | float | bool
type RequestParams = dict[str, RequestValue]


# =============================================================================
# Endpoints
# =============================================================================
_PING_ENDPOINT = "/api/v3/ping"
_ACCOUNT_ENDPOINT = "/api/v3/account"
_TICKER_ENDPOINT = "/api/v3/ticker/24hr"
_CANDLES_ENDPOINT = "/api/v3/klines"
_ORDER_ENDPOINT = "/api/v3/order"
_OPEN_ORDERS_ENDPOINT = "/api/v3/openOrders"
_TRADES_ENDPOINT = "/api/v3/myTrades"

_DEFAULT_TIME_IN_FORCE = "GTC"


# =============================================================================
# Binance Exchange Client
# =============================================================================
class BinanceExchangeClient(BaseExchangeClient):
    """Implement Botragram exchange operations using Binance Spot."""

    __slots__ = (
        "_mapper",
        "_rest",
    )

    def __init__(
        self,
        *,
        rest: BinanceRestClient,
        mapper: BinanceExchangeMapper,
    ) -> None:
        """Initialize the Binance exchange client."""
        self._rest = rest
        self._mapper = mapper

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> None:
        """Initialize exchange resources.

        BinanceRestClient creates its HTTP session lazily.
        """

    async def close(self) -> None:
        """Close exchange resources."""
        await self._rest.close()

    async def ping(self) -> bool:
        """Return whether Binance is reachable."""
        try:
            await self._rest.get(_PING_ENDPOINT)
        except (
            aiohttp.ClientError,
            TimeoutError,
            RuntimeError,
            ValueError,
        ):
            return False

        return True

    # =========================================================================
    # Account and Market Data
    # =========================================================================

    async def get_account(self) -> Account:
        """Return current Binance Spot account information."""
        payload = await self._rest.get(
            _ACCOUNT_ENDPOINT,
            authenticated=True,
        )

        return self._mapper.map_account(
            self._require_mapping(payload),
        )

    async def get_ticker(
        self,
        *,
        symbol: str,
    ) -> Ticker:
        """Return the latest 24-hour ticker for a trading symbol."""
        normalized_symbol = self._normalize_symbol(symbol)

        payload = await self._rest.get(
            _TICKER_ENDPOINT,
            params={
                "symbol": normalized_symbol,
            },
        )

        return self._mapper.map_ticker(
            self._require_mapping(payload),
        )

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Return candlestick market data."""
        normalized_symbol = self._normalize_symbol(symbol)
        normalized_interval = self._normalize_interval(interval)

        if limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("Candle start time must not be after end time")

        params: RequestParams = {
            "symbol": normalized_symbol,
            "interval": normalized_interval,
            "limit": limit,
        }

        if start_time is not None:
            params["startTime"] = self._datetime_to_milliseconds(start_time)

        if end_time is not None:
            params["endTime"] = self._datetime_to_milliseconds(end_time)

        payload: object = await self._rest.get(
            _CANDLES_ENDPOINT,
            params=params,
        )

        raw_candles = self._require_sequence(payload)

        candles: tuple[Candle, ...] = tuple(
            self._mapper.map_candle(
                self._require_sequence(item),
                symbol=normalized_symbol,
                interval=interval,
            )
            for item in raw_candles
        )

        return candles

    async def get_trades(
        self,
        *,
        symbol: str,
        limit: int,
    ) -> Sequence[Trade]:
        """Return executed Binance Spot trades for a symbol."""
        if limit <= 0:
            raise ValueError("Trade limit must be greater than zero")

        payload: object = await self._rest.get(
            _TRADES_ENDPOINT,
            params={
                "symbol": self._normalize_symbol(symbol),
                "limit": limit,
            },
            authenticated=True,
        )

        raw_trades = self._require_sequence(payload)

        trades: tuple[Trade, ...] = tuple(
            self._mapper.map_trade(
                self._require_mapping(item),
            )
            for item in raw_trades
        )

        return trades

    # =========================================================================
    # Orders
    # =========================================================================

    async def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> Order:
        """Create a Binance Spot order."""
        if quantity <= 0:
            raise ValueError("Order quantity must be greater than zero")

        params: RequestParams = {
            "symbol": self._normalize_symbol(symbol),
            "side": side.value,
            "type": order_type.value.upper(),
            "quantity": self._format_decimal(quantity),
        }

        if price is not None:
            if price <= 0:
                raise ValueError("Order price must be greater than zero")

            params["price"] = self._format_decimal(price)

        if self._requires_time_in_force(order_type):
            if price is None:
                raise ValueError(f"Order type {order_type.value!r} requires a price")

            params["timeInForce"] = _DEFAULT_TIME_IN_FORCE

        payload = await self._rest.post(
            _ORDER_ENDPOINT,
            params=params,
            authenticated=True,
        )

        return self._mapper.map_order(
            self._require_mapping(payload),
        )

    async def create_protection_orders(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> Sequence[Order]:
        """Create Binance Spot protection orders.

        Binance Spot protection requires exchange-specific conditional/OCO
        handling and dedicated response mapping. This is intentionally not
        emulated with independent orders because one leg could remain active
        after the other fills.
        """
        del symbol, side, quantity, stop_loss, take_profit

        raise NotImplementedError(
            "Binance Spot protection orders require dedicated OCO support"
        )

    async def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Cancel an existing Binance Spot order."""
        payload = await self._rest.delete(
            _ORDER_ENDPOINT,
            params={
                "symbol": self._normalize_symbol(symbol),
                "orderId": self._normalize_order_id(order_id),
            },
            authenticated=True,
        )

        return self._mapper.map_order(
            self._require_mapping(payload),
        )

    async def cancel_all_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Cancel all open Binance Spot orders for one symbol.

        Binance Spot requires a symbol for this operation.
        """
        if symbol is None:
            raise ValueError(
                "Binance Spot requires a symbol when cancelling all orders"
            )

        payload: object = await self._rest.delete(
            _OPEN_ORDERS_ENDPOINT,
            params={
                "symbol": self._normalize_symbol(symbol),
            },
            authenticated=True,
        )

        raw_orders = self._require_sequence(payload)

        orders: tuple[Order, ...] = tuple(
            self._mapper.map_order(
                self._require_mapping(item),
            )
            for item in raw_orders
        )

        return orders

    async def get_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Return a Binance Spot order by identifier."""
        payload = await self._rest.get(
            _ORDER_ENDPOINT,
            params={
                "symbol": self._normalize_symbol(symbol),
                "orderId": self._normalize_order_id(order_id),
            },
            authenticated=True,
        )

        return self._mapper.map_order(
            self._require_mapping(payload),
        )

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open Binance Spot orders."""
        params: RequestParams = {}

        if symbol is not None:
            params["symbol"] = self._normalize_symbol(symbol)

        payload: object = await self._rest.get(
            _OPEN_ORDERS_ENDPOINT,
            params=params or None,
            authenticated=True,
        )

        raw_orders = self._require_sequence(payload)

        orders: tuple[Order, ...] = tuple(
            self._mapper.map_order(
                self._require_mapping(item),
            )
            for item in raw_orders
        )

        return orders

    # =========================================================================
    # Positions
    # =========================================================================

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return current positions.

        Binance Spot represents holdings as account balances rather than
        futures-style positions.
        """
        if symbol is not None:
            self._normalize_symbol(symbol)

        return ()

    async def close_position(
        self,
        *,
        symbol: str,
    ) -> Order:
        """Close an active position.

        Binance Spot cannot infer the sell quantity from a futures-style
        Position model. A higher layer must resolve the asset balance and
        submit the appropriate sell order explicitly.
        """
        self._normalize_symbol(symbol)

        raise NotImplementedError(
            "Binance Spot position closing requires balance-aware order sizing"
        )

    async def close_all_positions(self) -> Sequence[Order]:
        """Close all active positions.

        Binance Spot holdings are balances, not position records.
        """
        raise NotImplementedError(
            "Binance Spot does not expose futures-style positions"
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a Binance symbol."""
        normalized = symbol.strip().upper()

        if not normalized:
            raise ValueError("Trading symbol must not be empty")

        return normalized

    @staticmethod
    def _normalize_interval(
        interval: Interval,
    ) -> str:
        """Return the Binance API interval value."""
        normalized = str(interval.value).strip()

        if not normalized:
            raise ValueError("Candle interval must not be empty")

        return normalized

    @staticmethod
    def _normalize_order_id(
        order_id: str,
    ) -> str:
        """Normalize and validate a Binance order identifier."""
        normalized = order_id.strip()

        if not normalized:
            raise ValueError("Order identifier must not be empty")

        if not normalized.isdecimal():
            raise ValueError(
                "Binance order identifier must contain only decimal digits"
            )

        return normalized

    @staticmethod
    def _format_decimal(
        value: Decimal,
    ) -> str:
        """Format a decimal without exponent notation."""
        return format(value, "f")

    @staticmethod
    def _datetime_to_milliseconds(
        value: datetime,
    ) -> int:
        """Convert a datetime into a Unix timestamp in milliseconds."""
        if value.tzinfo is None:
            normalized = value.replace(tzinfo=timezone.utc)
        else:
            normalized = value.astimezone(timezone.utc)

        return int(normalized.timestamp() * 1_000)

    @staticmethod
    def _requires_time_in_force(
        order_type: OrderType,
    ) -> bool:
        """Return whether the order type requires timeInForce."""
        return order_type.value in {
            "LIMIT",
            "STOP_LOSS_LIMIT",
            "TAKE_PROFIT_LIMIT",
        }

    @staticmethod
    def _require_mapping(
        value: object,
    ) -> ExchangePayload:
        """Return a mapping payload or raise ValueError."""
        if not isinstance(value, Mapping):
            raise ValueError("Expected a mapping response payload")

        return cast(ExchangePayload, value)

    @staticmethod
    def _require_sequence(
        value: object,
    ) -> ExchangeSequencePayload:
        """Return a JSON array as an immutable tuple."""
        if not isinstance(value, list):
            raise ValueError("Expected a list response payload")

        typed_value = cast(list[object], value)

        return tuple(typed_value)

    async def __aenter__(self) -> BinanceExchangeClient:
        """Enter the asynchronous context manager."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        """Exit the asynchronous context manager."""
        del exc_type, exc_value, traceback
        await self.close()
