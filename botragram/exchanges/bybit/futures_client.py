"""
Botragram

Description:
    Bybit Futures exchange client implementing linear perpetual trading.

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
from botragram.enums import OrderSide, OrderStatus, OrderType, PositionSide
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base.mapper import ExchangePayload
from botragram.exchanges.bybit.client import BybitExchangeClient
from botragram.exchanges.bybit.mapper import BybitExchangeMapper
from botragram.exchanges.bybit.rest import BybitRestClient, BybitRestResponseError
from botragram.models import Order, Position, Trade

__all__ = [
    "BybitFuturesExchangeClient",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_ORDER_CREATE_ENDPOINT: Final[str] = "/v5/order/create"
_ORDER_CANCEL_ENDPOINT: Final[str] = "/v5/order/cancel"
_ORDER_CANCEL_ALL_ENDPOINT: Final[str] = "/v5/order/cancel-all"
_ORDER_REALTIME_ENDPOINT: Final[str] = "/v5/order/realtime"
_POSITION_LIST_ENDPOINT: Final[str] = "/v5/position/list"
_SET_LEVERAGE_ENDPOINT: Final[str] = "/v5/position/set-leverage"
_EXECUTION_LIST_ENDPOINT: Final[str] = "/v5/execution/list"
_CLOSED_PNL_ENDPOINT: Final[str] = "/v5/position/closed-pnl"
_INSTRUMENTS_INFO_ENDPOINT: Final[str] = "/v5/market/instruments-info"


# =============================================================================
# Futures Client Implementation
# =============================================================================
class BybitFuturesExchangeClient(BybitExchangeClient):
    """Bybit Linear Perpetual (Futures) exchange client."""

    __slots__ = ()

    def __init__(
        self,
        *,
        rest: BybitRestClient,
        mapper: BybitExchangeMapper,
    ) -> None:
        """Initialize the Bybit Futures client."""
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
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> Order:
        """Create a new Bybit linear perpetual order."""
        normalized_symbol = symbol.strip().upper()
        bybit_side = "Buy" if side is OrderSide.BUY else "Sell"
        bybit_type = "Market" if order_type is OrderType.MARKET else "Limit"

        data: dict[str, object] = {
            "category": "linear",
            "symbol": normalized_symbol,
            "side": bybit_side,
            "orderType": bybit_type,
            "qty": str(quantity),
            "timeInForce": time_in_force,
            "reduceOnly": reduce_only,
        }
        if price is not None and bybit_type == "Limit":
            data["price"] = str(price)
        if client_order_id:
            data["orderLinkId"] = client_order_id

        try:
            payload = await self._rest.post(
                _ORDER_CREATE_ENDPOINT,
                data=data,
                authenticated=True,
            )
        except BybitRestResponseError as error:
            raise ExchangeOrderRejectedError(
                f"Bybit explicitly rejected the order: {error}"
            ) from error
        except (TimeoutError, RuntimeError) as error:
            raise ExchangeOrderOutcomeUnknownError(
                f"Bybit order outcome is unknown: {error}"
            ) from error

        order_id = ""
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                order_id = str(result_map.get("orderId", ""))

        if order_id:
            try:
                return await self.get_order(symbol=normalized_symbol, order_id=order_id)
            except Exception:
                pass

        now = datetime.now(timezone.utc)
        return Order(
            order_id=order_id or "bybit-submitted",
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
        """Create conditional stop-loss and take-profit orders for a position."""
        normalized_symbol = symbol.strip().upper()
        orders: list[Order] = []

        # Stop loss order
        if stop_loss is not None:
            trigger_dir = 2 if side is OrderSide.SELL else 1
            data: dict[str, object] = {
                "category": "linear",
                "symbol": normalized_symbol,
                "side": "Buy" if side is OrderSide.BUY else "Sell",
                "orderType": "Market",
                "qty": str(quantity),
                "triggerPrice": str(stop_loss),
                "triggerDirection": trigger_dir,
                "triggerBy": "MarkPrice",
                "orderFilter": "StopOrder",
                "reduceOnly": True,
            }
            if stop_loss_client_algo_id:
                data["orderLinkId"] = stop_loss_client_algo_id

            try:
                resp = await self._rest.post(
                    _ORDER_CREATE_ENDPOINT,
                    data=data,
                    authenticated=True,
                )
            except BybitRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bybit protection order was rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bybit protection order outcome is unknown: {error}"
                ) from error
            order_id = ""
            if isinstance(resp, dict):
                raw_result = resp.get("result")
                if isinstance(raw_result, dict):
                    result_map = cast(ExchangePayload, raw_result)
                    order_id = str(result_map.get("orderId", ""))

            now = datetime.now(timezone.utc)
            orders.append(
                Order(
                    order_id=order_id or "bybit-sl",
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

        # Take profit order
        if take_profit is not None:
            trigger_dir = 1 if side is OrderSide.SELL else 2
            tp_data: dict[str, object] = {
                "category": "linear",
                "symbol": normalized_symbol,
                "side": "Buy" if side is OrderSide.BUY else "Sell",
                "orderType": "Market",
                "qty": str(quantity),
                "triggerPrice": str(take_profit),
                "triggerDirection": trigger_dir,
                "triggerBy": "MarkPrice",
                "orderFilter": "StopOrder",
                "reduceOnly": True,
            }
            if take_profit_client_algo_id:
                tp_data["orderLinkId"] = take_profit_client_algo_id

            try:
                resp = await self._rest.post(
                    _ORDER_CREATE_ENDPOINT,
                    data=tp_data,
                    authenticated=True,
                )
            except BybitRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bybit protection order was rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bybit protection order outcome is unknown: {error}"
                ) from error
            order_id = ""
            if isinstance(resp, dict):
                raw_result = resp.get("result")
                if isinstance(raw_result, dict):
                    result_map = cast(ExchangePayload, raw_result)
                    order_id = str(result_map.get("orderId", ""))

            now = datetime.now(timezone.utc)
            orders.append(
                Order(
                    order_id=order_id or "bybit-tp",
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

    async def cancel_order(self, *, symbol: str, order_id: str) -> Order:
        """Cancel an existing order."""
        normalized_symbol = symbol.strip().upper()
        existing_order: Order | None = None
        try:
            existing_order = await self.get_order(
                symbol=normalized_symbol, order_id=order_id
            )
        except Exception:
            pass

        await self._rest.post(
            _ORDER_CANCEL_ENDPOINT,
            data={
                "category": "linear",
                "symbol": normalized_symbol,
                "orderId": order_id,
            },
            authenticated=True,
        )

        now = datetime.now(timezone.utc)
        if existing_order is not None:
            return Order(
                order_id=existing_order.order_id,
                symbol=existing_order.symbol,
                side=existing_order.side,
                order_type=existing_order.order_type,
                status=OrderStatus.CANCELED,
                quantity=existing_order.quantity,
                executed_quantity=existing_order.executed_quantity,
                price=existing_order.price,
                stop_price=existing_order.stop_price,
                client_order_id=existing_order.client_order_id,
                created_at=existing_order.created_at,
                updated_at=now,
            )

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

    async def cancel_all_orders(self, *, symbol: str | None = None) -> Sequence[Order]:
        """Cancel all open linear orders."""
        data: dict[str, object] = {"category": "linear"}
        if symbol is not None:
            data["symbol"] = symbol.strip().upper()

        payload = await self._rest.post(
            _ORDER_CANCEL_ALL_ENDPOINT,
            data=data,
            authenticated=True,
        )
        cancelled: list[Order] = []
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                order_list = result_map.get("list")
                if isinstance(order_list, list):
                    for item in cast(list[object], order_list):
                        if isinstance(item, dict):
                            cancelled.append(
                                self._mapper.map_order(cast(ExchangePayload, item))
                            )

        return tuple(cancelled)

    async def get_order(self, *, symbol: str, order_id: str) -> Order:
        """Return an order by its identifier."""
        payload = await self._rest.get(
            _ORDER_REALTIME_ENDPOINT,
            params={
                "category": "linear",
                "symbol": symbol.strip().upper(),
                "orderId": order_id,
            },
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                order_list = result_map.get("list")
                if isinstance(order_list, list) and order_list:
                    first = cast(list[object], order_list)[0]
                    if isinstance(first, dict):
                        return self._mapper.map_order(cast(ExchangePayload, first))

        raise ExchangeOrderNotFoundError(
            f"Order {order_id!r} not found for symbol {symbol!r}"
        )

    async def get_order_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Return an order by its client order ID."""
        payload = await self._rest.get(
            _ORDER_REALTIME_ENDPOINT,
            params={
                "category": "linear",
                "symbol": symbol.strip().upper(),
                "orderLinkId": client_order_id,
            },
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                order_list = result_map.get("list")
                if isinstance(order_list, list) and order_list:
                    first = cast(list[object], order_list)[0]
                    if isinstance(first, dict):
                        return self._mapper.map_order(cast(ExchangePayload, first))

        raise ExchangeOrderNotFoundError(
            f"Order with client ID {client_order_id!r} not found for symbol {symbol!r}"
        )

    async def get_open_orders(self, *, symbol: str | None = None) -> Sequence[Order]:
        """Return currently open orders."""
        params: dict[str, str | int] = {
            "category": "linear",
            "openOnly": 0,
        }
        if symbol is not None:
            params["symbol"] = symbol.strip().upper()
        else:
            params["settleCoin"] = "USDT"

        payload = await self._rest.get(
            _ORDER_REALTIME_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                order_list = result_map.get("list")
                if isinstance(order_list, list):
                    for item in cast(list[object], order_list):
                        if isinstance(item, dict):
                            orders.append(
                                self._mapper.map_order(cast(ExchangePayload, item))
                            )

        return tuple(orders)

    async def get_open_protection_orders(
        self, *, symbol: str | None = None
    ) -> Sequence[Order]:
        """Return currently open conditional protection orders."""
        params: dict[str, str | int] = {
            "category": "linear",
            "orderFilter": "StopOrder",
        }
        if symbol is not None:
            params["symbol"] = symbol.strip().upper()
        else:
            params["settleCoin"] = "USDT"

        payload = await self._rest.get(
            _ORDER_REALTIME_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                order_list = result_map.get("list")
                if isinstance(order_list, list):
                    for item in cast(list[object], order_list):
                        if isinstance(item, dict):
                            orders.append(
                                self._mapper.map_order(cast(ExchangePayload, item))
                            )

        return tuple(orders)

    async def get_protection_order_by_client_id(
        self, *, symbol: str, client_id: str
    ) -> Order:
        """Return one conditional protection order by client identity."""
        payload = await self._rest.get(
            _ORDER_REALTIME_ENDPOINT,
            params={
                "category": "linear",
                "symbol": symbol.strip().upper(),
                "orderLinkId": client_id,
                "orderFilter": "StopOrder",
            },
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                order_list = result_map.get("list")
                if isinstance(order_list, list) and order_list:
                    first = cast(list[object], order_list)[0]
                    if isinstance(first, dict):
                        return self._mapper.map_order(cast(ExchangePayload, first))

        raise ExchangeOrderNotFoundError(
            f"Protection order {client_id!r} not found for symbol {symbol!r}"
        )

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> None:
        """Cancel one conditional protection order by durable client identity."""
        await self._rest.post(
            _ORDER_CANCEL_ENDPOINT,
            data={
                "category": "linear",
                "symbol": symbol.strip().upper(),
                "orderLinkId": client_id,
                "orderFilter": "StopOrder",
            },
            authenticated=True,
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
        """Ensure one durable stop replacement and retire its predecessor."""
        if previous_client_algo_id:
            try:
                await self.cancel_protection_order(
                    symbol=symbol, client_id=previous_client_algo_id
                )
            except Exception as err:
                _LOGGER.warning(
                    "Failed to cancel previous stop %s: %s",
                    previous_client_algo_id,
                    err,
                )

        created = await self.create_protection_orders(
            symbol=symbol,
            side=side,
            quantity=quantity,
            stop_loss=stop_loss,
            stop_loss_client_algo_id=client_algo_id,
        )
        if not created:
            raise RuntimeError(f"Failed to create replacement stop order for {symbol}")
        return created[0]

    async def get_positions(self, *, symbol: str | None = None) -> Sequence[Position]:
        """Return active open positions."""
        params: dict[str, str] = {
            "category": "linear",
        }
        if symbol is not None:
            params["symbol"] = symbol.strip().upper()
        else:
            params["settleCoin"] = "USDT"

        payload = await self._rest.get(
            _POSITION_LIST_ENDPOINT,
            params=params,
            authenticated=True,
        )
        positions: list[Position] = []
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                pos_list = result_map.get("list")
                if isinstance(pos_list, list):
                    for item in cast(list[object], pos_list):
                        if isinstance(item, dict):
                            item_map = cast(ExchangePayload, item)
                            size_val = Decimal(str(item_map.get("size", "0")))
                            if size_val > Decimal("0"):
                                positions.append(self._mapper.map_position(item_map))

        return tuple(positions)

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
    ) -> Order:
        """Close an active position via market order with reduceOnly=True."""
        normalized_symbol = symbol.strip().upper()
        positions = await self.get_positions(symbol=normalized_symbol)
        if not positions:
            raise ValueError(
                f"No active position to close for symbol {normalized_symbol!r}"
            )

        pos = positions[0]
        close_side = OrderSide.SELL if pos.side is PositionSide.LONG else OrderSide.BUY

        return await self.create_order(
            symbol=normalized_symbol,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=pos.quantity,
            client_order_id=client_order_id,
            reduce_only=True,
        )

    async def close_all_positions(self) -> Sequence[Order]:
        """Close all active open positions."""
        positions = await self.get_positions()
        orders: list[Order] = []
        for pos in positions:
            order = await self.close_position(symbol=pos.symbol)
            orders.append(order)
        return tuple(orders)

    async def set_leverage(self, *, symbol: str, leverage: int) -> None:
        """Set leverage for a linear perpetual symbol."""
        try:
            await self._rest.post(
                _SET_LEVERAGE_ENDPOINT,
                data={
                    "category": "linear",
                    "symbol": symbol.strip().upper(),
                    "buyLeverage": str(leverage),
                    "sellLeverage": str(leverage),
                },
                authenticated=True,
            )
        except Exception as error:
            # Bybit returns 110043 if leverage is not modified
            if "110043" in str(error):
                return
            raise

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
            "category": "linear",
            "symbol": normalized_symbol,
            "orderId": normalized_order_id,
            "limit": 100,
        }
        payload = await self._rest.get(
            _EXECUTION_LIST_ENDPOINT,
            params=params,
            authenticated=True,
        )
        trades: list[Trade] = []
        if isinstance(payload, dict):
            raw_result = payload.get("result")
            if isinstance(raw_result, dict):
                result_map = cast(ExchangePayload, raw_result)
                trade_list = result_map.get("list")
                if isinstance(trade_list, list):
                    for item in cast(list[object], trade_list):
                        if isinstance(item, dict):
                            trade = self._mapper.map_trade(cast(ExchangePayload, item))
                            if trade.order_id == normalized_order_id:
                                trades.append(trade)

        if trades and any(trade.realized_pnl is None for trade in trades):
            closed_pnl_payload = await self._rest.get(
                _CLOSED_PNL_ENDPOINT,
                params={
                    "category": "linear",
                    "symbol": normalized_symbol,
                    "orderId": normalized_order_id,
                    "limit": 10,
                },
                authenticated=True,
            )
            closed_pnl: Decimal | None = None
            if isinstance(closed_pnl_payload, dict):
                pnl_result = closed_pnl_payload.get("result")
                if isinstance(pnl_result, dict):
                    pnl_list = cast(ExchangePayload, pnl_result).get("list")
                    if isinstance(pnl_list, list):
                        for item in cast(list[object], pnl_list):
                            if isinstance(item, dict):
                                item_map = cast(ExchangePayload, item)
                                if (
                                    str(item_map.get("orderId", "")).strip()
                                    == normalized_order_id
                                ):
                                    raw_pnl = item_map.get("closedPnl")
                                    if raw_pnl is not None and raw_pnl != "":
                                        closed_pnl = Decimal(str(raw_pnl))
                                        break
            if closed_pnl is not None:
                total_qty = sum((trade.quantity for trade in trades), Decimal("0"))
                if total_qty > Decimal("0") and len(trades) > 1:
                    trades = [
                        replace(
                            trade,
                            realized_pnl=closed_pnl * (trade.quantity / total_qty),
                        )
                        for trade in trades
                    ]
                else:
                    trades = [
                        replace(trade, realized_pnl=closed_pnl) for trade in trades
                    ]

        return tuple(trades)

    async def verify_mainnet_readiness(self) -> None:
        """Verify API key connectivity and UTA account access."""
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
            _INSTRUMENTS_INFO_ENDPOINT,
            params={"category": "linear", "symbol": normalized_symbol},
            authenticated=False,
        )
        if not isinstance(payload, dict):
            raise ValueError(
                f"Invalid instruments-info response for {normalized_symbol!r}"
            )

        raw_result = payload.get("result")
        if not isinstance(raw_result, dict):
            raise ValueError(f"No instrument result found for {normalized_symbol!r}")

        inst_list = cast(ExchangePayload, raw_result).get("list")
        if not isinstance(inst_list, list) or not inst_list:
            raise ValueError(f"No instrument rules found for {normalized_symbol!r}")

        first = cast(list[object], inst_list)[0]
        if not isinstance(first, dict):
            raise ValueError(f"Invalid instrument data for {normalized_symbol!r}")

        first_map = cast(ExchangePayload, first)
        self._mapper.map_symbol_rules(first_map)

        max_allowed_leverage = maximum_leverage
        lev_filter = first_map.get("leverageFilter")
        if isinstance(lev_filter, dict):
            raw_max = cast(ExchangePayload, lev_filter).get("maxLeverage")
            if raw_max is not None and str(raw_max).strip() != "":
                try:
                    max_allowed_leverage = int(float(str(raw_max)))
                except ValueError, TypeError:
                    max_allowed_leverage = maximum_leverage

        target_leverage = max(1, min(maximum_leverage, max_allowed_leverage))
        await self.set_leverage(symbol=normalized_symbol, leverage=target_leverage)
        _LOGGER.info(
            "Bybit symbol leverage verified and aligned: symbol=%s leverage=%dx "
            "(maximum_allowed=%dx requested=%dx)",
            normalized_symbol,
            target_leverage,
            max_allowed_leverage,
            maximum_leverage,
        )
