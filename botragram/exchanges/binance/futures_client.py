"""
Botragram

Description:
    Binance USD(S)-M Futures exchange client implementation.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

import aiohttp

from botragram.enums import (
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exceptions import (
    ExchangeOrderImmediateTriggerRejectedError,
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderPriceBandRejectedError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.binance.client import BinanceExchangeClient
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient, BinanceRestResponseError
from botragram.models import (
    Account,
    Candle,
    ExchangeSymbolRules,
    ExecutableQuote,
    MarketUniverseEntry,
    Order,
    Position,
    Ticker,
    Trade,
)

__all__ = ["BinanceFuturesExchangeClient"]

type RequestValue = str | int | float | bool
type RequestParams = dict[str, RequestValue]

_PING_ENDPOINT = "/fapi/v1/ping"
_EXCHANGE_INFO_ENDPOINT = "/fapi/v1/exchangeInfo"
_ACCOUNT_ENDPOINT = "/fapi/v3/account"
_TICKER_ENDPOINT = "/fapi/v1/ticker/24hr"
_BOOK_TICKER_ENDPOINT = "/fapi/v1/ticker/bookTicker"
_MARK_PRICE_ENDPOINT = "/fapi/v1/premiumIndex"
_CANDLES_ENDPOINT = "/fapi/v1/klines"
_ORDER_ENDPOINT = "/fapi/v1/order"
_OPEN_ORDERS_ENDPOINT = "/fapi/v1/openOrders"
_ALGO_ORDER_ENDPOINT = "/fapi/v1/algoOrder"
_OPEN_ALGO_ORDERS_ENDPOINT = "/fapi/v1/openAlgoOrders"
_TRADES_ENDPOINT = "/fapi/v1/userTrades"
_POSITIONS_ENDPOINT = "/fapi/v3/positionRisk"

_DEFAULT_TIME_IN_FORCE = "GTC"
_SUPPORTED_ENTRY_ORDER_TYPES = frozenset({OrderType.MARKET, OrderType.LIMIT})
_CLIENT_ORDER_ID_MAX_LENGTH = 36
_BINANCE_ORDER_NOT_FOUND_CODE = -2013
_BINANCE_IMMEDIATE_TRIGGER_REJECTED_CODE = -2021
_BINANCE_PERCENT_PRICE_REJECTED_CODE = -4131
_PROTECTION_RECONCILIATION_ATTEMPTS = 3
_PROTECTION_RECONCILIATION_DELAY_SECONDS = 0.5
_TRANSITIONAL_PROTECTION_STATUSES = frozenset({OrderStatus.TRIGGERING})


class BinanceFuturesExchangeClient(BinanceExchangeClient):
    """Implement Binance USD(S)-M Futures operations in one-way mode."""

    def __init__(
        self,
        *,
        rest: BinanceRestClient,
        mapper: BinanceExchangeMapper,
    ) -> None:
        """Initialize the Binance Futures exchange client."""
        super().__init__(rest=rest, mapper=mapper)

    async def ping(self) -> bool:
        """Return whether Binance Futures is reachable."""
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

    async def get_account(self) -> Account:
        """Return current Binance Futures account information."""
        payload = await self._rest.get(
            _ACCOUNT_ENDPOINT,
            authenticated=True,
        )
        return self._mapper.map_futures_account(
            self._require_mapping(payload),
        )

    async def get_ticker(
        self,
        *,
        symbol: str,
    ) -> Ticker:
        """Return the latest Futures 24-hour ticker."""
        payload = await self._rest.get(
            _TICKER_ENDPOINT,
            params={"symbol": self._normalize_symbol(symbol)},
        )
        return self._mapper.map_ticker(self._require_mapping(payload))

    async def get_executable_quote(
        self,
        *,
        symbol: str,
    ) -> ExecutableQuote:
        """Return the current Futures best bid and ask for a MARKET entry."""
        payload = await self._rest.get(
            _BOOK_TICKER_ENDPOINT,
            params={"symbol": self._normalize_symbol(symbol)},
        )
        return self._mapper.map_futures_executable_quote(self._require_mapping(payload))

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return the current Futures MARK_PRICE for conditional triggers."""
        payload = await self._rest.get(
            _MARK_PRICE_ENDPOINT,
            params={"symbol": self._normalize_symbol(symbol)},
        )
        return self._mapper.map_futures_mark_price(self._require_mapping(payload))

    async def get_trading_symbols(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[str]:
        """Return active Binance USD-M perpetual symbols."""
        return await self._get_trading_symbols(
            endpoint=_EXCHANGE_INFO_ENDPOINT,
            quote_asset=quote_asset,
            contract_type="PERPETUAL",
        )

    async def get_market_universe(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[MarketUniverseEntry]:
        """Return active perpetual symbols ranked by 24-hour quote volume."""
        eligible_symbols = frozenset(
            self._normalize_symbol(symbol)
            for symbol in await self.get_trading_symbols(quote_asset=quote_asset)
        )
        payload = await self._rest.get(_TICKER_ENDPOINT)
        entries: list[MarketUniverseEntry] = []
        seen_symbols: set[str] = set()

        for raw_ticker in self._require_sequence(payload):
            ticker_payload = self._require_mapping(raw_ticker)
            raw_symbol = ticker_payload.get("symbol")

            if not isinstance(raw_symbol, str):
                raise ValueError("Binance bulk ticker must contain a valid symbol")

            normalized_symbol = self._normalize_symbol(raw_symbol)

            if normalized_symbol not in eligible_symbols:
                continue

            if normalized_symbol in seen_symbols:
                raise ValueError(
                    "Binance bulk ticker contains duplicate eligible symbol: "
                    f"{normalized_symbol}"
                )

            entries.append(self._mapper.map_market_universe_entry(ticker_payload))
            seen_symbols.add(normalized_symbol)

        if not entries:
            raise ValueError(
                "Binance market universe contains no usable ranked symbols"
            )

        return tuple(
            sorted(
                entries,
                key=lambda entry: (-entry.quote_volume, entry.symbol),
            )
        )

    async def get_market_entry_rules(
        self,
        *,
        symbol: str,
    ) -> ExchangeSymbolRules:
        """Return authoritative Futures MARKET quantity rules."""
        normalized_symbol = self._normalize_symbol(symbol)
        payload = await self._rest.get(_EXCHANGE_INFO_ENDPOINT)
        symbol_payload = self._get_exchange_info_symbol(
            payload=payload,
            symbol=normalized_symbol,
        )
        return self._mapper.map_market_entry_rules(symbol_payload)

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Return Futures candlestick market data."""
        normalized_symbol = self._normalize_symbol(symbol)

        if limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("Candle start time must not be after end time")

        params: RequestParams = {
            "symbol": normalized_symbol,
            "interval": self._normalize_interval(interval),
            "limit": limit,
        }

        if start_time is not None:
            params["startTime"] = self._datetime_to_milliseconds(start_time)

        if end_time is not None:
            params["endTime"] = self._datetime_to_milliseconds(end_time)

        payload = await self._rest.get(_CANDLES_ENDPOINT, params=params)
        return tuple(
            self._mapper.map_candle(
                self._require_sequence(item),
                symbol=normalized_symbol,
                interval=interval,
            )
            for item in self._require_sequence(payload)
        )

    async def get_trades(
        self,
        *,
        symbol: str,
        limit: int,
    ) -> Sequence[Trade]:
        """Return executed Futures account trades."""
        if limit <= 0:
            raise ValueError("Trade limit must be greater than zero")

        payload = await self._rest.get(
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
        """Create a market or limit Futures entry order."""
        if order_type not in _SUPPORTED_ENTRY_ORDER_TYPES:
            raise ValueError(
                "Futures entry orders support only MARKET and LIMIT; "
                "use create_protection_orders for conditional exits"
            )

        params = self._build_order_params(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            client_order_id=client_order_id,
        )
        return await self._post_order(params=params)

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
        """Create reduce-only stop-loss and take-profit market orders."""
        if quantity <= 0:
            raise ValueError("Protection quantity must be greater than zero")

        normalized_symbol = self._normalize_symbol(symbol)
        orders: list[Order] = []

        for order_type, trigger_price, client_algo_id in (
            (OrderType.STOP_MARKET, stop_loss, stop_loss_client_algo_id),
            (
                OrderType.TAKE_PROFIT_MARKET,
                take_profit,
                take_profit_client_algo_id,
            ),
        ):
            if trigger_price is None:
                continue

            if trigger_price <= 0:
                raise ValueError("Protection trigger price must be greater than zero")

            if client_algo_id is None:
                raise ValueError("Protection client algo identity is required")

            orders.append(
                await self._post_algo_order(
                    params={
                        "algoType": "CONDITIONAL",
                        "symbol": normalized_symbol,
                        "side": side.value,
                        "type": order_type.value.upper(),
                        "quantity": self._format_decimal(quantity),
                        "triggerPrice": self._format_decimal(trigger_price),
                        "reduceOnly": "true",
                        "workingType": "MARK_PRICE",
                        "clientAlgoId": self._normalize_client_order_id(client_algo_id),
                    }
                )
            )

        return tuple(orders)

    async def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Cancel an existing Futures order."""
        payload = await self._rest.delete(
            _ORDER_ENDPOINT,
            params={
                "symbol": self._normalize_symbol(symbol),
                "orderId": self._normalize_order_id(order_id),
            },
            authenticated=True,
        )
        return self._mapper.map_order(self._require_mapping(payload))

    async def cancel_all_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Cancel every matching active Futures order."""
        open_orders = await self.get_open_orders(symbol=symbol)
        cancelled: list[Order] = []

        for order in open_orders:
            cancelled.append(
                await self.cancel_order(
                    symbol=order.symbol,
                    order_id=order.order_id,
                )
            )

        return tuple(cancelled)

    async def get_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Return a Futures order by identifier."""
        payload = await self._rest.get(
            _ORDER_ENDPOINT,
            params={
                "symbol": self._normalize_symbol(symbol),
                "orderId": self._normalize_order_id(order_id),
            },
            authenticated=True,
        )
        return self._mapper.map_order(self._require_mapping(payload))

    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Return one Futures order using Binance's client-order lookup field."""
        try:
            payload = await self._rest.get(
                _ORDER_ENDPOINT,
                params={
                    "symbol": self._normalize_symbol(symbol),
                    "origClientOrderId": self._normalize_client_order_id(
                        client_order_id,
                    ),
                },
                authenticated=True,
            )
        except BinanceRestResponseError as error:
            if error.status == 400 and error.code == _BINANCE_ORDER_NOT_FOUND_CODE:
                raise ExchangeOrderNotFoundError(
                    "Binance Futures order was not found"
                ) from error
            raise ExchangeOrderOutcomeUnknownError(
                "Binance Futures order lookup did not complete"
            ) from error
        except (aiohttp.ClientError, TimeoutError, RuntimeError) as error:
            raise ExchangeOrderOutcomeUnknownError(
                "Binance Futures order lookup did not complete"
            ) from error

        return self._mapper.map_order(self._require_mapping(payload))

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open Futures orders."""
        params: RequestParams | None = None

        if symbol is not None:
            params = {"symbol": self._normalize_symbol(symbol)}

        payload = await self._rest.get(
            _OPEN_ORDERS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        return tuple(
            self._mapper.map_order(self._require_mapping(item))
            for item in self._require_sequence(payload)
        )

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open Futures conditional algo orders."""
        params: RequestParams | None = None

        if symbol is not None:
            params = {"symbol": self._normalize_symbol(symbol)}

        payload = await self._rest.get(
            _OPEN_ALGO_ORDERS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        return tuple(
            self._mapper.map_algo_order(self._require_mapping(item))
            for item in self._require_sequence(payload)
        )

    async def get_protection_order_by_client_id(
        self, *, symbol: str, client_id: str
    ) -> Order:
        """Read one Futures conditional algo order by its client identity.

        A Binance conditional leg can be observed while it is transitioning
        from its trigger to its execution outcome. The read remains GET-only
        and bounded; an unresolved transition is returned for callers to
        fail closed rather than being relabeled as active protection.
        """
        for attempt in range(_PROTECTION_RECONCILIATION_ATTEMPTS):
            try:
                payload = await self._rest.get(
                    _ALGO_ORDER_ENDPOINT,
                    params={"clientAlgoId": self._normalize_client_order_id(client_id)},
                    authenticated=True,
                )
            except BinanceRestResponseError as error:
                if error.code == _BINANCE_ORDER_NOT_FOUND_CODE:
                    raise ExchangeOrderNotFoundError(
                        "Binance Futures protection order was not found"
                    ) from error
                raise
            except (aiohttp.ClientError, TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    "Binance Futures protection lookup outcome is unknown"
                ) from error

            order = self._mapper.map_algo_order(self._require_mapping(payload))
            if (
                order.status not in _TRANSITIONAL_PROTECTION_STATUSES
                or attempt + 1 == _PROTECTION_RECONCILIATION_ATTEMPTS
            ):
                return order

            await asyncio.sleep(_PROTECTION_RECONCILIATION_DELAY_SECONDS)

        raise RuntimeError("Binance protection lookup did not produce an order")

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> None:
        """Cancel one Futures conditional order by exact durable client identity.

        The DELETE is attempted at most once. Any transport or HTTP uncertainty
        is surfaced so the caller can reconcile exclusively through GET reads.
        """
        self._normalize_symbol(symbol)
        try:
            await self._rest.delete(
                _ALGO_ORDER_ENDPOINT,
                params={
                    "clientAlgoId": self._normalize_client_order_id(client_id),
                },
                authenticated=True,
            )
        except BinanceRestResponseError as error:
            raise ExchangeOrderOutcomeUnknownError(
                "Binance Futures protection cancellation outcome is unknown"
            ) from error
        except (aiohttp.ClientError, TimeoutError, RuntimeError) as error:
            raise ExchangeOrderOutcomeUnknownError(
                "Binance Futures protection cancellation outcome is unknown"
            ) from error

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
        """Ensure one exact durable replacement and retire its predecessor."""
        if quantity <= 0:
            raise ValueError("Stop-loss quantity must be greater than zero")
        if stop_loss <= 0:
            raise ValueError("Stop-loss trigger price must be greater than zero")

        normalized_symbol = self._normalize_symbol(symbol)
        candidates = self._matching_stop_orders(
            orders=await self.get_open_protection_orders(symbol=normalized_symbol),
            symbol=normalized_symbol,
            side=side,
            quantity=quantity,
        )
        target: Order | None = None

        if client_algo_id is not None:
            target = next(
                (
                    order
                    for order in candidates
                    if order.client_order_id == client_algo_id
                ),
                None,
            )
            if target is None:
                try:
                    target = await self.get_protection_order_by_client_id(
                        symbol=normalized_symbol,
                        client_id=client_algo_id,
                    )
                except ExchangeOrderNotFoundError:
                    target = None
        else:
            target = next(
                (order for order in candidates if order.stop_price == stop_loss),
                None,
            )

        if target is None:
            try:
                created = tuple(
                    await self.create_protection_orders(
                        symbol=normalized_symbol,
                        side=side,
                        quantity=quantity,
                        stop_loss=stop_loss,
                        stop_loss_client_algo_id=client_algo_id,
                    )
                )
            except ExchangeOrderOutcomeUnknownError:
                if client_algo_id is None:
                    raise
                target = await self._reconcile_stop_loss_order(
                    symbol=normalized_symbol,
                    side=side,
                    quantity=quantity,
                    stop_loss=stop_loss,
                    client_algo_id=client_algo_id,
                )
            else:
                if client_algo_id is not None:
                    target = next(
                        (
                            order
                            for order in created
                            if order.client_order_id == client_algo_id
                        ),
                        None,
                    )
                    if target is None:
                        target = await self._reconcile_stop_loss_order(
                            symbol=normalized_symbol,
                            side=side,
                            quantity=quantity,
                            stop_loss=stop_loss,
                            client_algo_id=client_algo_id,
                        )
                else:
                    target = next(
                        (
                            order
                            for order in created
                            if order.order_type is OrderType.STOP_MARKET
                            and order.stop_price == stop_loss
                        ),
                        None,
                    )

        if target is None:
            raise RuntimeError("Binance did not confirm the replacement stop-loss")

        self._validate_stop_loss_order(
            order=target,
            symbol=normalized_symbol,
            side=side,
            quantity=quantity,
            stop_loss=stop_loss,
            client_algo_id=client_algo_id,
        )

        if (
            previous_client_algo_id is not None
            and previous_client_algo_id != target.client_order_id
        ):
            await self._retire_stop_loss_predecessor(
                symbol=normalized_symbol,
                side=side,
                quantity=quantity,
                client_algo_id=previous_client_algo_id,
            )
        elif previous_client_algo_id is None:
            for order in candidates:
                if order.order_id == target.order_id:
                    continue
                await self._cancel_algo_order(
                    symbol=normalized_symbol,
                    order_id=order.order_id,
                )

        if client_algo_id is not None:
            return await self._reconcile_stop_loss_order(
                symbol=normalized_symbol,
                side=side,
                quantity=quantity,
                stop_loss=stop_loss,
                client_algo_id=client_algo_id,
            )

        remaining = await self.get_open_protection_orders(symbol=normalized_symbol)
        if not any(order.order_id == target.order_id for order in remaining):
            raise RuntimeError("Replacement stop-loss was not active after cleanup")
        return target

    async def _reconcile_stop_loss_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal,
        client_algo_id: str,
    ) -> Order:
        """Resolve a replacement solely through its exact client identity."""
        for attempt in range(_PROTECTION_RECONCILIATION_ATTEMPTS):
            try:
                order = await self.get_protection_order_by_client_id(
                    symbol=symbol,
                    client_id=client_algo_id,
                )
            except ExchangeOrderNotFoundError, ExchangeOrderOutcomeUnknownError:
                if attempt + 1 < _PROTECTION_RECONCILIATION_ATTEMPTS:
                    await asyncio.sleep(_PROTECTION_RECONCILIATION_DELAY_SECONDS)
                    continue
                break

            self._validate_stop_loss_order(
                order=order,
                symbol=symbol,
                side=side,
                quantity=quantity,
                stop_loss=stop_loss,
                client_algo_id=client_algo_id,
            )
            return order

        raise RuntimeError("Ambiguous replacement stop-loss remains unresolved")

    async def _retire_stop_loss_predecessor(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        client_algo_id: str,
    ) -> None:
        """Make one exact predecessor STOP provably inactive."""
        try:
            predecessor = await self.get_protection_order_by_client_id(
                symbol=symbol,
                client_id=client_algo_id,
            )
        except ExchangeOrderNotFoundError:
            return
        except ExchangeOrderOutcomeUnknownError as error:
            raise RuntimeError(
                "Replacement STOP predecessor could not be verified"
            ) from error

        self._validate_stop_loss_order(
            order=predecessor,
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_loss=None,
            client_algo_id=client_algo_id,
            require_active=False,
        )
        if predecessor.status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }:
            return
        if predecessor.status is not OrderStatus.NEW:
            raise RuntimeError(
                "Replacement STOP predecessor is neither active nor terminal"
            )

        ambiguous_error: ExchangeOrderOutcomeUnknownError | None = None
        try:
            await self.cancel_protection_order(
                symbol=symbol,
                client_id=client_algo_id,
            )
        except ExchangeOrderOutcomeUnknownError as error:
            ambiguous_error = error

        for attempt in range(_PROTECTION_RECONCILIATION_ATTEMPTS):
            try:
                remaining = await self.get_protection_order_by_client_id(
                    symbol=symbol,
                    client_id=client_algo_id,
                )
            except ExchangeOrderNotFoundError:
                return
            except ExchangeOrderOutcomeUnknownError:
                remaining = None

            if remaining is not None:
                self._validate_stop_loss_order(
                    order=remaining,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    stop_loss=None,
                    client_algo_id=client_algo_id,
                    require_active=False,
                )
                if remaining.status in {
                    OrderStatus.FILLED,
                    OrderStatus.CANCELED,
                    OrderStatus.REJECTED,
                    OrderStatus.EXPIRED,
                }:
                    return

            if attempt + 1 < _PROTECTION_RECONCILIATION_ATTEMPTS:
                await asyncio.sleep(_PROTECTION_RECONCILIATION_DELAY_SECONDS)

        if ambiguous_error is not None:
            raise RuntimeError(
                "Ambiguous replacement STOP predecessor cleanup remains unresolved"
            ) from ambiguous_error
        raise RuntimeError("Replacement STOP predecessor remains active")

    @staticmethod
    def _validate_stop_loss_order(
        *,
        order: Order,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal | None,
        client_algo_id: str | None,
        require_active: bool = True,
    ) -> None:
        """Validate exact shape of a current or replacement STOP."""
        if (
            order.symbol.upper() != symbol
            or order.side is not side
            or order.order_type is not OrderType.STOP_MARKET
            or order.quantity != quantity
            or order.stop_price is None
            or (client_algo_id is not None and order.client_order_id != client_algo_id)
            or (stop_loss is not None and order.stop_price != stop_loss)
            or (require_active and order.status is not OrderStatus.NEW)
        ):
            raise RuntimeError(
                "Binance STOP does not match the durable replacement identity"
            )

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return non-zero Futures positions."""
        params: RequestParams | None = None

        if symbol is not None:
            params = {"symbol": self._normalize_symbol(symbol)}

        payload = await self._rest.get(
            _POSITIONS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        raw_positions = (
            self._require_mapping(item) for item in self._require_sequence(payload)
        )
        return tuple(
            self._mapper.map_position(position)
            for position in raw_positions
            if Decimal(str(position.get("positionAmt", "0"))) != 0
        )

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
    ) -> Order:
        """Close one active one-way Futures position with a market order."""
        positions = await self.get_positions(symbol=symbol)

        if not positions:
            raise ValueError(f"No active Futures position for {symbol!r}")

        if len(positions) > 1:
            raise ValueError(
                "Hedge-mode positions require explicit position-side closing"
            )

        return await self._close_position(
            positions[0],
            client_order_id=client_order_id,
        )

    async def close_all_positions(self) -> Sequence[Order]:
        """Close all active one-way Futures positions."""
        positions = await self.get_positions()
        closed: list[Order] = []

        for position in positions:
            closed.append(await self._close_position(position))

        return tuple(closed)

    def _build_order_params(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None,
        client_order_id: str | None = None,
    ) -> RequestParams:
        """Build validated market or limit order parameters."""
        if quantity <= 0:
            raise ValueError("Order quantity must be greater than zero")

        params: RequestParams = {
            "symbol": self._normalize_symbol(symbol),
            "side": side.value,
            "type": order_type.value.upper(),
            "quantity": self._format_decimal(quantity),
        }
        if client_order_id is not None:
            params["newClientOrderId"] = self._normalize_client_order_id(
                client_order_id,
            )

        if order_type is OrderType.LIMIT:
            if price is None or price <= 0:
                raise ValueError("Futures LIMIT orders require a positive price")

            params["price"] = self._format_decimal(price)
            params["timeInForce"] = _DEFAULT_TIME_IN_FORCE
        elif price is not None:
            raise ValueError("Futures MARKET orders must not include a price")

        return params

    async def _post_order(
        self,
        *,
        params: RequestParams,
    ) -> Order:
        """Submit and map one authenticated Futures order."""
        try:
            payload = await self._rest.post(
                _ORDER_ENDPOINT,
                params=params,
                authenticated=True,
            )
        except BinanceRestResponseError as error:
            if (
                error.status == 400
                and error.code == _BINANCE_PERCENT_PRICE_REJECTED_CODE
            ):
                raise ExchangeOrderPriceBandRejectedError(
                    "Binance Futures rejected the order at the PERCENT_PRICE band"
                ) from error
            if error.status == 400 and error.code is not None:
                raise ExchangeOrderRejectedError(
                    "Binance Futures explicitly rejected the order"
                ) from error
            raise ExchangeOrderOutcomeUnknownError(
                "Binance Futures order outcome is unknown"
            ) from error
        except (aiohttp.ClientError, TimeoutError, RuntimeError) as error:
            raise ExchangeOrderOutcomeUnknownError(
                "Binance Futures entry outcome is unknown"
            ) from error
        return self._mapper.map_order(self._require_mapping(payload))

    @staticmethod
    def _normalize_client_order_id(client_order_id: str) -> str:
        """Validate the bounded vendor-compatible entry client identity."""
        normalized = client_order_id.strip()

        if not normalized:
            raise ValueError("Client order identifier must not be empty")

        if len(normalized) > _CLIENT_ORDER_ID_MAX_LENGTH:
            raise ValueError("Client order identifier exceeds Binance length limit")

        if not all(
            character.isalnum() or character in "-_" for character in normalized
        ):
            raise ValueError("Client order identifier contains invalid characters")

        return normalized

    async def _post_algo_order(
        self,
        *,
        params: RequestParams,
    ) -> Order:
        """Submit and map one authenticated Futures conditional algo order."""
        try:
            payload = await self._rest.post(
                _ALGO_ORDER_ENDPOINT,
                params=params,
                authenticated=True,
            )
        except BinanceRestResponseError as error:
            if error.code == _BINANCE_IMMEDIATE_TRIGGER_REJECTED_CODE:
                raise ExchangeOrderImmediateTriggerRejectedError(
                    "Binance Futures protection would trigger immediately"
                ) from error
            raise ExchangeOrderRejectedError(
                "Binance Futures protection order was rejected"
            ) from error
        except (aiohttp.ClientError, TimeoutError, RuntimeError) as error:
            raise ExchangeOrderOutcomeUnknownError(
                "Binance Futures protection outcome is unknown"
            ) from error
        return self._mapper.map_algo_order(self._require_mapping(payload))

    async def _cancel_algo_order(self, *, symbol: str, order_id: str) -> None:
        """Cancel one authenticated Futures algo order."""
        await self._rest.delete(
            _ALGO_ORDER_ENDPOINT,
            params={
                "symbol": self._normalize_symbol(symbol),
                "algoId": self._normalize_order_id(order_id),
            },
            authenticated=True,
        )

    @staticmethod
    def _matching_stop_orders(
        *,
        orders: Sequence[Order],
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
    ) -> tuple[Order, ...]:
        """Return exact-position stop orders eligible for replacement."""
        return tuple(
            order
            for order in orders
            if order.symbol.upper() == symbol
            and order.side is side
            and order.order_type is OrderType.STOP_MARKET
            and order.quantity == quantity
        )

    async def _close_position(
        self,
        position: Position,
        *,
        client_order_id: str | None = None,
    ) -> Order:
        """Submit a reduce-only market order for one position."""
        close_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        params: RequestParams = {
            "symbol": position.symbol,
            "side": close_side.value,
            "type": OrderType.MARKET.value.upper(),
            "quantity": self._format_decimal(position.quantity),
            "reduceOnly": "true",
        }
        if client_order_id is not None:
            params["newClientOrderId"] = self._normalize_client_order_id(
                client_order_id
            )
        return await self._post_order(params=params)
