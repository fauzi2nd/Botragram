"""
Botragram

Description:
    Bitget Futures exchange client implementing USDT-M futures trading.

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
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final, cast

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    MarginMode,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exceptions import (
    ExchangeError,
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base.mapper import ExchangePayload
from botragram.exchanges.bitget.client import BitgetClient
from botragram.exchanges.bitget.mapper import BitgetExchangeMapper
from botragram.exchanges.bitget.rest import BitgetRestClient, BitgetRestResponseError
from botragram.models import Order, Position, Trade

__all__ = [
    "BitgetFuturesExchangeClient",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_CATEGORY: Final[str] = "USDT-FUTURES"
_MARGIN_COIN: Final[str] = "USDT"

_PLACE_ORDER_ENDPOINT: Final[str] = "/api/v3/trade/place-order"
_CANCEL_ORDER_ENDPOINT: Final[str] = "/api/v3/trade/cancel-order"
_CANCEL_ALL_ENDPOINT: Final[str] = "/api/v3/trade/cancel-symbol-order"
_ORDER_DETAIL_ENDPOINT: Final[str] = "/api/v3/trade/order-info"
_CURRENT_ORDERS_ENDPOINT: Final[str] = "/api/v3/trade/unfilled-orders"
_FILLS_ENDPOINT: Final[str] = "/api/v3/trade/fills"

_PLACE_PLAN_ORDER_ENDPOINT: Final[str] = "/api/v3/trade/place-strategy-order"
_CANCEL_PLAN_ORDER_ENDPOINT: Final[str] = "/api/v3/trade/cancel-strategy-order"
_PLAN_PENDING_ENDPOINT: Final[str] = "/api/v3/trade/unfilled-strategy-orders"
_PLAN_HISTORY_ENDPOINT: Final[str] = "/api/v3/trade/history-strategy-orders"

_ALL_POSITIONS_ENDPOINT: Final[str] = "/api/v3/position/current-position"
_SET_LEVERAGE_ENDPOINT: Final[str] = "/api/v3/account/set-leverage"
_ACCOUNT_SETTINGS_ENDPOINT: Final[str] = "/api/v3/account/settings"
_CONTRACTS_ENDPOINT: Final[str] = "/api/v2/mix/market/contracts"
_PRODUCT_TYPE: Final[str] = "usdt-futures"


# =============================================================================
# Futures Client Implementation
# =============================================================================
class BitgetFuturesExchangeClient(BitgetClient):
    """Bitget USDT-M Futures exchange client."""

    __slots__ = ("_hold_mode", "_margin_mode")

    def __init__(
        self,
        *,
        rest: BitgetRestClient,
        mapper: BitgetExchangeMapper,
        margin_mode: MarginMode | str = MarginMode.ISOLATED,
    ) -> None:
        """Initialize the Bitget Futures client."""
        super().__init__(rest=rest, mapper=mapper)
        self._hold_mode: str | None = None
        self._margin_mode: str = (
            margin_mode.value
            if isinstance(margin_mode, MarginMode)
            else margin_mode.strip().lower()
        )

    async def get_margin_mode(self) -> str:
        """Return the configured futures margin mode (isolated or crossed)."""
        return self._margin_mode

    async def get_hold_mode(self) -> str:
        """Return the account position hold mode (hedge_mode or one_way_mode)."""
        if self._hold_mode is None:
            try:
                payload = await self._rest.get(
                    _ACCOUNT_SETTINGS_ENDPOINT,
                    authenticated=True,
                )
                if isinstance(payload, dict):
                    raw_data = payload.get("data")
                    if isinstance(raw_data, dict):
                        data_dict = cast(ExchangePayload, raw_data)
                        self._hold_mode = str(data_dict.get("holdMode", "hedge_mode"))
            except Exception as error:
                _LOGGER.warning(
                    "Failed to fetch Bitget account settings for hold mode: %s; "
                    "defaulting to hedge_mode",
                    error,
                )
                self._hold_mode = "hedge_mode"
        return self._hold_mode or "hedge_mode"

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
        reduce_only: bool = False,
        pos_side: str | None = None,
    ) -> Order:
        """Create a new Bitget futures order."""
        normalized_symbol = symbol.strip().upper()
        bg_side = "buy" if side is OrderSide.BUY else "sell"
        bg_type = "market" if order_type is OrderType.MARKET else "limit"

        hold_mode = await self.get_hold_mode()
        margin_mode = await self.get_margin_mode()

        data: dict[str, object] = {
            "category": _CATEGORY,
            "symbol": normalized_symbol,
            "side": bg_side,
            "orderType": bg_type,
            "qty": str(quantity),
            "marginMode": margin_mode,
        }
        if price is not None and bg_type == "limit":
            data["price"] = str(price)
        if client_order_id:
            data["clientOid"] = client_order_id

        if hold_mode == "hedge_mode":
            # In hedge mode, posSide is mandatory on Bitget UTA.
            # When opening: BUY -> long, SELL -> short
            # When closing (reduce_only): SELL -> long, BUY -> short
            if pos_side is not None:
                data["posSide"] = pos_side
            elif not reduce_only:
                data["posSide"] = "long" if side is OrderSide.BUY else "short"
            else:
                data["posSide"] = "long" if side is OrderSide.SELL else "short"
        else:
            # In one-way mode, posSide is omitted and reduceOnly is used for reductions.
            if reduce_only:
                data["reduceOnly"] = "YES"

        try:
            payload = await self._rest.post(
                _PLACE_ORDER_ENDPOINT,
                data=data,
                authenticated=True,
            )
        except BitgetRestResponseError as error:
            raise ExchangeOrderRejectedError(
                f"Bitget explicitly rejected the order: {error}"
            ) from error
        except (TimeoutError, RuntimeError) as error:
            raise ExchangeOrderOutcomeUnknownError(
                f"Bitget order outcome is unknown: {error}"
            ) from error

        order_id = ""
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                data_dict = cast(ExchangePayload, raw_data)
                order_id = str(data_dict.get("orderId", ""))

        if order_id:
            try:
                order = await self.get_order(
                    symbol=normalized_symbol, order_id=order_id
                )
                if client_order_id and not order.client_order_id:
                    return replace(order, client_order_id=client_order_id)
                return order
            except (
                ExchangeError,
                ExchangeOrderNotFoundError,
                BitgetRestResponseError,
            ) as error:
                _LOGGER.debug(
                    "Immediate Bitget get_order for %s (%s) not available: %s",
                    order_id,
                    normalized_symbol,
                    error,
                )

        now = datetime.now(timezone.utc)
        return Order(
            order_id=order_id or "bitget-submitted",
            symbol=normalized_symbol,
            side=side,
            order_type=order_type,
            status=OrderStatus.NEW,
            quantity=quantity,
            executed_quantity=Decimal("0"),
            price=price,
            client_order_id=client_order_id,
            created_at=now,
            updated_at=now,
        )

    async def create_reduce_only_market_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        client_order_id: str | None = None,
    ) -> Order:
        """Create a reduce-only market order for Futures position reduction."""
        if quantity <= 0:
            raise ValueError("Order quantity must be greater than zero")

        return await self.create_order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            client_order_id=client_order_id,
            reduce_only=True,
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
        """Create conditional stop-loss and take-profit plan orders for a position."""
        normalized_symbol = symbol.strip().upper()
        pos_side = "long" if side is OrderSide.SELL else "short"
        margin_mode = await self.get_margin_mode()

        # Case 1: Both legs requested — submit atomically in one TPSL request
        if stop_loss is not None and take_profit is not None:
            data: dict[str, object] = {
                "category": _CATEGORY,
                "symbol": normalized_symbol,
                "type": "tpsl",
                "posSide": pos_side,
                "size": str(quantity),
                "stopLoss": str(stop_loss),
                "takeProfit": str(take_profit),
                "marginMode": margin_mode,
            }
            if stop_loss_client_algo_id:
                data["clientOid"] = stop_loss_client_algo_id
            elif take_profit_client_algo_id:
                data["clientOid"] = take_profit_client_algo_id

            try:
                resp = await self._rest.post(
                    _PLACE_PLAN_ORDER_ENDPOINT,
                    data=data,
                    authenticated=True,
                )
            except BitgetRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bitget protection orders rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bitget protection orders outcome unknown: {error}"
                ) from error

            order_id = ""
            if isinstance(resp, dict):
                raw_data = resp.get("data")
                if isinstance(raw_data, dict):
                    data_dict = cast(ExchangePayload, raw_data)
                    order_id = str(data_dict.get("orderId", ""))

            now = datetime.now(timezone.utc)
            return (
                Order(
                    order_id=f"{order_id}-sl" if order_id else "bitget-sl",
                    symbol=normalized_symbol,
                    side=side,
                    order_type=OrderType.STOP_MARKET,
                    status=OrderStatus.NEW,
                    quantity=quantity,
                    executed_quantity=Decimal("0"),
                    stop_price=stop_loss,
                    client_order_id=stop_loss_client_algo_id,
                    created_at=now,
                    updated_at=now,
                ),
                Order(
                    order_id=f"{order_id}-tp" if order_id else "bitget-tp",
                    symbol=normalized_symbol,
                    side=side,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    status=OrderStatus.NEW,
                    quantity=quantity,
                    executed_quantity=Decimal("0"),
                    stop_price=take_profit,
                    client_order_id=take_profit_client_algo_id,
                    created_at=now,
                    updated_at=now,
                ),
            )

        orders: list[Order] = []

        # Case 2: Only stop loss requested
        if stop_loss is not None:
            sl_data: dict[str, object] = {
                "category": _CATEGORY,
                "symbol": normalized_symbol,
                "type": "tpsl",
                "posSide": pos_side,
                "size": str(quantity),
                "stopLoss": str(stop_loss),
                "marginMode": margin_mode,
            }
            if stop_loss_client_algo_id:
                sl_data["clientOid"] = stop_loss_client_algo_id

            try:
                open_orders = await self.get_open_protection_orders(
                    symbol=normalized_symbol
                )
            except (TimeoutError, ConnectionError, RuntimeError) as error:
                raise ExchangeError(
                    "Bitget network failure while querying "
                    f"existing protection orders: {error}"
                ) from error

            existing_tp = next(
                (
                    o
                    for o in open_orders
                    if o.order_type
                    in (OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT)
                    and o.status is OrderStatus.NEW
                    and o.side is side
                    and o.stop_price is not None
                ),
                None,
            )
            if existing_tp is not None and existing_tp.stop_price is not None:
                sl_data["takeProfit"] = str(existing_tp.stop_price)

            try:
                resp = await self._rest.post(
                    _PLACE_PLAN_ORDER_ENDPOINT,
                    data=sl_data,
                    authenticated=True,
                )
            except BitgetRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bitget stop-loss was rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bitget stop-loss outcome is unknown: {error}"
                ) from error

            order_id = ""
            if isinstance(resp, dict):
                raw_data = resp.get("data")
                if isinstance(raw_data, dict):
                    data_dict = cast(ExchangePayload, raw_data)
                    order_id = str(data_dict.get("orderId", ""))

            now = datetime.now(timezone.utc)
            orders.append(
                Order(
                    order_id=order_id or "bitget-sl",
                    symbol=normalized_symbol,
                    side=side,
                    order_type=OrderType.STOP_MARKET,
                    status=OrderStatus.NEW,
                    quantity=quantity,
                    executed_quantity=Decimal("0"),
                    stop_price=stop_loss,
                    client_order_id=stop_loss_client_algo_id,
                    created_at=now,
                    updated_at=now,
                )
            )

        # Case 3: Only take profit requested
        if take_profit is not None:
            tp_data: dict[str, object] = {
                "category": _CATEGORY,
                "symbol": normalized_symbol,
                "type": "tpsl",
                "posSide": pos_side,
                "size": str(quantity),
                "takeProfit": str(take_profit),
                "marginMode": margin_mode,
            }
            if take_profit_client_algo_id:
                tp_data["clientOid"] = take_profit_client_algo_id

            try:
                open_orders = await self.get_open_protection_orders(
                    symbol=normalized_symbol
                )
            except (TimeoutError, ConnectionError, RuntimeError) as error:
                raise ExchangeError(
                    "Bitget network failure while querying "
                    f"existing protection orders: {error}"
                ) from error

            existing_sl = next(
                (
                    o
                    for o in open_orders
                    if o.order_type in (OrderType.STOP_MARKET, OrderType.STOP)
                    and o.status is OrderStatus.NEW
                    and o.side is side
                    and o.stop_price is not None
                ),
                None,
            )
            if existing_sl is not None and existing_sl.stop_price is not None:
                tp_data["stopLoss"] = str(existing_sl.stop_price)

            try:
                resp = await self._rest.post(
                    _PLACE_PLAN_ORDER_ENDPOINT,
                    data=tp_data,
                    authenticated=True,
                )
            except BitgetRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bitget take-profit was rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bitget take-profit outcome is unknown: {error}"
                ) from error

            order_id = ""
            if isinstance(resp, dict):
                raw_data = resp.get("data")
                if isinstance(raw_data, dict):
                    tp_dict = cast(ExchangePayload, raw_data)
                    order_id = str(tp_dict.get("orderId", ""))

            now = datetime.now(timezone.utc)
            orders.append(
                Order(
                    order_id=order_id or "bitget-tp",
                    symbol=normalized_symbol,
                    side=side,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    status=OrderStatus.NEW,
                    quantity=quantity,
                    executed_quantity=Decimal("0"),
                    stop_price=take_profit,
                    client_order_id=take_profit_client_algo_id,
                    created_at=now,
                    updated_at=now,
                )
            )

        return tuple(orders)

    async def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Cancel an open order."""
        normalized_symbol = symbol.strip().upper()
        data: dict[str, object] = {
            "category": _CATEGORY,
            "symbol": normalized_symbol,
            "orderId": order_id,
        }
        await self._rest.post(
            _CANCEL_ORDER_ENDPOINT,
            data=data,
            authenticated=True,
        )
        try:
            return await self.get_order(symbol=normalized_symbol, order_id=order_id)
        except (
            ExchangeError,
            ExchangeOrderNotFoundError,
            BitgetRestResponseError,
        ) as error:
            _LOGGER.debug(
                "Order %s (%s) fetch after cancel failed: %s; returning canceled order",
                order_id,
                normalized_symbol,
                error,
            )
            now = datetime.now(timezone.utc)
            return Order(
                order_id=order_id,
                symbol=normalized_symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                status=OrderStatus.CANCELED,
                quantity=Decimal("0"),
                executed_quantity=Decimal("0"),
                created_at=now,
                updated_at=now,
            )

    async def cancel_all_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Cancel all open orders."""
        open_orders = await self.get_open_orders(symbol=symbol)
        if not open_orders:
            return ()

        symbols_to_cancel: set[str] = (
            {symbol.strip().upper()}
            if symbol is not None
            else {o.symbol for o in open_orders}
        )
        for sym in symbols_to_cancel:
            data: dict[str, object] = {
                "category": _CATEGORY,
                "symbol": sym,
            }
            await self._rest.post(
                _CANCEL_ALL_ENDPOINT,
                data=data,
                authenticated=True,
            )
        return open_orders

    async def get_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Return order by order_id."""
        normalized_symbol = symbol.strip().upper()
        try:
            payload = await self._rest.get(
                _ORDER_DETAIL_ENDPOINT,
                params={
                    "category": _CATEGORY,
                    "symbol": normalized_symbol,
                    "orderId": order_id,
                },
                authenticated=True,
            )
        except BitgetRestResponseError as error:
            if (
                error.code in ("25204", "40004", "40404")
                or "not exist" in error.message.lower()
                or error.http_status == 404
            ):
                raise ExchangeOrderNotFoundError(
                    f"Order {order_id!r} not found for symbol {symbol!r}"
                ) from error
            raise

        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_order(cast(ExchangePayload, raw_data))
            elif isinstance(raw_data, list) and raw_data:
                first = cast(list[object], raw_data)[0]
                if isinstance(first, dict):
                    return self._mapper.map_order(cast(ExchangePayload, first))

        raise ExchangeOrderNotFoundError(
            f"Order {order_id!r} not found for symbol {symbol!r}"
        )

    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Return order by client_order_id."""
        normalized_symbol = symbol.strip().upper()
        try:
            payload = await self._rest.get(
                _ORDER_DETAIL_ENDPOINT,
                params={
                    "category": _CATEGORY,
                    "symbol": normalized_symbol,
                    "clientOid": client_order_id,
                },
                authenticated=True,
            )
        except BitgetRestResponseError as error:
            if (
                error.code in ("25204", "40004", "40404")
                or "not exist" in error.message.lower()
                or error.http_status == 404
            ):
                raise ExchangeOrderNotFoundError(
                    f"Order with clientOid {client_order_id!r} not found for "
                    f"symbol {symbol!r}"
                ) from error
            raise

        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_order(cast(ExchangePayload, raw_data))
            elif isinstance(raw_data, list) and raw_data:
                first = cast(list[object], raw_data)[0]
                if isinstance(first, dict):
                    return self._mapper.map_order(cast(ExchangePayload, first))

        raise ExchangeOrderNotFoundError(
            f"Order with clientOid {client_order_id!r} not found for symbol {symbol!r}"
        )

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open standard orders."""
        params: dict[str, str] = {"category": _CATEGORY}
        if symbol is not None:
            params["symbol"] = symbol.strip().upper()

        payload = await self._rest.get(
            _CURRENT_ORDERS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("list")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)

            for item in raw_list:
                if isinstance(item, dict):
                    orders.append(self._mapper.map_order(cast(ExchangePayload, item)))

        return tuple(orders)

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open conditional/plan protection orders."""
        params: dict[str, str] = {"category": _CATEGORY}
        if symbol is not None:
            params["symbol"] = symbol.strip().upper()

        payload = await self._rest.get(
            _PLAN_PENDING_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("list")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)

            for item in raw_list:
                if isinstance(item, dict):
                    orders.extend(
                        self._mapper.map_protection_orders(cast(ExchangePayload, item))
                    )

        return tuple(orders)

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Find pending plan order by client_id."""
        orders = await self.get_open_protection_orders(symbol=symbol)
        for order in orders:
            if order.client_order_id == client_id:
                return order
            if client_id.startswith("adopted-"):
                raw_id = client_id.removeprefix("adopted-")
                clean_raw_id = (
                    raw_id[:-3] if raw_id.endswith(("-tp", "-sl")) else raw_id
                )
                clean_order_id = (
                    order.order_id[:-3]
                    if order.order_id.endswith(("-tp", "-sl"))
                    else order.order_id
                )
                if (
                    order.order_id == raw_id
                    or clean_order_id == clean_raw_id
                    or f"adopted-{order.order_id}" == client_id
                ):
                    return replace(order, client_order_id=client_id)

        # Handle Bitget combined TPSL orders where the venue stores only one clientOid.
        # If client_id is a TAKE_PROFIT leg (e.g. btp-...) and the venue record only
        # retained the stop loss clientOid, associate the unmapped TP leg:
        if client_id.startswith("btp-"):
            for order in orders:
                if order.order_type in (
                    OrderType.TAKE_PROFIT_MARKET,
                    OrderType.TAKE_PROFIT,
                ) and (order.client_order_id is None or order.order_id.endswith("-tp")):
                    return replace(order, client_order_id=client_id)

        # Reciprocally, if client_id is a STOP_LOSS leg (e.g. bsl-...) and the venue
        # record only retained the take profit clientOid, associate the unmapped SL leg:
        if client_id.startswith("bsl-"):
            for order in orders:
                if order.order_type in (
                    OrderType.STOP_MARKET,
                    OrderType.STOP,
                ) and (order.client_order_id is None or order.order_id.endswith("-sl")):
                    return replace(order, client_order_id=client_id)

        raise ExchangeOrderNotFoundError(
            f"Protection order with client_id {client_id!r} not found "
            f"for symbol {symbol!r}"
        )

    async def get_protection_order_history(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> Sequence[Order]:
        """Return conditional protection order history for one symbol."""
        start_ms = int(start_time.timestamp() * 1000)
        params: dict[str, str | int] = {
            "category": _CATEGORY,
            "symbol": symbol.strip().upper(),
            "startTime": start_ms,
            "limit": 100,
        }
        if end_time is not None:
            params["endTime"] = int(end_time.timestamp() * 1000)

        payload = await self._rest.get(
            _PLAN_HISTORY_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("list")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)

            for item in raw_list:
                if isinstance(item, dict):
                    orders.extend(
                        self._mapper.map_protection_orders(cast(ExchangePayload, item))
                    )

        return tuple(orders)

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str | None = None,
        order_id: str | None = None,
    ) -> None:
        """Cancel conditional plan order by order_id or client_id."""
        if client_id is None and order_id is None:
            raise ValueError(
                "Either client_id or order_id must be provided to cancel "
                "protection order"
            )
        normalized_symbol = symbol.strip().upper()
        data: dict[str, object] = {
            "category": _CATEGORY,
            "symbol": normalized_symbol,
        }
        if order_id is not None:
            clean_id = order_id[:-3] if order_id.endswith(("-tp", "-sl")) else order_id
            data["orderId"] = clean_id
        elif client_id is not None and client_id.startswith("adopted-"):
            raw_id = client_id.removeprefix("adopted-")
            order_id_from_client = (
                raw_id[:-3] if raw_id.endswith(("-tp", "-sl")) else raw_id
            )
            data["orderId"] = order_id_from_client
        elif client_id is not None:
            resolved_order_id: str | None = None
            try:
                matched_order = await self.get_protection_order_by_client_id(
                    symbol=normalized_symbol,
                    client_id=client_id,
                )
                clean_id = (
                    matched_order.order_id[:-3]
                    if matched_order.order_id.endswith(("-tp", "-sl"))
                    else matched_order.order_id
                )
                if clean_id and not clean_id.startswith("bitget-"):
                    resolved_order_id = clean_id
            except Exception:
                resolved_order_id = None

            if resolved_order_id is not None:
                data["orderId"] = resolved_order_id
            else:
                data["clientOid"] = client_id
        try:
            await self._rest.post(
                _CANCEL_PLAN_ORDER_ENDPOINT,
                data=data,
                authenticated=True,
            )
        except Exception as error:
            _LOGGER.warning(
                "Failed to cancel protection order %s on Bitget: %s",
                client_id,
                error,
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
        """Replace or ensure a stop-loss plan order."""
        if previous_client_algo_id:
            await self.cancel_protection_order(
                symbol=symbol,
                client_id=previous_client_algo_id,
            )

        orders = await self.create_protection_orders(
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_loss=stop_loss,
            stop_loss_client_algo_id=client_algo_id,
        )
        if not orders:
            raise ExchangeOrderRejectedError(
                f"Failed to place stop loss order for {symbol} at {stop_loss}"
            )
        return orders[0]

    # =========================================================================
    # Positions
    # =========================================================================

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return open positions."""
        params: dict[str, str] = {
            "category": _CATEGORY,
        }
        if symbol is not None:
            params["symbol"] = symbol.strip().upper()

        payload = await self._rest.get(
            _ALL_POSITIONS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        positions: list[Position] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("list")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)

            seen_symbols: set[str] = set()
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                pos = self._mapper.map_position(cast(ExchangePayload, item))
                if pos.quantity > Decimal("0"):
                    if pos.symbol in seen_symbols:
                        _LOGGER.critical(
                            "Bitget returned multiple positions for symbol %s in "
                            "hedge mode; Botragram invariant requires One-Way Mode",
                            pos.symbol,
                        )
                    seen_symbols.add(pos.symbol)
                    positions.append(pos)

        return tuple(positions)

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
        side: PositionSide | None = None,
    ) -> Order:
        """Close an active position using market order."""
        positions = await self.get_positions(symbol=symbol)
        if not positions:
            raise ExchangeOrderNotFoundError(
                f"No open position found to close for {symbol!r}"
            )

        if side is not None:
            matching = [p for p in positions if p.side is side]
            if not matching:
                raise ExchangeOrderNotFoundError(
                    f"No open {side.value} position found to close for {symbol!r}"
                )
            pos = matching[0]
        elif len(positions) == 1:
            pos = positions[0]
        else:
            raise RuntimeError(
                f"Multiple open positions found for {symbol!r}; specify side to close"
            )

        close_side = OrderSide.SELL if pos.side is PositionSide.LONG else OrderSide.BUY
        pos_side = "long" if pos.side is PositionSide.LONG else "short"

        return await self.create_order(
            symbol=symbol,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=pos.quantity,
            client_order_id=client_order_id,
            reduce_only=True,
            pos_side=pos_side,
        )

    async def close_position_exact(
        self,
        *,
        position: Position,
        client_order_id: str,
    ) -> Order:
        """Submit one reduce-only close from an authoritative snapshot."""
        normalized_symbol = position.symbol.strip().upper()
        close_side = (
            OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY
        )
        pos_side = "long" if position.side is PositionSide.LONG else "short"
        return await self.create_order(
            symbol=normalized_symbol,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=position.quantity,
            client_order_id=client_order_id,
            reduce_only=True,
            pos_side=pos_side,
        )

    async def close_all_positions(self) -> Sequence[Order]:
        """Close all open positions."""
        positions = await self.get_positions()
        orders: list[Order] = []
        for pos in positions:
            order = await self.close_position(symbol=pos.symbol, side=pos.side)
            orders.append(order)
        return tuple(orders)

    async def set_leverage(
        self,
        *,
        symbol: str,
        leverage: int,
        hold_side: str = "long",
        margin_mode: str | None = None,
    ) -> None:
        """Set leverage for symbol."""
        effective_margin_mode = margin_mode or await self.get_margin_mode()
        data: dict[str, object] = {
            "category": _CATEGORY,
            "symbol": symbol.strip().upper(),
            "leverage": str(leverage),
            "posSide": hold_side,
            "marginMode": effective_margin_mode,
        }
        await self._rest.post(
            _SET_LEVERAGE_ENDPOINT,
            data=data,
            authenticated=True,
        )

    async def verify_mainnet_readiness(self) -> None:
        """Verify API key connectivity and futures account access."""
        await self.get_account()

    async def verify_mainnet_symbol_readiness(
        self,
        *,
        symbol: str,
        maximum_leverage: int,
        entry_notional: Decimal,
    ) -> None:
        """Fail closed unless one symbol is safe for a MAINNET entry."""
        del entry_notional
        if isinstance(maximum_leverage, bool) or maximum_leverage <= 0:
            raise ValueError("Maximum leverage must be greater than zero")

        normalized_symbol = symbol.strip().upper()
        payload = await self._rest.get(
            _CONTRACTS_ENDPOINT,
            params={"productType": _PRODUCT_TYPE, "symbol": normalized_symbol},
            authenticated=False,
        )
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid contracts response for {normalized_symbol!r}")

        raw_data = payload.get("data")
        if not isinstance(raw_data, list) or not raw_data:
            raise ValueError(f"No contract rules found for {normalized_symbol!r}")

        first = cast(list[object], raw_data)[0]
        if not isinstance(first, dict):
            raise ValueError(f"Invalid contract data for {normalized_symbol!r}")

        first_map = cast(ExchangePayload, first)
        self._mapper.map_symbol_rules(first_map)

        max_allowed_leverage = maximum_leverage
        raw_max = first_map.get("maxLever")
        if raw_max is not None and str(raw_max).strip() != "":
            try:
                max_allowed_leverage = int(float(str(raw_max)))
            except ValueError, TypeError:
                max_allowed_leverage = maximum_leverage

        target_leverage = max(1, min(maximum_leverage, max_allowed_leverage))
        hold_mode = await self.get_hold_mode()
        margin_mode = await self.get_margin_mode()
        if hold_mode == "hedge_mode":
            await self.set_leverage(
                symbol=normalized_symbol,
                leverage=target_leverage,
                hold_side="long",
                margin_mode=margin_mode,
            )
            await self.set_leverage(
                symbol=normalized_symbol,
                leverage=target_leverage,
                hold_side="short",
                margin_mode=margin_mode,
            )
        else:
            await self.set_leverage(
                symbol=normalized_symbol,
                leverage=target_leverage,
                hold_side="long",
                margin_mode=margin_mode,
            )

        _LOGGER.info(
            "Bitget symbol leverage verified and aligned: symbol=%s leverage=%dx "
            "(maximum_allowed=%dx requested=%dx hold_mode=%s margin_mode=%s)",
            normalized_symbol,
            target_leverage,
            max_allowed_leverage,
            maximum_leverage,
            hold_mode,
            margin_mode,
        )

    async def get_trades_for_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Sequence[Trade]:
        """Return every fill for one exact Futures order identity."""
        normalized_symbol = symbol.strip().upper()
        normalized_order_id = order_id.strip()
        params: dict[str, str | int] = {
            "category": _CATEGORY,
            "symbol": normalized_symbol,
            "orderId": normalized_order_id,
            "limit": 100,
        }
        payload = await self._rest.get(
            _FILLS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        trades: list[Trade] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            raw_list: list[object] = []
            if isinstance(raw_data, dict):
                data_dict = cast(dict[str, object], raw_data)
                ent_list = data_dict.get("list") or data_dict.get("fillList")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)

            for item in raw_list:
                if isinstance(item, dict):
                    trade = self._mapper.map_trade(cast(ExchangePayload, item))
                    if trade.order_id == normalized_order_id:
                        trades.append(trade)

        return tuple(trades)
