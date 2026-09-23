"""
Botragram

Description:
    Bitget CFD exchange client implementing BaseExchangeClient.

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
from botragram.engine.cfd_financing_engine import CfdFinancingEngine
from botragram.engine.cfd_sizing_engine import CfdSizingEngine
from botragram.engine.market_calendar import MarketCalendarEngine
from botragram.enums import (
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exceptions.exchange import (
    ExchangeError,
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.base.mapper import ExchangePayload
from botragram.exchanges.bitget.cfd_mapper import BitgetCfdMapper
from botragram.exchanges.bitget.rest import BitgetRestClient, BitgetRestResponseError
from botragram.models import (
    Account,
    Candle,
    CfdContractSpec,
    CfdFinancingSchedule,
    CfdMarginRequirement,
    CfdOvernightSwapEstimate,
    ExchangeSymbolRules,
    MarketSession,
    Order,
    PipCalculationResult,
    Position,
    Ticker,
    Trade,
)

__all__ = [
    "BITGET_CFD_INTERVAL_MAP",
    "BitgetCfdExchangeClient",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)

_PING_ENDPOINT: Final[str] = "/api/v2/public/time"
_CFD_ACCOUNT_ENDPOINT: Final[str] = "/api/v3/cfd/account/fund-detail"
_CFD_TICKERS_ENDPOINT: Final[str] = "/api/v3/cfd/market/tickers"
_CFD_CANDLES_ENDPOINT: Final[str] = "/api/v3/cfd/market/history-candlestick"
_CFD_SYMBOLS_ENDPOINT: Final[str] = "/api/v3/cfd/market/tickers"
_CFD_PLACE_ORDER_ENDPOINT: Final[str] = "/api/v3/cfd/trade/place-order"
_CFD_CANCEL_ORDER_ENDPOINT: Final[str] = "/api/v3/cfd/trade/cancel-order"
_CFD_ORDER_INFO_ENDPOINT: Final[str] = "/api/v3/cfd/trade/order-info"
_CFD_OPEN_ORDERS_ENDPOINT: Final[str] = "/api/v3/cfd/trade/open-orders"
_CFD_POSITIONS_ENDPOINT: Final[str] = "/api/v3/cfd/trade/positions"
_CFD_CLOSE_POSITION_ENDPOINT: Final[str] = "/api/v3/cfd/trade/close-positions"

_CFD_PLACE_PLAN_ORDER_ENDPOINT: Final[str] = "/api/v3/cfd/trade/place-strategy-order"
_CFD_CANCEL_PLAN_ORDER_ENDPOINT: Final[str] = "/api/v3/cfd/trade/cancel-strategy-order"
_CFD_PLAN_OPEN_ENDPOINT: Final[str] = "/api/v3/cfd/trade/unfilled-strategy-orders"
_CFD_PLAN_HISTORY_ENDPOINT: Final[str] = "/api/v3/cfd/trade/history-strategy-orders"

BITGET_CFD_INTERVAL_MAP: Final[dict[Interval, str]] = {
    Interval.M1: "1m",
    Interval.M3: "1m",
    Interval.M5: "1m",
    Interval.M15: "15m",
    Interval.M30: "15m",
    Interval.H1: "1h",
    Interval.H2: "1h",
    Interval.H4: "4h",
    Interval.H6: "4h",
    Interval.H12: "4h",
    Interval.D1: "1d",
    Interval.W1: "1d",
    Interval.MN1: "1d",
}


# =============================================================================
# Bitget CFD Exchange Client Class
# =============================================================================
class BitgetCfdExchangeClient(BaseExchangeClient):
    """Bitget CFD exchange client providing TradFi CFD capabilities."""

    __slots__ = (
        "_calendar",
        "_financing",
        "_mapper",
        "_mode",
        "_rest",
        "_sizing",
    )

    def __init__(
        self,
        *,
        rest: BitgetRestClient,
        mapper: BitgetCfdMapper,
        mode: str = "ecn",
        calendar: MarketCalendarEngine | None = None,
        sizing: CfdSizingEngine | None = None,
        financing: CfdFinancingEngine | None = None,
    ) -> None:
        """Initialize the Bitget CFD client.

        Args:
            rest: Bitget REST transport client.
            mapper: Bitget CFD payload mapper.
            mode: CFD instrument mode ('ecn', 'zero_fee', or 'pro').
            calendar: Optional market calendar engine for session evaluation.
            sizing: Optional CFD sizing engine for pip/lot calculations.
            financing: Optional CFD financing engine for rollover swap calculations.
        """
        self._rest = rest
        self._mapper = mapper
        self._mode = mode
        self._calendar = calendar if calendar is not None else MarketCalendarEngine()
        self._sizing = (
            sizing if sizing is not None else CfdSizingEngine(calendar=self._calendar)
        )
        self._financing = (
            financing
            if financing is not None
            else CfdFinancingEngine(calendar=self._calendar, sizing=self._sizing)
        )

    @property
    def mode(self) -> str:
        """Return the active CFD mode."""
        return self._mode

    @property
    def calendar(self) -> MarketCalendarEngine:
        """Return the market calendar engine."""
        return self._calendar

    @property
    def sizing(self) -> CfdSizingEngine:
        """Return the CFD sizing engine."""
        return self._sizing

    @property
    def financing(self) -> CfdFinancingEngine:
        """Return the CFD financing and rollover engine."""
        return self._financing

    def get_contract_spec(self, symbol: str) -> CfdContractSpec:
        """Return the contract and pip specifications for a symbol."""
        return self._sizing.get_contract_spec(symbol)

    def get_financing_schedule(self, symbol: str) -> CfdFinancingSchedule:
        """Return the financing interest and rollover schedule for a symbol."""
        return self._financing.get_financing_schedule(symbol)

    def estimate_overnight_swap(
        self,
        *,
        symbol: str,
        side: PositionSide,
        lots: Decimal,
        price: Decimal,
        at: datetime | None = None,
    ) -> CfdOvernightSwapEstimate:
        """Estimate overnight rollover swap interest for holding a CFD position."""
        return self._financing.estimate_overnight_swap(
            symbol=symbol,
            side=side,
            lots=lots,
            price=price,
            at=at,
        )

    def calculate_margin_requirement(
        self,
        *,
        symbol: str,
        lots: Decimal,
        price: Decimal,
        leverage: int,
        free_margin: Decimal,
    ) -> CfdMarginRequirement:
        """Calculate margin requirements and capital sufficiency for a CFD trade."""
        return self._financing.calculate_margin_requirement(
            symbol=symbol,
            lots=lots,
            price=price,
            leverage=leverage,
            free_margin=free_margin,
        )

    def calculate_lot_size(
        self,
        *,
        symbol: str,
        entry_price: Decimal,
        stop_loss: Decimal,
        risk_amount: Decimal,
        quote_to_account_rate: Decimal = Decimal("1.0"),
    ) -> PipCalculationResult:
        """Calculate dynamic lot sizing based on stop-loss distance and risk capital."""
        return self._sizing.calculate_lot_size(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_amount=risk_amount,
            quote_to_account_rate=quote_to_account_rate,
        )

    async def is_market_open(
        self,
        *,
        symbol: str,
        at: datetime | None = None,
    ) -> bool:
        """Return whether the TradFi CFD market is open for the given symbol."""
        return self._calendar.is_market_open(symbol=symbol, at=at)

    async def get_market_session(
        self,
        *,
        symbol: str,
        at: datetime | None = None,
    ) -> MarketSession:
        """Return the market trading session details for the symbol."""
        return self._calendar.get_session(symbol=symbol, at=at)

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def connect(self) -> None:
        """Initialize connections and verify connectivity."""
        await self.ping()

    async def close(self) -> None:
        """Release underlying REST sessions."""
        await self._rest.close()

    async def ping(self) -> bool:
        """Return whether Bitget API is reachable."""
        try:
            payload = await self._rest.get(_PING_ENDPOINT, authenticated=False)
            return isinstance(payload, dict) and payload.get("code") == "00000"
        except Exception as error:
            _LOGGER.debug("Bitget CFD ping failed: %s", error)
            return False

    # =========================================================================
    # Account & Market Data
    # =========================================================================

    async def get_account(self) -> Account:
        """Return current CFD account fund details."""
        payload = await self._rest.get(_CFD_ACCOUNT_ENDPOINT, authenticated=True)
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_account(cast(ExchangePayload, raw_data))
        return self._mapper.map_account({})

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return latest ticker for a CFD symbol."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        payload = await self._rest.get(
            _CFD_TICKERS_ENDPOINT,
            params={"symbol": vendor_symbol},
            authenticated=False,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list):
                raw_list = cast(list[object], raw_data)
                if raw_list and isinstance(raw_list[0], dict):
                    return self._mapper.map_ticker(cast(ExchangePayload, raw_list[0]))
            elif isinstance(raw_data, dict):
                return self._mapper.map_ticker(cast(ExchangePayload, raw_data))

        raise ExchangeError(f"No ticker returned for CFD symbol {symbol}")

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return quantity and pricing rules for a CFD symbol."""
        spec = self._sizing.get_contract_spec(symbol)
        return ExchangeSymbolRules(
            symbol=self._mapper.normalize_symbol(symbol),
            market_min_quantity=spec.min_lot,
            market_max_quantity=spec.max_lot,
            market_quantity_step=spec.lot_step,
            price_tick_size=spec.pip_size,
        )

    async def get_trading_symbols(self, *, quote_asset: str) -> Sequence[str]:
        """Return list of active CFD trading symbols."""
        try:
            payload = await self._rest.get(_CFD_TICKERS_ENDPOINT, authenticated=False)
            if isinstance(payload, dict):
                raw_data = payload.get("data")
                if isinstance(raw_data, list):
                    result: list[str] = []
                    seen: set[str] = set()
                    quote_upper = quote_asset.strip().upper()
                    for item in cast(list[object], raw_data):
                        if isinstance(item, dict):
                            item_payload = cast(ExchangePayload, item)
                            sym = str(item_payload.get("symbol", ""))
                            clean_sym = self._mapper.normalize_symbol(sym)
                            if clean_sym in seen:
                                continue
                            if clean_sym.endswith(quote_upper) or (
                                quote_upper in ("USD", "USDT")
                                and (
                                    clean_sym.endswith("USD")
                                    or clean_sym.endswith("USDT")
                                )
                            ):
                                seen.add(clean_sym)
                                result.append(clean_sym)
                    return tuple(result)
        except Exception as error:
            _LOGGER.warning("Failed to fetch CFD trading symbols: %s", error)
        return ()

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Return historical CFD candlestick data."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        interval_str = BITGET_CFD_INTERVAL_MAP.get(interval, "15m")
        params: dict[str, str | int] = {
            "symbol": vendor_symbol,
            "interval": interval_str,
            "side": "buy",
            "limit": min(limit, 100),
        }
        if start_time is not None:
            params["startTime"] = int(start_time.timestamp() * 1000)
        if end_time is not None:
            params["endTime"] = int(end_time.timestamp() * 1000)

        payload = await self._rest.get(
            _CFD_CANDLES_ENDPOINT,
            params=params,
            authenticated=False,
        )
        candles: list[Candle] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list):
                for row in cast(list[object], raw_data):
                    if isinstance(row, (list, tuple)):
                        row_items = cast(Sequence[object], row)
                        candles.append(
                            self._mapper.map_candle(
                                tuple(row_items),
                                symbol=symbol,
                                interval=interval,
                            )
                        )
        return tuple(candles)

    async def get_trades(
        self,
        *,
        symbol: str | None,
        limit: int,
    ) -> Sequence[Trade]:
        """Return recent CFD executions/fills."""
        del symbol, limit
        # CFD trades endpoint will be linked when account trade history is queried
        return ()

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
        bypass_calendar_guard: bool = False,
    ) -> Order:
        """Create a new CFD order."""
        if not bypass_calendar_guard:
            session = self._calendar.get_session(symbol)
            if not session.is_open:
                raise ExchangeOrderRejectedError(
                    f"TradFi CFD market is closed for {symbol} "
                    f"(status: {session.status.value}, reason: {session.reason})"
                )

        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        side_str = "buy" if side is OrderSide.BUY else "sell"
        type_str = "market" if order_type is OrderType.MARKET else "limit"
        body: dict[str, object] = {
            "symbol": vendor_symbol,
            "side": side_str,
            "orderType": type_str,
            "size": str(quantity),
        }
        if price is not None:
            body["price"] = str(price)
        if client_order_id is not None:
            body["clientOid"] = client_order_id

        payload = await self._rest.post(
            _CFD_PLACE_ORDER_ENDPOINT,
            data=body,
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_order(cast(ExchangePayload, raw_data))

        raise ExchangeOrderRejectedError(
            f"Bitget CFD order submission failed for {symbol}: {payload}"
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
        bypass_calendar_guard: bool = False,
    ) -> Sequence[Order]:
        """Create conditional stop-loss and take-profit plan orders for CFD."""
        if not bypass_calendar_guard:
            session = self._calendar.get_session(symbol)
            if not session.is_open:
                raise ExchangeOrderRejectedError(
                    f"Cannot place protection orders: TradFi CFD market is closed "
                    f"for {symbol} (status: {session.status.value}, "
                    f"reason: {session.reason})"
                )

        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        pos_side = "long" if side is OrderSide.SELL else "short"

        # Case 1: Both legs requested - combined TPSL submission
        if stop_loss is not None and take_profit is not None:
            data: dict[str, object] = {
                "symbol": vendor_symbol,
                "type": "tpsl",
                "posSide": pos_side,
                "size": str(quantity),
                "stopLoss": str(stop_loss),
                "takeProfit": str(take_profit),
            }
            if stop_loss_client_algo_id:
                data["clientOid"] = stop_loss_client_algo_id
            elif take_profit_client_algo_id:
                data["clientOid"] = take_profit_client_algo_id

            try:
                resp = await self._rest.post(
                    _CFD_PLACE_PLAN_ORDER_ENDPOINT,
                    data=data,
                    authenticated=True,
                )
            except BitgetRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bitget CFD protection orders rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bitget CFD protection orders outcome unknown: {error}"
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
                    order_id=order_id or "bitget-cfd-sl",
                    symbol=self._mapper.normalize_symbol(symbol),
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
                    order_id=order_id or "bitget-cfd-tp",
                    symbol=self._mapper.normalize_symbol(symbol),
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

        # Case 2: Only stop-loss requested
        if stop_loss is not None:
            existing_tp_price: Decimal | None = None
            try:
                open_protections = await self.get_open_protection_orders(symbol=symbol)
                for existing in open_protections:
                    if (
                        existing.order_type
                        in (OrderType.TAKE_PROFIT_MARKET, OrderType.TAKE_PROFIT)
                        and existing.stop_price is not None
                    ):
                        existing_tp_price = existing.stop_price
                        break
            except Exception as check_error:
                _LOGGER.warning(
                    "Could not inspect open protections before placing SL for %s: %s",
                    symbol,
                    check_error,
                )

            sl_data: dict[str, object] = {
                "symbol": vendor_symbol,
                "type": "tpsl",
                "posSide": pos_side,
                "size": str(quantity),
                "stopLoss": str(stop_loss),
            }
            if existing_tp_price is not None:
                sl_data["takeProfit"] = str(existing_tp_price)
            if stop_loss_client_algo_id:
                sl_data["clientOid"] = stop_loss_client_algo_id

            try:
                resp = await self._rest.post(
                    _CFD_PLACE_PLAN_ORDER_ENDPOINT,
                    data=sl_data,
                    authenticated=True,
                )
            except BitgetRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bitget CFD stop-loss was rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bitget CFD stop-loss outcome is unknown: {error}"
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
                    order_id=order_id or "bitget-cfd-sl",
                    symbol=self._mapper.normalize_symbol(symbol),
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

        # Case 3: Only take-profit requested
        if take_profit is not None:
            existing_sl_price: Decimal | None = None
            try:
                open_protections = await self.get_open_protection_orders(symbol=symbol)
                for existing in open_protections:
                    if (
                        existing.order_type in (OrderType.STOP_MARKET, OrderType.STOP)
                        and existing.stop_price is not None
                    ):
                        existing_sl_price = existing.stop_price
                        break
            except Exception as check_error:
                _LOGGER.warning(
                    "Could not inspect open protections before placing TP for %s: %s",
                    symbol,
                    check_error,
                )

            tp_data: dict[str, object] = {
                "symbol": vendor_symbol,
                "type": "tpsl",
                "posSide": pos_side,
                "size": str(quantity),
                "takeProfit": str(take_profit),
            }
            if existing_sl_price is not None:
                tp_data["stopLoss"] = str(existing_sl_price)
            if take_profit_client_algo_id:
                tp_data["clientOid"] = take_profit_client_algo_id

            try:
                resp = await self._rest.post(
                    _CFD_PLACE_PLAN_ORDER_ENDPOINT,
                    data=tp_data,
                    authenticated=True,
                )
            except BitgetRestResponseError as error:
                raise ExchangeOrderRejectedError(
                    f"Bitget CFD take-profit was rejected: {error}"
                ) from error
            except (TimeoutError, RuntimeError) as error:
                raise ExchangeOrderOutcomeUnknownError(
                    f"Bitget CFD take-profit outcome is unknown: {error}"
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
                    order_id=order_id or "bitget-cfd-tp",
                    symbol=self._mapper.normalize_symbol(symbol),
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
        """Cancel an open CFD order."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        body: dict[str, object] = {
            "symbol": vendor_symbol,
            "orderId": order_id,
        }
        payload = await self._rest.post(
            _CFD_CANCEL_ORDER_ENDPOINT,
            data=body,
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_order(cast(ExchangePayload, raw_data))

        return await self.get_order(symbol=symbol, order_id=order_id)

    async def cancel_all_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Cancel all open CFD orders."""
        open_orders = await self.get_open_orders(symbol=symbol)
        canceled: list[Order] = []
        for order in open_orders:
            try:
                canceled.append(
                    await self.cancel_order(
                        symbol=order.symbol,
                        order_id=order.order_id,
                    )
                )
            except Exception as error:
                _LOGGER.warning(
                    "Failed to cancel CFD order %s: %s",
                    order.order_id,
                    error,
                )
        return tuple(canceled)

    async def get_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Return CFD order detail by order ID."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        payload = await self._rest.get(
            _CFD_ORDER_INFO_ENDPOINT,
            params={"symbol": vendor_symbol, "orderId": order_id},
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_order(cast(ExchangePayload, raw_data))

        raise ExchangeOrderNotFoundError(
            f"CFD order {order_id} for {symbol} was not found"
        )

    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Return CFD order detail by client order ID."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        payload = await self._rest.get(
            _CFD_ORDER_INFO_ENDPOINT,
            params={"symbol": vendor_symbol, "clientOid": client_order_id},
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                return self._mapper.map_order(cast(ExchangePayload, raw_data))

        raise ExchangeOrderNotFoundError(
            f"CFD client order {client_order_id} for {symbol} not found"
        )

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return open CFD orders."""
        params: dict[str, str] = {}
        if symbol is not None:
            params["symbol"] = self._mapper.to_vendor_symbol(symbol, mode=self._mode)

        payload = await self._rest.get(
            _CFD_OPEN_ORDERS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        orders: list[Order] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list):
                for item in cast(list[object], raw_data):
                    if isinstance(item, dict):
                        orders.append(
                            self._mapper.map_order(cast(ExchangePayload, item))
                        )
        return tuple(orders)

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return open CFD conditional protection orders."""
        params: dict[str, str] = {}
        if symbol is not None:
            params["symbol"] = self._mapper.to_vendor_symbol(symbol, mode=self._mode)

        payload = await self._rest.get(
            _CFD_PLAN_OPEN_ENDPOINT,
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
        """Find pending CFD protection plan order by client_id."""
        orders = await self.get_open_protection_orders(symbol=symbol)
        for order in orders:
            if order.client_order_id == client_id:
                return order

        # Handle companion leg for combined TPSL
        if client_id.startswith("btp-"):
            for order in orders:
                if order.order_type in (
                    OrderType.TAKE_PROFIT_MARKET,
                    OrderType.TAKE_PROFIT,
                ) and (order.client_order_id is None or order.order_id.endswith("-tp")):
                    return replace(order, client_order_id=client_id)

        if client_id.startswith("bsl-"):
            for order in orders:
                if order.order_type in (
                    OrderType.STOP_MARKET,
                    OrderType.STOP,
                ) and (order.client_order_id is None or order.order_id.endswith("-sl")):
                    return replace(order, client_order_id=client_id)

        raise ExchangeOrderNotFoundError(
            f"CFD protection order with client_id {client_id!r} not found "
            f"for symbol {symbol!r}"
        )

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> None:
        """Cancel conditional plan order by client_id."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        data: dict[str, object] = {
            "symbol": vendor_symbol,
        }
        resolved_order_id: str | None = None
        try:
            matched = await self.get_protection_order_by_client_id(
                symbol=symbol,
                client_id=client_id,
            )
            clean_id = (
                matched.order_id[:-3]
                if matched.order_id.endswith(("-tp", "-sl"))
                else matched.order_id
            )
            if clean_id and not clean_id.startswith("bitget-cfd-"):
                resolved_order_id = clean_id
        except Exception:
            resolved_order_id = None

        if resolved_order_id is not None:
            data["orderId"] = resolved_order_id
        else:
            data["clientOid"] = client_id

        try:
            await self._rest.post(
                _CFD_CANCEL_PLAN_ORDER_ENDPOINT,
                data=data,
                authenticated=True,
            )
        except Exception as error:
            _LOGGER.warning(
                "Failed to cancel CFD protection order %s: %s",
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
        """Replace or ensure a stop-loss plan order for CFD position."""
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
                f"Failed to place stop loss order for CFD {symbol} at {stop_loss}"
            )
        return orders[0]

    async def get_protection_order_history(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> Sequence[Order]:
        """Return conditional protection order history for one CFD symbol."""
        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        start_ms = int(start_time.timestamp() * 1000)
        params: dict[str, str | int] = {
            "symbol": vendor_symbol,
            "startTime": start_ms,
            "limit": 100,
        }
        if end_time is not None:
            params["endTime"] = int(end_time.timestamp() * 1000)

        payload = await self._rest.get(
            _CFD_PLAN_HISTORY_ENDPOINT,
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

    # =========================================================================
    # Positions
    # =========================================================================

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return open CFD positions."""
        params: dict[str, str] = {}
        if symbol is not None:
            params["symbol"] = self._mapper.to_vendor_symbol(symbol, mode=self._mode)

        payload = await self._rest.get(
            _CFD_POSITIONS_ENDPOINT,
            params=params,
            authenticated=True,
        )
        positions: list[Position] = []
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, list):
                for item in cast(list[object], raw_data):
                    if isinstance(item, dict):
                        positions.append(
                            self._mapper.map_position(cast(ExchangePayload, item))
                        )
        return tuple(positions)

    async def close_position(
        self,
        *,
        symbol: str,
        client_order_id: str | None = None,
        bypass_calendar_guard: bool = False,
    ) -> Order:
        """Close an open CFD position."""
        if not bypass_calendar_guard:
            session = self._calendar.get_session(symbol)
            if not session.is_open:
                raise ExchangeOrderRejectedError(
                    f"Cannot close position: TradFi CFD market is closed for {symbol} "
                    f"(status: {session.status.value}, reason: {session.reason})"
                )

        vendor_symbol = self._mapper.to_vendor_symbol(symbol, mode=self._mode)
        body: dict[str, object] = {"symbol": vendor_symbol}
        if client_order_id is not None:
            body["clientOid"] = client_order_id

        payload = await self._rest.post(
            _CFD_CLOSE_POSITION_ENDPOINT,
            data=body,
            authenticated=True,
        )
        if isinstance(payload, dict):
            raw_data = payload.get("data")
            if isinstance(raw_data, dict):
                mapped = self._mapper.map_order(cast(ExchangePayload, raw_data))
                if client_order_id and not mapped.client_order_id:
                    return replace(mapped, client_order_id=client_order_id)
                return mapped

        raise ExchangeError(f"Failed to close CFD position for {symbol}: {payload}")

    async def close_position_exact(
        self,
        *,
        position: Position,
        client_order_id: str,
    ) -> Order:
        """Submit one close from an authoritative CFD position snapshot."""
        return await self.close_position(
            symbol=position.symbol,
            client_order_id=client_order_id,
        )

    async def close_all_positions(self) -> Sequence[Order]:
        """Close all active CFD positions."""
        open_positions = await self.get_positions()
        closed_orders: list[Order] = []
        for position in open_positions:
            try:
                closed_orders.append(await self.close_position(symbol=position.symbol))
            except Exception as error:
                _LOGGER.warning(
                    "Failed to close CFD position for %s: %s",
                    position.symbol,
                    error,
                )
        return tuple(closed_orders)
