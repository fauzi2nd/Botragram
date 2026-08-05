"""
Botragram

Description:
    Binance exchange payload mapper.

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
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide, OrderStatus, OrderType, PositionSide
from botragram.exchanges.base import BaseExchangeMapper
from botragram.exchanges.base.mapper import ExchangePayload, ExchangeSequencePayload
from botragram.models import Account, Balance, Candle, Order, Position, Ticker, Trade

__all__ = [
    "BinanceExchangeMapper",
]


# =============================================================================
# Binance Exchange Mapper
# =============================================================================
class BinanceExchangeMapper(BaseExchangeMapper):
    """Map Binance REST and WebSocket payloads into domain models."""

    def map_account(
        self,
        payload: ExchangePayload,
    ) -> Account:
        """Map a Binance account payload into an Account model."""
        raw_balances = self._require_list_field(
            payload,
            key="balances",
        )

        balances: tuple[Balance, ...] = tuple(
            self._map_balance(
                self._require_mapping(item),
            )
            for item in raw_balances
        )

        return Account(
            balances=balances,
            can_trade=self._to_bool(payload.get("canTrade")),
            can_deposit=self._to_bool(payload.get("canDeposit")),
            can_withdraw=self._to_bool(payload.get("canWithdraw")),
        )

    def map_ticker(
        self,
        payload: ExchangePayload,
    ) -> Ticker:
        """Map a Binance REST ticker payload into a Ticker model."""
        timestamp_value = payload.get("closeTime")

        return Ticker(
            symbol=self._to_string(payload.get("symbol")),
            bid_price=self._to_decimal(payload.get("bidPrice")),
            ask_price=self._to_decimal(payload.get("askPrice")),
            last_price=self._to_decimal(payload.get("lastPrice")),
            timestamp=(
                self._to_datetime(timestamp_value)
                if timestamp_value is not None
                else datetime.now(tz=UTC)
            ),
        )

    def map_stream_ticker(
        self,
        payload: ExchangePayload,
    ) -> Ticker:
        """Map a Binance WebSocket ticker payload into a Ticker model."""
        return Ticker(
            symbol=self._to_string(payload.get("s")),
            bid_price=self._to_decimal(payload.get("b")),
            ask_price=self._to_decimal(payload.get("a")),
            last_price=self._to_decimal(payload.get("c")),
            timestamp=self._to_datetime(payload.get("E")),
        )

    def map_candle(
        self,
        payload: ExchangeSequencePayload,
        *,
        symbol: str,
    ) -> Candle:
        """Map a Binance REST kline payload into a Candle model."""
        if len(payload) < 7:
            raise ValueError("Binance candle payload must contain at least 7 elements")

        return Candle(
            symbol=symbol,
            open_time=self._to_datetime(payload[0]),
            close_time=self._to_datetime(payload[6]),
            open_price=self._to_decimal(payload[1]),
            high_price=self._to_decimal(payload[2]),
            low_price=self._to_decimal(payload[3]),
            close_price=self._to_decimal(payload[4]),
            volume=self._to_decimal(payload[5]),
        )

    def map_stream_candle(
        self,
        payload: ExchangePayload,
    ) -> Candle:
        """Map a Binance WebSocket kline event into a Candle model."""
        raw_kline = self._require_mapping_field(
            payload,
            key="k",
        )

        symbol_value = raw_kline.get("s", payload.get("s"))

        return Candle(
            symbol=self._to_string(symbol_value),
            open_time=self._to_datetime(raw_kline.get("t")),
            close_time=self._to_datetime(raw_kline.get("T")),
            open_price=self._to_decimal(raw_kline.get("o")),
            high_price=self._to_decimal(raw_kline.get("h")),
            low_price=self._to_decimal(raw_kline.get("l")),
            close_price=self._to_decimal(raw_kline.get("c")),
            volume=self._to_decimal(raw_kline.get("v")),
        )

    def map_order(
        self,
        payload: ExchangePayload,
    ) -> Order:
        """Map a Binance order payload into an Order model."""
        created_at_value = payload.get(
            "time",
            payload.get("transactTime"),
        )
        updated_at_value = payload.get(
            "updateTime",
            created_at_value,
        )

        created_at = self._to_datetime(created_at_value)

        return Order(
            order_id=self._to_string(payload.get("orderId")),
            symbol=self._to_string(payload.get("symbol")),
            side=OrderSide(self._to_string(payload.get("side"))),
            order_type=OrderType(self._to_string(payload.get("type"))),
            status=OrderStatus(self._to_string(payload.get("status"))),
            quantity=self._to_decimal(payload.get("origQty")),
            executed_quantity=self._to_decimal(payload.get("executedQty")),
            price=self._to_decimal(payload.get("price")),
            stop_price=self._to_decimal(payload.get("stopPrice")),
            created_at=created_at,
            updated_at=(
                self._to_datetime(updated_at_value)
                if updated_at_value is not None
                else created_at
            ),
        )

    def map_position(
        self,
        payload: ExchangePayload,
    ) -> Position:
        """Map a Binance futures position into a Position model."""
        quantity = self._to_decimal(payload.get("positionAmt"))
        updated_at = self._to_datetime(payload.get("updateTime"))

        return Position(
            symbol=self._to_string(payload.get("symbol")),
            side=self._resolve_position_side(
                raw_side=payload.get("positionSide"),
                quantity=quantity,
            ),
            quantity=abs(quantity),
            entry_price=self._to_decimal(payload.get("entryPrice")),
            current_price=self._to_decimal(payload.get("markPrice")),
            unrealized_pnl=self._to_decimal(payload.get("unRealizedProfit")),
            leverage=self._to_int(payload.get("leverage")),
            opened_at=updated_at,
            updated_at=updated_at,
        )

    def map_trade(
        self,
        payload: ExchangePayload,
    ) -> Trade:
        """Map a Binance trade payload into a Trade model."""
        price = self._to_decimal(payload.get("price"))
        quantity = self._to_decimal(payload.get("qty"))
        quote_quantity_value = payload.get("quoteQty")

        quote_quantity = (
            self._to_decimal(quote_quantity_value)
            if quote_quantity_value is not None
            else price * quantity
        )

        return Trade(
            trade_id=self._to_string(payload.get("id")),
            order_id=self._to_string(payload.get("orderId")),
            symbol=self._to_string(payload.get("symbol")),
            side=self._resolve_trade_side(payload),
            price=price,
            quantity=quantity,
            quote_quantity=quote_quantity,
            fee=self._to_decimal(payload.get("commission")),
            fee_asset=self._to_string(payload.get("commissionAsset")),
            executed_at=self._to_datetime(payload.get("time")),
        )

    @staticmethod
    def _map_balance(
        payload: ExchangePayload,
    ) -> Balance:
        """Map a Binance balance entry."""
        return Balance(
            asset=BinanceExchangeMapper._to_string(payload.get("asset")),
            free=BinanceExchangeMapper._to_decimal(payload.get("free")),
            locked=BinanceExchangeMapper._to_decimal(payload.get("locked")),
        )

    @staticmethod
    def _resolve_position_side(
        *,
        raw_side: object,
        quantity: Decimal,
    ) -> PositionSide:
        """Resolve Binance position direction."""
        side_value = BinanceExchangeMapper._to_string(raw_side)

        if side_value in {"LONG", "SHORT"}:
            return PositionSide(side_value)

        if quantity < Decimal("0"):
            return PositionSide.SHORT

        return PositionSide.LONG

    @staticmethod
    def _resolve_trade_side(
        payload: ExchangePayload,
    ) -> OrderSide:
        """Resolve trade side from a Binance trade payload."""
        raw_side = payload.get("side")

        if raw_side is not None:
            return OrderSide(BinanceExchangeMapper._to_string(raw_side))

        return (
            OrderSide.BUY
            if BinanceExchangeMapper._to_bool(payload.get("isBuyer"))
            else OrderSide.SELL
        )

    @staticmethod
    def _require_mapping(
        value: object,
    ) -> ExchangePayload:
        """Return a mapping payload or raise ValueError."""
        if not isinstance(value, Mapping):
            raise ValueError("Expected a mapping payload")

        return cast(ExchangePayload, value)

    @staticmethod
    def _require_mapping_field(
        payload: ExchangePayload,
        *,
        key: str,
    ) -> ExchangePayload:
        """Return a mapping field or raise ValueError."""
        value = payload.get(key)

        if not isinstance(value, Mapping):
            raise ValueError(f"Expected '{key}' to contain a mapping")

        return cast(ExchangePayload, value)

    @staticmethod
    def _require_list_field(
        payload: ExchangePayload,
        *,
        key: str,
    ) -> list[object]:
        """Return a JSON list field or raise ValueError."""
        value = payload.get(key)

        if not isinstance(value, list):
            raise ValueError(f"Expected '{key}' to contain a list")

        return cast(list[object], value)

    @staticmethod
    def _to_datetime(
        value: object,
    ) -> datetime:
        """Convert a millisecond timestamp into UTC datetime."""
        timestamp_ms = BinanceExchangeMapper._to_int(value)

        return datetime.fromtimestamp(
            timestamp_ms / 1_000,
            tz=UTC,
        )

    @staticmethod
    def _to_decimal(
        value: object,
    ) -> Decimal:
        """Convert a payload value into Decimal."""
        if value is None or value == "":
            return Decimal("0")

        return Decimal(str(value))

    @staticmethod
    def _to_int(
        value: object,
    ) -> int:
        """Convert a payload value into int."""
        if value is None or value == "":
            return 0

        return int(str(value))

    @staticmethod
    def _to_string(
        value: object,
    ) -> str:
        """Convert a payload value into string."""
        if value is None:
            return ""

        return str(value)

    @staticmethod
    def _to_bool(
        value: object,
    ) -> bool:
        """Convert a payload value into bool."""
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            return value.lower() in {
                "1",
                "true",
                "yes",
            }

        return bool(value)
