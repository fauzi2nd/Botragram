"""
Botragram

Description:
    Bitget CFD payload mapper translating CFD vendor payloads into domain models.

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
from collections.abc import Mapping, Sequence
from dataclasses import replace
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
    Order,
    Position,
    Ticker,
    Trade,
)

__all__ = [
    "BitgetCfdMapper",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DEFAULT_TICK_SIZE: Final[Decimal] = Decimal("0.01")
_DEFAULT_MIN_QTY: Final[Decimal] = Decimal("0.01")
_DEFAULT_QTY_STEP: Final[Decimal] = Decimal("0.01")

_SIDE_MAP: Final[Mapping[str, OrderSide]] = {
    "BUY": OrderSide.BUY,
    "SELL": OrderSide.SELL,
}

_POSITION_SIDE_MAP: Final[Mapping[str, PositionSide]] = {
    "LONG": PositionSide.LONG,
    "SHORT": PositionSide.SHORT,
    "BUY": PositionSide.LONG,
    "SELL": PositionSide.SHORT,
}

_ORDER_TYPE_MAP: Final[Mapping[str, OrderType]] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "STOP": OrderType.STOP,
    "STOP_MARKET": OrderType.STOP_MARKET,
    "TAKE_PROFIT": OrderType.TAKE_PROFIT,
    "TAKE_PROFIT_MARKET": OrderType.TAKE_PROFIT_MARKET,
}

_STATUS_MAP: Final[Mapping[str, OrderStatus]] = {
    "INIT": OrderStatus.NEW,
    "NEW": OrderStatus.NEW,
    "OPEN": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELED,
    "CANCELED": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
}


# =============================================================================
# Bitget CFD Mapper Class
# =============================================================================
class BitgetCfdMapper(BaseExchangeMapper):
    """Payload mapper for Bitget CFD endpoints."""

    # =========================================================================
    # Symbol Formatting Helpers
    # =========================================================================

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Strip CFD mode suffixes (.s, .pro) to return base normalized symbol."""
        cleaned = symbol.strip().upper()
        if cleaned.endswith(".S"):
            return cleaned[:-2]
        if cleaned.endswith(".PRO"):
            return cleaned[:-4]
        return cleaned

    @staticmethod
    def to_vendor_symbol(symbol: str, *, mode: str = "ecn") -> str:
        """Convert standard symbol to vendor-specific instrument code.

        Args:
            symbol: Clean trading pair symbol (e.g. XAUUSD, EURUSD).
            mode: Trading account mode: 'zero_fee' (.s), 'pro' (.pro), or 'ecn'.

        Returns:
            Vendor-formatted symbol string.
        """
        cleaned = BitgetCfdMapper.normalize_symbol(symbol)
        match mode.strip().lower():
            case "zero_fee" | "zerofee" | "zero":
                return f"{cleaned}.s"
            case "pro":
                return f"{cleaned}.pro"
            case _:
                return cleaned

    # =========================================================================
    # Mapping Implementations
    # =========================================================================

    def map_account(self, payload: ExchangePayload) -> Account:
        """Map Bitget CFD account payload into an Account model."""
        balances: list[Balance] = []

        currency = self._to_string(payload.get("marginCoin", "USDT")).strip().upper()
        equity = self._to_decimal(
            payload.get("equity", payload.get("accountEquity", _DECIMAL_ZERO))
        )
        available = self._to_decimal(
            payload.get("available", payload.get("availBalance", _DECIMAL_ZERO))
        )
        locked = equity - available
        if locked < _DECIMAL_ZERO:
            locked = _DECIMAL_ZERO

        balances.append(
            Balance(
                asset=currency if currency else "USDT",
                free=available,
                locked=locked,
            )
        )

        return Account(
            balances=tuple(balances),
            can_trade=bool(payload.get("canTrade", True)),
            can_deposit=True,
            can_withdraw=True,
        )

    def map_ticker(self, payload: ExchangePayload) -> Ticker:
        """Map Bitget CFD ticker payload into Ticker model."""
        raw_symbol = self._to_string(payload.get("symbol")).strip().upper()
        symbol = self.normalize_symbol(raw_symbol)

        last_price = self._to_decimal(
            payload.get("lastPr", payload.get("lastPrice", _DECIMAL_ZERO))
        )
        bid_price = self._to_decimal(
            payload.get("bidPr", payload.get("bidPrice", last_price))
        )
        ask_price = self._to_decimal(
            payload.get("askPr", payload.get("askPrice", last_price))
        )

        if bid_price <= _DECIMAL_ZERO:
            bid_price = last_price
        if ask_price <= _DECIMAL_ZERO:
            ask_price = last_price

        timestamp = self._to_datetime(payload.get("ts", payload.get("timestamp")))

        return Ticker(
            symbol=symbol,
            bid_price=bid_price,
            ask_price=ask_price,
            last_price=last_price,
            timestamp=timestamp,
            funding_rate=None,
        )

    def map_candle(
        self,
        payload: ExchangeSequencePayload,
        *,
        symbol: str,
        interval: Interval,
    ) -> Candle:
        """Map Bitget CFD candle sequence into Candle model."""
        if len(payload) < 5:
            raise ValueError(
                f"Invalid Bitget CFD candle payload, expected >= 5: {payload}"
            )

        open_time = self._to_datetime(payload[0])
        close_time = open_time + timedelta(seconds=interval.seconds)
        open_price = self._to_decimal(payload[1])
        high_price = self._to_decimal(payload[2])
        low_price = self._to_decimal(payload[3])
        close_price = self._to_decimal(payload[4])
        volume = self._to_decimal(payload[5]) if len(payload) >= 6 else _DECIMAL_ZERO

        return Candle(
            symbol=self.normalize_symbol(symbol),
            interval=interval,
            open_time=open_time,
            close_time=close_time,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
        )

    def map_order(self, payload: ExchangePayload) -> Order:
        """Map Bitget CFD order payload into Order model."""
        order_id = self._to_string(
            payload.get("orderId", payload.get("order_id", ""))
        ).strip()
        client_order_id = (
            self._to_string(
                payload.get("clientOid", payload.get("clientOrderId", ""))
            ).strip()
            or None
        )
        symbol = self.normalize_symbol(
            self._to_string(payload.get("symbol")).strip().upper()
        )

        raw_side = self._to_string(payload.get("side")).strip().upper()
        side = _SIDE_MAP.get(raw_side, OrderSide.BUY)

        raw_order_type = (
            self._to_string(payload.get("orderType", payload.get("type", "MARKET")))
            .strip()
            .upper()
        )
        order_type = _ORDER_TYPE_MAP.get(raw_order_type, OrderType.MARKET)

        raw_status = (
            self._to_string(payload.get("status", payload.get("state", "NEW")))
            .strip()
            .upper()
        )
        status = _STATUS_MAP.get(raw_status, OrderStatus.NEW)

        price_raw = payload.get("price", payload.get("orderPrice"))
        price = self._to_decimal(price_raw) if price_raw is not None else None

        quantity = self._to_decimal(
            payload.get(
                "size", payload.get("quantity", payload.get("qty", _DECIMAL_ZERO))
            )
        )
        filled_quantity = self._to_decimal(
            payload.get(
                "filledQty",
                payload.get("cumQty", payload.get("dealSize", _DECIMAL_ZERO)),
            )
        )

        created_at = self._to_datetime(
            payload.get("cTime", payload.get("uTime", payload.get("ts")))
        )
        updated_at = self._to_datetime(
            payload.get("uTime", payload.get("cTime", payload.get("ts")))
        )

        raw_stop_price = payload.get(
            "triggerPrice",
            payload.get(
                "stopPrice", payload.get("stopLoss", payload.get("takeProfit"))
            ),
        )
        stop_price_val = self._to_decimal(raw_stop_price)
        stop_price = stop_price_val if stop_price_val > _DECIMAL_ZERO else None

        return Order(
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
            price=price,
            stop_price=stop_price,
            quantity=quantity,
            executed_quantity=filled_quantity,
            created_at=created_at,
            updated_at=updated_at,
        )

    def map_protection_orders(self, payload: ExchangePayload) -> Sequence[Order]:
        """Map Bitget CFD strategy/plan order payload into protection orders.

        If a CFD strategy order contains both stop-loss and take-profit legs,
        it is unpacked into two separate Order models with distinct client IDs.
        """
        raw_sl = payload.get("stopLoss")
        raw_tp = payload.get("takeProfit")
        if isinstance(raw_sl, dict):
            stop_loss_val = self._to_decimal(
                cast(dict[str, object], raw_sl).get("triggerPrice")
            )
        else:
            stop_loss_val = self._to_decimal(raw_sl)

        if isinstance(raw_tp, dict):
            take_profit_val = self._to_decimal(
                cast(dict[str, object], raw_tp).get("triggerPrice")
            )
        else:
            take_profit_val = self._to_decimal(raw_tp)

        if stop_loss_val > _DECIMAL_ZERO and take_profit_val > _DECIMAL_ZERO:
            base_order = self.map_order(payload)
            raw_client_id = (
                self._to_string(
                    payload.get("clientOid", payload.get("clientOrderId"))
                ).strip()
                or None
            )
            sl_client_id = (
                raw_client_id
                if raw_client_id is not None and not raw_client_id.startswith("btp-")
                else None
            )
            tp_client_id = (
                raw_client_id
                if raw_client_id is not None and not raw_client_id.startswith("bsl-")
                else None
            )

            sl_order = replace(
                base_order,
                order_id=f"{base_order.order_id}-sl" if base_order.order_id else "sl",
                client_order_id=sl_client_id,
                order_type=OrderType.STOP_MARKET,
                stop_price=stop_loss_val,
            )
            tp_order = replace(
                base_order,
                order_id=f"{base_order.order_id}-tp" if base_order.order_id else "tp",
                client_order_id=tp_client_id,
                order_type=OrderType.TAKE_PROFIT_MARKET,
                stop_price=take_profit_val,
            )
            return (sl_order, tp_order)

        base_order = self.map_order(payload)
        if stop_loss_val > _DECIMAL_ZERO:
            return (
                replace(
                    base_order,
                    order_type=OrderType.STOP_MARKET,
                    stop_price=stop_loss_val,
                ),
            )
        if take_profit_val > _DECIMAL_ZERO:
            return (
                replace(
                    base_order,
                    order_type=OrderType.TAKE_PROFIT_MARKET,
                    stop_price=take_profit_val,
                ),
            )
        return (base_order,)

    def map_position(self, payload: ExchangePayload) -> Position:
        """Map Bitget CFD position payload into Position model."""
        symbol = self.normalize_symbol(
            self._to_string(payload.get("symbol")).strip().upper()
        )

        raw_side = (
            self._to_string(payload.get("posSide", payload.get("side", "LONG")))
            .strip()
            .upper()
        )
        position_side = _POSITION_SIDE_MAP.get(raw_side, PositionSide.LONG)

        quantity = self._to_decimal(
            payload.get(
                "total",
                payload.get("holdAmount", payload.get("size", _DECIMAL_ZERO)),
            )
        )
        entry_price = self._to_decimal(
            payload.get(
                "openPriceAvg",
                payload.get("entryPrice", payload.get("avgPrice", _DECIMAL_ZERO)),
            )
        )
        current_price = self._to_decimal(
            payload.get("markPrice", payload.get("marketPrice", entry_price))
        )
        if current_price <= _DECIMAL_ZERO:
            current_price = entry_price

        unrealized_pnl = self._to_decimal(
            payload.get(
                "unrealizedPl",
                payload.get("upl", payload.get("unrealizedPnl", _DECIMAL_ZERO)),
            )
        )

        leverage_raw = payload.get("leverage")
        try:
            leverage = int(float(self._to_string(leverage_raw or "1")))
        except ValueError, TypeError:
            leverage = 1

        created_at = self._to_datetime(
            payload.get("cTime", payload.get("uTime", payload.get("ts")))
        )
        updated_at = self._to_datetime(
            payload.get("uTime", payload.get("cTime", payload.get("ts")))
        )

        return Position(
            symbol=symbol,
            side=position_side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            leverage=max(1, leverage),
            opened_at=created_at,
            updated_at=updated_at,
        )

    def map_trade(self, payload: ExchangePayload) -> Trade:
        """Map Bitget CFD trade / fill payload into Trade model."""
        trade_id = self._to_string(
            payload.get("tradeId", payload.get("fillId", ""))
        ).strip()
        order_id = self._to_string(payload.get("orderId", "")).strip()
        symbol = self.normalize_symbol(
            self._to_string(payload.get("symbol")).strip().upper()
        )

        raw_side = self._to_string(payload.get("side")).strip().upper()
        side = _SIDE_MAP.get(raw_side, OrderSide.BUY)

        price = self._to_decimal(
            payload.get("price", payload.get("fillPrice", _DECIMAL_ZERO))
        )
        quantity = self._to_decimal(
            payload.get("size", payload.get("fillQty", _DECIMAL_ZERO))
        )
        quote_quantity = self._to_decimal(payload.get("quoteVolume", price * quantity))
        fee = self._to_decimal(payload.get("fee", _DECIMAL_ZERO))
        fee_asset = self._to_string(payload.get("feeCoin", "USDT")).strip().upper()
        executed_at = self._to_datetime(
            payload.get("cTime", payload.get("ts", payload.get("fillTime")))
        )

        return Trade(
            trade_id=trade_id,
            order_id=order_id,
            symbol=symbol,
            side=side,
            price=price,
            quantity=quantity,
            quote_quantity=quote_quantity,
            fee=fee,
            fee_asset=fee_asset,
            executed_at=executed_at,
        )

    def map_symbol_rules(
        self,
        payload: ExchangePayload,
        *,
        symbol: str,
    ) -> ExchangeSymbolRules:
        """Map contract rules payload into ExchangeSymbolRules model."""
        tick_size = self._to_decimal(
            payload.get("pricePlace", payload.get("tickSize", _DEFAULT_TICK_SIZE))
        )
        min_qty = self._to_decimal(
            payload.get("minOrderNum", payload.get("minQty", _DEFAULT_MIN_QTY))
        )
        max_qty = self._to_decimal(
            payload.get("maxOrderNum", payload.get("maxQty", Decimal("1000000")))
        )
        step_size = self._to_decimal(
            payload.get("volumePlace", payload.get("stepSize", _DEFAULT_QTY_STEP))
        )

        return ExchangeSymbolRules(
            symbol=self.normalize_symbol(symbol),
            market_min_quantity=(
                min_qty if min_qty > _DECIMAL_ZERO else _DEFAULT_MIN_QTY
            ),
            market_max_quantity=(max_qty if max_qty >= min_qty else Decimal("1000000")),
            market_quantity_step=(
                step_size if step_size > _DECIMAL_ZERO else _DEFAULT_QTY_STEP
            ),
            price_tick_size=(
                tick_size if tick_size > _DECIMAL_ZERO else _DEFAULT_TICK_SIZE
            ),
        )

    # =========================================================================
    # Private Parsing Helpers
    # =========================================================================

    @staticmethod
    def _to_string(value: object | None) -> str:
        """Safely convert object to string."""
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _to_decimal(value: object | None) -> Decimal:
        """Safely convert string or numeric object to Decimal."""
        if value is None:
            return _DECIMAL_ZERO
        try:
            return Decimal(str(value).strip())
        except InvalidOperation, ValueError, TypeError:
            return _DECIMAL_ZERO

    @staticmethod
    def _to_datetime(value: object | None) -> datetime:
        """Safely convert epoch timestamp (ms or s) to UTC datetime."""
        if value is None:
            return datetime.now(timezone.utc)
        try:
            numeric_val = float(str(value).strip())
            # Convert milliseconds to seconds if value > 1e11
            if numeric_val > 100_000_000_000:
                numeric_val /= 1000.0
            return datetime.fromtimestamp(numeric_val, tz=timezone.utc)
        except ValueError, TypeError, OSError:
            return datetime.now(timezone.utc)
