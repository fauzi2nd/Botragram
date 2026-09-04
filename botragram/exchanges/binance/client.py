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
from botragram.models import (
    Account,
    Candle,
    ExchangeSymbolRules,
    Order,
    Position,
    Ticker,
    Trade,
)

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
_TIME_ENDPOINT = "/api/v3/time"
_EXCHANGE_INFO_ENDPOINT = "/api/v3/exchangeInfo"
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
        """Initialize the Binance Spot exchange client."""
        self._rest = rest
        self._mapper = mapper

    @property
    def rest_transport(self) -> BinanceRestClient:
        """Return the vendor REST transport for non-trading lifecycle adapters."""
        return self._rest

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> None:
        """Initialize exchange resources and synchronize server time."""
        await self._rest.synchronize_time(path=_TIME_ENDPOINT)

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

    async def get_market_entry_rules(
        self,
        *,
        symbol: str,
    ) -> ExchangeSymbolRules:
        """Return authoritative Binance Spot MARKET quantity rules."""
        payload = await self._rest.get(
            _EXCHANGE_INFO_ENDPOINT,
            params={"symbol": self._normalize_symbol(symbol)},
        )
        symbol_payload = self._get_exchange_info_symbol(payload=payload, symbol=symbol)
        return self._mapper.map_market_entry_rules(symbol_payload)

    async def get_trading_symbols(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[str]:
        """Return active Binance Spot symbols for one quote asset."""
        return await self._get_trading_symbols(
            endpoint=_EXCHANGE_INFO_ENDPOINT,
            quote_asset=quote_asset,
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
        symbol: str | None,
        limit: int,
    ) -> Sequence[Trade]:
        """Return executed Binance Spot trades for a required symbol."""
        if limit <= 0:
            raise ValueError("Trade limit must be greater than zero")
        if symbol is None:
            raise NotImplementedError(
                "Binance Spot account-trade history requires a symbol"
            )

        payload: object = await self._rest.get(
            _TRADES_ENDPOINT,
            params={
                "symbol": self._normalize_symbol(symbol),
                "limit": limit,
            },
            authenticated=True,
        )
        return tuple(
            self._mapper.map_trade(self._require_mapping(item))
            for item in self._require_sequence(payload)
        )

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
        client_order_id: str | None = None,
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
        if client_order_id is not None:
            params["newClientOrderId"] = client_order_id

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
        stop_loss_client_algo_id: str | None = None,
        take_profit_client_algo_id: str | None = None,
    ) -> Sequence[Order]:
        """Create Binance Spot protection orders.

        Binance Spot protection requires exchange-specific conditional/OCO
        handling and dedicated response mapping. This is intentionally not
        emulated with independent orders because one leg could remain active
        after the other fills.
        """
        _ = (
            symbol,
            side,
            quantity,
            stop_loss,
            take_profit,
            stop_loss_client_algo_id,
            take_profit_client_algo_id,
        )

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

    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Return a Binance Spot order by its client-assigned identity."""
        normalized_client_order_id = client_order_id.strip()
        if not normalized_client_order_id:
            raise ValueError("Client order identifier must not be empty")

        payload = await self._rest.get(
            _ORDER_ENDPOINT,
            params={
                "symbol": self._normalize_symbol(symbol),
                "origClientOrderId": normalized_client_order_id,
            },
            authenticated=True,
        )
        return self._mapper.map_order(self._require_mapping(payload))

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

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return Spot protection orders when dedicated OCO support exists."""
        del symbol
        return ()

    async def get_protection_order_by_client_id(
        self, *, symbol: str, client_id: str
    ) -> Order:
        """Reject unsupported Spot conditional-algo lookup semantics."""
        del symbol, client_id
        raise NotImplementedError(
            "Binance Spot protection orders require dedicated OCO support"
        )

    async def ensure_stop_loss_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal,
        client_algo_id: str | None = None,
        previous_client_algo_id: str | None = None,
    ) -> Order:
        """Reject unsupported Spot stop replacement until OCO is implemented."""
        _ = (
            symbol,
            side,
            quantity,
            stop_loss,
            client_algo_id,
            previous_client_algo_id,
        )
        raise NotImplementedError(
            "Binance Spot stop replacement requires dedicated OCO support"
        )

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
        client_order_id: str | None = None,
    ) -> Order:
        """Close an active position.

        Binance Spot cannot infer the sell quantity from a futures-style
        Position model. A higher layer must resolve the asset balance and
        submit the appropriate sell order explicitly.
        """
        self._normalize_symbol(symbol)
        del client_order_id

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

    def _get_exchange_info_symbol(
        self,
        *,
        payload: object,
        symbol: str,
    ) -> ExchangePayload:
        """Return one normalized symbol payload from Binance exchangeInfo."""
        normalized_symbol = self._normalize_symbol(symbol)
        response = self._require_mapping(payload)
        raw_symbols = self._require_sequence(response.get("symbols"))

        for raw_symbol in raw_symbols:
            candidate = self._require_mapping(raw_symbol)
            candidate_symbol = candidate.get("symbol")

            if candidate_symbol == normalized_symbol:
                return candidate

        raise ValueError(f"Binance exchangeInfo did not contain {normalized_symbol!r}")

    async def _get_trading_symbols(
        self,
        *,
        endpoint: str,
        quote_asset: str,
        contract_type: str | None = None,
    ) -> tuple[str, ...]:
        """Read and validate exchange-info symbols at the vendor boundary."""
        normalized_quote_asset = quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Quote asset must not be empty")

        payload = self._require_mapping(await self._rest.get(endpoint))
        raw_symbols = self._require_sequence(payload.get("symbols"))
        symbols: list[str] = []

        for raw_symbol in raw_symbols:
            symbol_info = self._require_mapping(raw_symbol)
            symbol = symbol_info.get("symbol")
            status = symbol_info.get("status")
            raw_quote_asset = symbol_info.get("quoteAsset")

            if (
                not isinstance(symbol, str)
                or not isinstance(status, str)
                or not isinstance(raw_quote_asset, str)
            ):
                raise ValueError("Binance exchange info contains invalid symbol data")

            if status != "TRADING" or raw_quote_asset.upper() != normalized_quote_asset:
                continue

            if contract_type is not None:
                raw_contract_type = symbol_info.get("contractType")

                if raw_contract_type != contract_type:
                    continue

            symbols.append(symbol.upper())

        return tuple(sorted(set(symbols)))

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
