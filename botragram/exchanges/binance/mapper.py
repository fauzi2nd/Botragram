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
from decimal import Decimal, InvalidOperation
from typing import cast

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, OrderSide, OrderStatus, OrderType, PositionSide
from botragram.exchanges.base import BaseExchangeMapper
from botragram.exchanges.base.mapper import ExchangePayload, ExchangeSequencePayload
from botragram.models import (
    Account,
    Balance,
    Candle,
    ExchangeSymbolRules,
    ExecutableQuote,
    MarketUniverseEntry,
    Order,
    Position,
    Ticker,
    Trade,
)

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

    def map_futures_account(
        self,
        payload: ExchangePayload,
    ) -> Account:
        """Map a Binance USD(S)-M Futures account payload."""
        raw_assets = self._require_list_field(
            payload,
            key="assets",
        )
        balances = tuple(
            self._map_futures_balance(self._require_mapping(item))
            for item in raw_assets
        )

        return Account(
            balances=balances,
            can_trade=self._to_bool(payload.get("canTrade")),
            can_deposit=False,
            can_withdraw=False,
        )

    def map_ticker(
        self,
        payload: ExchangePayload,
    ) -> Ticker:
        """Map a Binance REST ticker payload into a Ticker model."""
        timestamp_value = payload.get("closeTime")
        if timestamp_value is None or timestamp_value == "":
            raise ValueError(
                "Binance REST ticker payload must contain a valid closeTime"
            )

        return Ticker(
            symbol=self._to_string(payload.get("symbol")),
            bid_price=self._to_decimal(payload.get("bidPrice")),
            ask_price=self._to_decimal(payload.get("askPrice")),
            last_price=self._to_decimal(payload.get("lastPrice")),
            timestamp=self._to_datetime(timestamp_value),
        )

    def map_futures_executable_quote(
        self,
        payload: ExchangePayload,
    ) -> ExecutableQuote:
        """Map a Binance Futures book ticker into an executable quote."""
        timestamp_value = payload.get("time")
        if timestamp_value is None or timestamp_value == "":
            raise ValueError(
                "Binance Futures book ticker payload must contain a valid time"
            )

        return ExecutableQuote(
            symbol=self._to_string(payload.get("symbol")),
            bid_price=self._to_required_decimal(payload, key="bidPrice"),
            ask_price=self._to_required_decimal(payload, key="askPrice"),
            timestamp=self._to_datetime(timestamp_value),
        )

    def map_market_universe_entry(
        self,
        payload: ExchangePayload,
    ) -> MarketUniverseEntry:
        """Map one Binance bulk 24-hour ticker into a market-universe fact."""
        return MarketUniverseEntry(
            symbol=self._to_string(payload.get("symbol")),
            quote_volume=self._to_required_decimal(payload, key="quoteVolume"),
        )

    def map_market_entry_rules(self, payload: ExchangePayload) -> ExchangeSymbolRules:
        """Map Binance exchangeInfo filters into typed Futures symbol rules."""
        raw_filters = self._require_list_field(payload, key="filters")
        filters = {
            self._to_string(
                self._require_mapping(item).get("filterType")
            ): self._require_mapping(item)
            for item in raw_filters
        }
        market_filter = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE")
        if market_filter is None:
            raise ValueError("Binance symbol has no MARKET quantity filter")
        price_filter = filters.get("PRICE_FILTER")
        if price_filter is None:
            raise ValueError("Binance symbol has no PRICE_FILTER")
        minimum_notional = filters.get("MIN_NOTIONAL")
        return ExchangeSymbolRules(
            symbol=self._to_string(payload.get("symbol")),
            market_min_quantity=self._to_decimal(market_filter.get("minQty")),
            market_max_quantity=self._to_decimal(market_filter.get("maxQty")),
            market_quantity_step=self._to_decimal(market_filter.get("stepSize")),
            minimum_notional=(
                self._to_decimal(minimum_notional.get("notional"))
                if minimum_notional is not None
                else None
            ),
            minimum_price=self._to_decimal(price_filter.get("minPrice")),
            maximum_price=self._to_decimal(price_filter.get("maxPrice")),
            price_tick_size=self._to_decimal(price_filter.get("tickSize")),
        )

    def map_futures_mark_price(self, payload: ExchangePayload) -> Decimal:
        """Map Binance Futures premium-index payload into a MARK_PRICE value."""
        return self._to_decimal(payload.get("markPrice"))

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
        interval: Interval,
    ) -> Candle:
        """Map a Binance REST kline payload into a Candle model."""
        if len(payload) < 7:
            raise ValueError("Binance candle payload must contain at least 7 elements")

        return Candle(
            symbol=symbol,
            interval=interval,
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
            interval=Interval(self._to_string(raw_kline.get("i"))),
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
            order_type=OrderType(
                self._to_string(payload.get("type")).lower(),
            ),
            status=OrderStatus(
                self._to_string(payload.get("status")).lower(),
            ),
            quantity=self._to_decimal(payload.get("origQty")),
            executed_quantity=self._to_decimal(payload.get("executedQty")),
            price=self._to_optional_decimal(payload.get("price")),
            stop_price=self._to_optional_decimal(payload.get("stopPrice")),
            created_at=created_at,
            updated_at=(
                self._to_datetime(updated_at_value)
                if updated_at_value is not None
                else created_at
            ),
            client_order_id=self._to_optional_string(payload.get("clientOrderId")),
        )

    def map_algo_order(
        self,
        payload: ExchangePayload,
    ) -> Order:
        """Map a Binance Futures conditional algo order payload."""
        created_at_value = payload.get(
            "createTime",
            payload.get("time", payload.get("transactTime")),
        )
        created_at = self._to_datetime(created_at_value)
        updated_at_value = payload.get("updateTime", created_at_value)

        return Order(
            order_id=self._to_string(payload.get("algoId", payload.get("orderId"))),
            symbol=self._to_string(payload.get("symbol")),
            side=OrderSide(self._to_string(payload.get("side"))),
            order_type=OrderType(
                self._to_string(payload.get("orderType", payload.get("type"))).lower(),
            ),
            status=self._map_algo_order_status(
                payload.get("algoStatus", payload.get("status"))
            ),
            quantity=self._to_decimal(payload.get("quantity", payload.get("origQty"))),
            executed_quantity=self._to_decimal(
                payload.get(
                    "actualQty",
                    payload.get("actualQuantity", payload.get("executedQty")),
                )
            ),
            price=self._to_optional_decimal(
                payload.get("algoPrice", payload.get("price"))
            ),
            stop_price=self._to_optional_decimal(
                payload.get("triggerPrice", payload.get("stopPrice"))
            ),
            created_at=created_at,
            updated_at=(
                self._to_datetime(updated_at_value)
                if updated_at_value is not None
                else created_at
            ),
            client_order_id=self._to_optional_string(payload.get("clientAlgoId")),
        )

    @staticmethod
    def _map_algo_order_status(value: object) -> OrderStatus:
        """Normalize Binance conditional-algo lifecycle states.

        Binance USD-M conditional orders expose algo-specific states in addition
        to standard order statuses. ``ACTIVE`` remains open protection, while
        ``TRIGGERED`` means the conditional leg has already fired and is mapped
        to an in-progress status so protection recovery cannot mistake it for a
        still-pending trigger. ``FINISHED`` is normalized to FILLED.
        """
        normalized = BinanceExchangeMapper._to_string(value).strip().lower()

        if normalized == "active":
            return OrderStatus.NEW

        if normalized == "triggered":
            return OrderStatus.PARTIALLY_FILLED

        if normalized == "finished":
            return OrderStatus.FILLED

        if normalized == "failed":
            return OrderStatus.REJECTED

        return OrderStatus(normalized)

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
    def _map_futures_balance(
        payload: ExchangePayload,
    ) -> Balance:
        """Map one collateral asset from a Futures account payload."""
        wallet_balance = BinanceExchangeMapper._to_decimal(payload.get("walletBalance"))
        available_balance = BinanceExchangeMapper._to_decimal(
            payload.get("availableBalance")
        )

        return Balance(
            asset=BinanceExchangeMapper._to_string(payload.get("asset")),
            free=available_balance,
            locked=max(wallet_balance - available_balance, Decimal("0")),
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
            return PositionSide(side_value.lower())

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
    def _to_required_decimal(
        payload: ExchangePayload,
        *,
        key: str,
    ) -> Decimal:
        """Convert a required decimal payload field without a zero fallback."""
        value = payload.get(key)
        if value is None or value == "":
            raise ValueError(f"Binance payload must contain a valid {key}")

        try:
            return Decimal(str(value))
        except InvalidOperation as error:
            raise ValueError(f"Binance payload contains an invalid {key}") from error

    @staticmethod
    def _to_optional_decimal(
        value: object,
    ) -> Decimal | None:
        """Convert an optional payload value into Decimal."""
        if value is None or value == "":
            return None

        result = Decimal(str(value))

        if result == Decimal("0"):
            return None

        return result

    @staticmethod
    def _to_optional_string(value: object) -> str | None:
        """Convert an optional payload identifier into a non-empty string."""
        if value is None:
            return None

        normalized = str(value).strip()
        return normalized or None

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
