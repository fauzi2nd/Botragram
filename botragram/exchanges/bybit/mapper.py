"""
Botragram

Description:
    Bybit V5 payload mapper translating vendor payloads into domain models.

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
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Final, cast

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import (
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from botragram.exchanges.base.mapper import (
    BaseExchangeMapper,
    ExchangePayload,
    ExchangeSequencePayload,
)
from botragram.models import (
    Account,
    Balance,
    Candle,
    ExchangeSymbolRules,
    MarketUniverseEntry,
    Order,
    Position,
    Ticker,
    Trade,
)

__all__ = [
    "BybitExchangeMapper",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DEFAULT_TICK_SIZE: Final[Decimal] = Decimal("0.0001")
_DEFAULT_MIN_QTY: Final[Decimal] = Decimal("0.001")
_DEFAULT_QTY_STEP: Final[Decimal] = Decimal("0.001")

_SIDE_MAP: Final[Mapping[str, OrderSide]] = {
    "BUY": OrderSide.BUY,
    "SELL": OrderSide.SELL,
}

_POSITION_SIDE_MAP: Final[Mapping[str, PositionSide]] = {
    "BUY": PositionSide.LONG,
    "SELL": PositionSide.SHORT,
}

_ORDER_TYPE_MAP: Final[Mapping[str, OrderType]] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "STOP": OrderType.STOP,
    "STOP_MARKET": OrderType.STOP_MARKET,
    "STOPLOSS": OrderType.STOP,
    "TAKEPROFIT": OrderType.TAKE_PROFIT,
    "TAKE_PROFIT": OrderType.TAKE_PROFIT,
    "TAKE_PROFIT_MARKET": OrderType.TAKE_PROFIT_MARKET,
}

_STATUS_MAP: Final[Mapping[str, OrderStatus]] = {
    "NEW": OrderStatus.NEW,
    "UNTRIGGERED": OrderStatus.NEW,
    "TRIGGERED": OrderStatus.NEW,
    "PARTIALLYFILLED": OrderStatus.PARTIALLY_FILLED,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELED,
    "CANCELED": OrderStatus.CANCELED,
    "DEACTIVATED": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
}


# =============================================================================
# Mapper Implementation
# =============================================================================
class BybitExchangeMapper(BaseExchangeMapper):
    """Translate Bybit V5 JSON payloads into typed Botragram domain models."""

    __slots__ = ()

    @staticmethod
    def _to_decimal(value: object, default: Decimal = _DECIMAL_ZERO) -> Decimal:
        """Safely parse a Decimal from an object."""
        if value is None or value == "":
            return default
        try:
            return Decimal(str(value))
        except InvalidOperation, TypeError, ValueError:
            return default

    @staticmethod
    def _to_datetime(timestamp_ms: object) -> datetime:
        """Parse a millisecond integer timestamp into a UTC datetime."""
        if isinstance(timestamp_ms, (int, float)):
            return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
        if isinstance(timestamp_ms, str) and timestamp_ms.isdigit():
            return datetime.fromtimestamp(int(timestamp_ms) / 1000.0, tz=timezone.utc)
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_string(value: object) -> str:
        """Convert a payload value into string."""
        if value is None:
            return ""
        return str(value)

    def map_account(self, payload: ExchangePayload) -> Account:
        """Map Bybit V5 wallet balance payload into an Account model."""
        balances: list[Balance] = []

        accounts_list = payload.get("list")
        if isinstance(accounts_list, list):
            for acc in cast(list[object], accounts_list):
                if not isinstance(acc, dict):
                    continue
                acc_map = cast(ExchangePayload, acc)
                coins = acc_map.get("coin")
                if isinstance(coins, list):
                    for coin_data in cast(list[object], coins):
                        if not isinstance(coin_data, dict):
                            continue
                        coin_map = cast(ExchangePayload, coin_data)
                        coin_name = (
                            self._to_string(coin_map.get("coin")).strip().upper()
                        )
                        if not coin_name:
                            continue
                        wallet_bal = self._to_decimal(coin_map.get("walletBalance"))
                        raw_available = coin_map.get("availableToWithdraw")
                        if raw_available is None or raw_available == "":
                            raw_available = coin_map.get("availableBalance")
                        available = self._to_decimal(
                            raw_available if raw_available is not None else wallet_bal
                        )
                        locked = max(_DECIMAL_ZERO, wallet_bal - available)
                        balances.append(
                            Balance(
                                asset=coin_name,
                                free=available,
                                locked=locked,
                            )
                        )

        return Account(
            balances=tuple(balances),
            can_trade=True,
            can_deposit=True,
            can_withdraw=True,
        )

    def map_ticker(self, payload: ExchangePayload) -> Ticker:
        """Map Bybit V5 linear ticker payload into a Ticker model."""
        symbol = self._to_string(payload.get("symbol")).strip().upper()
        last_price = self._to_decimal(payload.get("lastPrice"))
        bid_price = self._to_decimal(payload.get("bid1Price", last_price))
        ask_price = self._to_decimal(payload.get("ask1Price", last_price))

        if bid_price <= _DECIMAL_ZERO:
            bid_price = last_price
        if ask_price <= _DECIMAL_ZERO:
            ask_price = last_price

        timestamp = self._to_datetime(payload.get("time"))

        return Ticker(
            symbol=symbol,
            bid_price=bid_price,
            ask_price=ask_price,
            last_price=last_price,
            timestamp=timestamp,
        )

    def map_stream_ticker(self, payload: ExchangePayload) -> Ticker:
        """Map Bybit WebSocket linear ticker payload into a Ticker model."""
        symbol = self._to_string(payload.get("symbol")).strip().upper()
        last_price = self._to_decimal(payload.get("lastPrice"))
        bid_price = self._to_decimal(payload.get("bid1Price", last_price))
        ask_price = self._to_decimal(payload.get("ask1Price", last_price))

        if bid_price <= _DECIMAL_ZERO:
            bid_price = last_price
        if ask_price <= _DECIMAL_ZERO:
            ask_price = last_price

        timestamp = self._to_datetime(payload.get("time"))

        return Ticker(
            symbol=symbol,
            bid_price=bid_price,
            ask_price=ask_price,
            last_price=last_price,
            timestamp=timestamp,
        )

    def map_candle(
        self,
        payload: ExchangeSequencePayload,
        *,
        symbol: str,
        interval: Interval,
    ) -> Candle:
        """Map Bybit V5 kline array into a Candle model."""
        if len(payload) < 6:
            raise ValueError(f"Bybit candle payload too short: {payload!r}")

        open_time = self._to_datetime(payload[0])
        close_time = open_time + timedelta(seconds=interval.seconds)

        return Candle(
            symbol=symbol.strip().upper(),
            interval=interval,
            open_time=open_time,
            close_time=close_time,
            open_price=self._to_decimal(payload[1]),
            high_price=self._to_decimal(payload[2]),
            low_price=self._to_decimal(payload[3]),
            close_price=self._to_decimal(payload[4]),
            volume=self._to_decimal(payload[5]),
        )

    def map_stream_candle(
        self,
        payload: ExchangePayload,
        *,
        symbol: str,
        interval: Interval,
    ) -> Candle:
        """Map Bybit WebSocket kline payload into a Candle model."""
        open_time = self._to_datetime(payload.get("start"))
        end_time_raw = payload.get("end")
        if end_time_raw is not None:
            close_time = self._to_datetime(end_time_raw)
        else:
            close_time = open_time + timedelta(seconds=interval.seconds)

        return Candle(
            symbol=symbol.strip().upper(),
            interval=interval,
            open_time=open_time,
            close_time=close_time,
            open_price=self._to_decimal(payload.get("open")),
            high_price=self._to_decimal(payload.get("high")),
            low_price=self._to_decimal(payload.get("low")),
            close_price=self._to_decimal(payload.get("close")),
            volume=self._to_decimal(payload.get("volume")),
        )

    def map_order(self, payload: ExchangePayload) -> Order:
        """Map Bybit V5 order payload into an Order model."""
        order_id = self._to_string(payload.get("orderId"))
        symbol = self._to_string(payload.get("symbol")).strip().upper()

        raw_side = self._to_string(payload.get("side")).strip().upper()
        side = _SIDE_MAP.get(raw_side, OrderSide.BUY)

        raw_type = self._to_string(payload.get("orderType")).strip().upper()
        stop_order_type = self._to_string(payload.get("stopOrderType")).strip().upper()
        if stop_order_type in ("STOPLOSS", "STOP_LOSS", "STOP"):
            order_type = OrderType.STOP
        elif stop_order_type in ("TAKEPROFIT", "TAKE_PROFIT"):
            order_type = OrderType.TAKE_PROFIT
        else:
            order_type = _ORDER_TYPE_MAP.get(raw_type, OrderType.MARKET)

        raw_status = self._to_string(payload.get("orderStatus")).strip().upper()
        status = _STATUS_MAP.get(raw_status, OrderStatus.NEW)

        qty = self._to_decimal(payload.get("qty"))
        exec_qty = self._to_decimal(payload.get("cumExecQty"))

        price_val = self._to_decimal(payload.get("price"))
        price = price_val if price_val > _DECIMAL_ZERO else None

        trigger_val = self._to_decimal(payload.get("triggerPrice"))
        stop_price = trigger_val if trigger_val > _DECIMAL_ZERO else None

        client_order_id = self._to_string(payload.get("orderLinkId")).strip() or None

        created_at = self._to_datetime(payload.get("createdTime"))
        updated_at = self._to_datetime(
            payload.get("updatedTime", payload.get("createdTime"))
        )

        return Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
            quantity=qty,
            executed_quantity=exec_qty,
            price=price,
            stop_price=stop_price,
            client_order_id=client_order_id,
            created_at=created_at,
            updated_at=updated_at,
        )

    def map_position(self, payload: ExchangePayload) -> Position:
        """Map Bybit V5 position payload into a Position model."""
        symbol = self._to_string(payload.get("symbol")).strip().upper()

        raw_side = self._to_string(payload.get("side")).strip().upper()
        side = _POSITION_SIDE_MAP.get(raw_side, PositionSide.LONG)

        qty = self._to_decimal(payload.get("size"))
        entry_price = self._to_decimal(payload.get("avgPrice"))
        mark_price = self._to_decimal(payload.get("markPrice", entry_price))
        unrealized_pnl = self._to_decimal(payload.get("unrealisedPnl"))

        try:
            leverage = int(float(self._to_string(payload.get("leverage", "1"))))
        except ValueError, TypeError:
            leverage = 1

        created_at = self._to_datetime(payload.get("createdTime"))
        updated_at = self._to_datetime(
            payload.get("updatedTime", payload.get("createdTime"))
        )

        return Position(
            symbol=symbol,
            side=side,
            quantity=qty,
            entry_price=entry_price,
            current_price=mark_price,
            unrealized_pnl=unrealized_pnl,
            leverage=max(1, leverage),
            opened_at=created_at,
            updated_at=updated_at,
        )

    def map_trade(self, payload: ExchangePayload) -> Trade:
        """Map Bybit execution/trade payload into a Trade model."""
        trade_id = self._to_string(payload.get("execId", payload.get("tradeId", "")))
        order_id = self._to_string(payload.get("orderId"))
        symbol = self._to_string(payload.get("symbol")).strip().upper()

        raw_side = self._to_string(payload.get("side")).strip().upper()
        side = _SIDE_MAP.get(raw_side, OrderSide.BUY)

        price = self._to_decimal(payload.get("execPrice", payload.get("price")))
        qty = self._to_decimal(payload.get("execQty", payload.get("qty")))
        quote_qty = price * qty

        fee = self._to_decimal(payload.get("execFee", payload.get("fee")))
        fee_asset = self._to_string(payload.get("feeCurrency")).strip().upper()

        executed_at = self._to_datetime(payload.get("execTime", payload.get("time")))

        return Trade(
            trade_id=trade_id,
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=price,
            quantity=qty,
            quote_quantity=quote_qty,
            fee=fee,
            fee_asset=fee_asset,
            executed_at=executed_at,
        )

    def map_symbol_rules(self, payload: ExchangePayload) -> ExchangeSymbolRules:
        """Map Bybit V5 instrument info payload into ExchangeSymbolRules."""
        symbol = self._to_string(payload.get("symbol")).strip().upper()

        lot_filter = payload.get("lotSizeFilter")
        min_qty = _DEFAULT_MIN_QTY
        max_qty = Decimal("1000000")
        qty_step = _DEFAULT_QTY_STEP

        if isinstance(lot_filter, dict):
            lot_map = cast(ExchangePayload, lot_filter)
            min_qty = self._to_decimal(lot_map.get("minOrderQty"), min_qty)
            max_qty = self._to_decimal(lot_map.get("maxOrderQty"), max_qty)
            qty_step = self._to_decimal(lot_map.get("qtyStep"), qty_step)

        if min_qty <= _DECIMAL_ZERO:
            min_qty = _DEFAULT_MIN_QTY
        if qty_step <= _DECIMAL_ZERO:
            qty_step = _DEFAULT_QTY_STEP
        if max_qty < min_qty:
            max_qty = min_qty * Decimal("1000")

        price_filter = payload.get("priceFilter")
        min_price = _DECIMAL_ZERO
        max_price = _DECIMAL_ZERO
        tick_size = _DEFAULT_TICK_SIZE

        if isinstance(price_filter, dict):
            price_map = cast(ExchangePayload, price_filter)
            min_price = self._to_decimal(price_map.get("minPrice"))
            max_price = self._to_decimal(price_map.get("maxPrice"))
            parsed_tick = self._to_decimal(price_map.get("tickSize"))
            if parsed_tick > _DECIMAL_ZERO:
                tick_size = parsed_tick

        min_notional_val = self._to_decimal(payload.get("minNotionalValue"))
        min_notional = min_notional_val if min_notional_val > _DECIMAL_ZERO else None

        return ExchangeSymbolRules(
            symbol=symbol,
            market_min_quantity=min_qty,
            market_max_quantity=max_qty,
            market_quantity_step=qty_step,
            minimum_notional=min_notional,
            minimum_price=min_price,
            maximum_price=max_price,
            price_tick_size=tick_size,
        )

    def map_market_universe_entry(
        self,
        payload: ExchangePayload,
    ) -> MarketUniverseEntry:
        """Map Bybit V5 linear ticker payload into a MarketUniverseEntry."""
        symbol = self._to_string(payload.get("symbol")).strip().upper()
        turnover = self._to_decimal(payload.get("turnover24h"))
        volume = self._to_decimal(payload.get("volume24h"))
        quote_volume = turnover if turnover > _DECIMAL_ZERO else volume

        return MarketUniverseEntry(
            symbol=symbol,
            quote_volume=quote_volume,
        )
