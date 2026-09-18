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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Final, cast

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide, OrderStatus, OrderType, PositionSide
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base.mapper import ExchangePayload
from botragram.exchanges.bitget.client import BitgetClient
from botragram.exchanges.bitget.mapper import BitgetExchangeMapper
from botragram.exchanges.bitget.rest import BitgetRestClient, BitgetRestResponseError
from botragram.models import Order, Position

__all__ = [
    "BitgetFuturesExchangeClient",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_PRODUCT_TYPE: Final[str] = "USDT-FUTURES"
_MARGIN_COIN: Final[str] = "USDT"

_PLACE_ORDER_ENDPOINT: Final[str] = "/api/v2/mix/order/place-order"
_CANCEL_ORDER_ENDPOINT: Final[str] = "/api/v2/mix/order/cancel-order"
_CANCEL_ALL_ENDPOINT: Final[str] = "/api/v2/mix/order/cancel-all-orders"
_ORDER_DETAIL_ENDPOINT: Final[str] = "/api/v2/mix/order/detail"
_CURRENT_ORDERS_ENDPOINT: Final[str] = "/api/v2/mix/order/current-orders"

_PLACE_PLAN_ORDER_ENDPOINT: Final[str] = "/api/v2/mix/order/place-plan-order"
_CANCEL_PLAN_ORDER_ENDPOINT: Final[str] = "/api/v2/mix/order/cancel-plan-order"
_PLAN_PENDING_ENDPOINT: Final[str] = "/api/v2/mix/order/orders-plan-pending"

_ALL_POSITIONS_ENDPOINT: Final[str] = "/api/v2/mix/position/all-position"
_SET_LEVERAGE_ENDPOINT: Final[str] = "/api/v2/mix/account/set-leverage"


# =============================================================================
# Futures Client Implementation
# =============================================================================
class BitgetFuturesExchangeClient(BitgetClient):
    """Bitget USDT-M Futures exchange client."""

    __slots__ = ()

    def __init__(
        self,
        *,
        rest: BitgetRestClient,
        mapper: BitgetExchangeMapper,
    ) -> None:
        """Initialize the Bitget Futures client."""
        super().__init__(rest=rest, mapper=mapper)

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
    ) -> Order:
        """Create a new Bitget futures order."""
        normalized_symbol = symbol.strip().upper()
        bg_side = "buy" if side is OrderSide.BUY else "sell"
        bg_trade_side = "close" if reduce_only else "open"
        bg_type = "market" if order_type is OrderType.MARKET else "limit"

        data: dict[str, object] = {
            "productType": _PRODUCT_TYPE,
            "symbol": normalized_symbol,
            "marginMode": "crossed",
            "marginCoin": _MARGIN_COIN,
            "size": str(quantity),
            "side": bg_side,
            "tradeSide": bg_trade_side,
            "orderType": bg_type,
        }
        if price is not None and bg_type == "limit":
            data["price"] = str(price)
        if client_order_id:
            data["clientOid"] = client_order_id

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
                return await self.get_order(symbol=normalized_symbol, order_id=order_id)
            except Exception:
                pass

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
        orders: list[Order] = []
        bg_side = "buy" if side is OrderSide.BUY else "sell"

        # Stop loss
        if stop_loss is not None:
            sl_data: dict[str, object] = {
                "productType": _PRODUCT_TYPE,
                "symbol": normalized_symbol,
                "marginCoin": _MARGIN_COIN,
                "planType": "pos_loss",
                "triggerPrice": str(stop_loss),
                "triggerType": "mark_price",
                "executePrice": "0",
                "size": str(quantity),
                "side": bg_side,
                "tradeSide": "close",
                "orderType": "market",
            }
            if stop_loss_client_algo_id:
                sl_data["clientOid"] = stop_loss_client_algo_id

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

        # Take profit
        if take_profit is not None:
            tp_data: dict[str, object] = {
                "productType": _PRODUCT_TYPE,
                "symbol": normalized_symbol,
                "marginCoin": _MARGIN_COIN,
                "planType": "pos_profit",
                "triggerPrice": str(take_profit),
                "triggerType": "mark_price",
                "executePrice": "0",
                "size": str(quantity),
                "side": bg_side,
                "tradeSide": "close",
                "orderType": "market",
            }
            if take_profit_client_algo_id:
                tp_data["clientOid"] = take_profit_client_algo_id

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
            "productType": _PRODUCT_TYPE,
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
        except Exception:
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

        data: dict[str, object] = {
            "productType": _PRODUCT_TYPE,
            "marginCoin": _MARGIN_COIN,
        }
        if symbol is not None:
            data["symbol"] = symbol.strip().upper()

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
        payload = await self._rest.get(
            _ORDER_DETAIL_ENDPOINT,
            params={
                "productType": _PRODUCT_TYPE,
                "symbol": normalized_symbol,
                "orderId": order_id,
            },
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_order(cast(ExchangePayload, raw_data))

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
        payload = await self._rest.get(
            _ORDER_DETAIL_ENDPOINT,
            params={
                "productType": _PRODUCT_TYPE,
                "symbol": normalized_symbol,
                "clientOid": client_order_id,
            },
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_order(cast(ExchangePayload, raw_data))

        raise ExchangeOrderNotFoundError(
            f"Order with clientOid {client_order_id!r} not found for symbol {symbol!r}"
        )

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open standard orders."""
        params: dict[str, str] = {"productType": _PRODUCT_TYPE}
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
            raw_list: list[object]
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("entrustedList")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)
            else:
                raw_list = []

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
        params: dict[str, str] = {"productType": _PRODUCT_TYPE}
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
            raw_list: list[object]
            if isinstance(raw_data, dict):
                ent_list = cast(dict[str, object], raw_data).get("entrustedList")
                raw_list = (
                    cast(list[object], ent_list) if isinstance(ent_list, list) else []
                )
            elif isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)
            else:
                raw_list = []

            for item in raw_list:
                if isinstance(item, dict):
                    orders.append(self._mapper.map_order(cast(ExchangePayload, item)))

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

        raise ExchangeOrderNotFoundError(
            f"Protection order with client_id {client_id!r} not found "
            f"for symbol {symbol!r}"
        )

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> None:
        """Cancel conditional plan order by client_id."""
        normalized_symbol = symbol.strip().upper()
        data: dict[str, object] = {
            "productType": _PRODUCT_TYPE,
            "symbol": normalized_symbol,
            "marginCoin": _MARGIN_COIN,
            "clientOid": client_id,
        }
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
            "productType": _PRODUCT_TYPE,
            "marginCoin": _MARGIN_COIN,
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
            if isinstance(raw_data, list):
                for item in cast(list[object], raw_data):
                    if not isinstance(item, dict):
                        continue
                    pos = self._mapper.map_position(cast(ExchangePayload, item))
                    if pos.quantity > Decimal("0"):
                        positions.append(pos)

        return tuple(positions)

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
    ) -> Order:
        """Close an active position using market order."""
        positions = await self.get_positions(symbol=symbol)
        if not positions:
            raise ExchangeOrderNotFoundError(
                f"No open position found to close for {symbol!r}"
            )

        pos = positions[0]
        close_side = OrderSide.SELL if pos.side is PositionSide.LONG else OrderSide.BUY

        return await self.create_order(
            symbol=symbol,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=pos.quantity,
            client_order_id=client_order_id,
            reduce_only=True,
        )

    async def close_all_positions(self) -> Sequence[Order]:
        """Close all open positions."""
        positions = await self.get_positions()
        orders: list[Order] = []
        for pos in positions:
            order = await self.close_position(symbol=pos.symbol)
            orders.append(order)
        return tuple(orders)

    async def set_leverage(
        self,
        *,
        symbol: str,
        leverage: int,
        hold_side: str = "long",
    ) -> None:
        """Set leverage for symbol."""
        data: dict[str, object] = {
            "productType": _PRODUCT_TYPE,
            "symbol": symbol.strip().upper(),
            "marginCoin": _MARGIN_COIN,
            "leverage": str(leverage),
            "holdSide": hold_side,
        }
        await self._rest.post(
            _SET_LEVERAGE_ENDPOINT,
            data=data,
            authenticated=True,
        )

    async def verify_mainnet_readiness(self) -> None:
        """Verify API key connectivity and futures account access."""
        await self.get_account()
