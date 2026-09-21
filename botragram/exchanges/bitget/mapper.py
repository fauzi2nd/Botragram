"""
Botragram

Description:
    Bitget V2 payload mapper translating vendor payloads into domain models.

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
    MarketUniverseEntry,
    Order,
    Position,
    Ticker,
    Trade,
)

__all__ = [
    "BitgetExchangeMapper",
    "BitgetMapper",
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
    "PLAN": OrderType.STOP,
    "TAKE_PROFIT": OrderType.TAKE_PROFIT,
    "TAKE_PROFIT_MARKET": OrderType.TAKE_PROFIT_MARKET,
    "TPSL": OrderType.STOP_MARKET,
}

_STATUS_MAP: Final[Mapping[str, OrderStatus]] = {
    "INIT": OrderStatus.NEW,
    "NEW": OrderStatus.NEW,
    "NOT_TRIGGER": OrderStatus.NEW,
    "UNTRIGGERED": OrderStatus.NEW,
    "PENDING": OrderStatus.NEW,
    "LIVE": OrderStatus.NEW,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "PARTIAL_FILL": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "FULL_FILL": OrderStatus.FILLED,
    "EXECUTED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELED,
    "CANCELED": OrderStatus.CANCELED,
    "FAIL": OrderStatus.REJECTED,
    "FAILED": OrderStatus.REJECTED,
    "REJECTED": OrderStatus.REJECTED,
}

_INTERVAL_MAP: Final[Mapping[Interval, str]] = {
    Interval.M1: "1m",
    Interval.M3: "3m",
    Interval.M5: "5m",
    Interval.M15: "15m",
    Interval.M30: "30m",
    Interval.H1: "1H",
    Interval.H2: "2H",
    Interval.H4: "4H",
    Interval.H6: "6H",
    Interval.H12: "12H",
    Interval.D1: "1D",
    Interval.W1: "1W",
    Interval.MN1: "1M",
}


# =============================================================================
# Mapper Implementation
# =============================================================================
class BitgetExchangeMapper(BaseExchangeMapper):
    """Translate Bitget V2 payloads into Botragram domain models."""

    __slots__ = ()

    def to_exchange_interval(self, interval: Interval) -> str:
        """Map canonical interval enum to Bitget granularity string."""
        granularity = _INTERVAL_MAP.get(interval)
        if granularity is None:
            raise ValueError(f"Unsupported Bitget interval: {interval.value}")
        return granularity

    def map_candle(
        self,
        payload: ExchangeSequencePayload,
        *,
        symbol: str,
        interval: Interval,
    ) -> Candle:
        """Map Bitget V2 candle sequence into Candle model.

        Format: [ts, open, high, low, close, base_volume, quote_volume]
        """
        if len(payload) < 6:
            raise ValueError(
                f"Bitget candle payload must contain at least 6 elements: {payload}"
            )

        open_time = self._to_datetime(payload[0])
        close_time = open_time + timedelta(seconds=interval.seconds)

        open_price = self._to_decimal(payload[1])
        high_price = self._to_decimal(payload[2])
        low_price = self._to_decimal(payload[3])
        close_price = self._to_decimal(payload[4])
        volume = self._to_decimal(payload[5])

        return Candle(
            symbol=symbol.strip().upper(),
            interval=interval,
            open_time=open_time,
            close_time=close_time,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
        )

    def map_ticker(self, payload: ExchangePayload) -> Ticker:
        """Map Bitget V2 ticker payload into Ticker model."""
        symbol = self._to_string(payload.get("symbol")).strip().upper()
        last_price = self._to_decimal(payload.get("lastPr"))
        bid_price = self._to_decimal(payload.get("bidPr", last_price))
        ask_price = self._to_decimal(payload.get("askPr", last_price))

        if bid_price <= _DECIMAL_ZERO:
            bid_price = last_price
        if ask_price <= _DECIMAL_ZERO:
            ask_price = last_price

        timestamp = self._to_datetime(payload.get("ts"))

        raw_funding = payload.get("fundingRate")
        funding_rate = (
            self._to_decimal(raw_funding)
            if raw_funding is not None and raw_funding != ""
            else None
        )

        return Ticker(
            symbol=symbol,
            bid_price=bid_price,
            ask_price=ask_price,
            last_price=last_price,
            timestamp=timestamp,
            funding_rate=funding_rate,
        )

    def map_order(self, payload: ExchangePayload) -> Order:
        """Map Bitget V2 order payload into Order model."""
        order_id = self._to_string(
            payload.get("orderId", payload.get("planOrderId"))
        ).strip()
        client_order_id = (
            self._to_string(
                payload.get("clientOid", payload.get("clientOrderId"))
            ).strip()
            or None
        )
        symbol = self._to_string(payload.get("symbol")).strip().upper()

        raw_side = self._to_string(payload.get("side")).strip().upper()
        if raw_side in _SIDE_MAP:
            side = _SIDE_MAP[raw_side]
        else:
            # Plan / Strategy orders on Bitget specify posSide instead of side.
            # A stop-loss or take-profit order closing a LONG position has side SELL,
            # and closing a SHORT position has side BUY.
            pos_side = (
                self._to_string(payload.get("posSide", payload.get("holdSide")))
                .strip()
                .upper()
            )
            if pos_side == "LONG":
                side = OrderSide.SELL
            elif pos_side == "SHORT":
                side = OrderSide.BUY
            else:
                side = OrderSide.BUY

        raw_type = (
            self._to_string(
                payload.get("orderType", payload.get("planType", payload.get("type")))
            )
            .strip()
            .upper()
        )
        # planType classifies the trigger intent (pos_loss / pos_profit) independently
        # of orderType, which describes only the execution order type (market / limit).
        raw_plan_type = self._to_string(payload.get("planType", "")).strip().upper()

        # stopLoss / takeProfit may arrive as a plain price string or as a nested
        # object {"triggerPrice": ..., "triggerType": ..., "orderType": ...}.
        raw_sl = payload.get("stopLoss")
        raw_tp = payload.get("takeProfit")
        stop_loss_val = (
            self._to_decimal(cast(dict[str, object], raw_sl).get("triggerPrice"))
            if isinstance(raw_sl, dict)
            else self._to_decimal(raw_sl)
        )
        take_profit_val = (
            self._to_decimal(cast(dict[str, object], raw_tp).get("triggerPrice"))
            if isinstance(raw_tp, dict)
            else self._to_decimal(raw_tp)
        )
        trigger_price_val = self._to_decimal(payload.get("triggerPrice"))

        if stop_loss_val > _DECIMAL_ZERO:
            order_type = OrderType.STOP_MARKET
            stop_price: Decimal | None = stop_loss_val
        elif take_profit_val > _DECIMAL_ZERO:
            order_type = OrderType.TAKE_PROFIT_MARKET
            stop_price = take_profit_val
        elif trigger_price_val > _DECIMAL_ZERO:
            # orderType in plan-order responses describes the post-trigger execution
            # style ("market", "limit") — not whether it is a stop-loss or take-profit.
            # Use planType for accurate classification.
            if raw_plan_type in (
                "POS_LOSS",
                "LOSS_PLAN",
                "STOP_LOSS",
                "LOSS",
                "TRIGGERED_SL",
                "NORMAL_PLAN",
            ):
                order_type = OrderType.STOP_MARKET
            elif raw_plan_type in (
                "POS_PROFIT",
                "PROFIT_PLAN",
                "TAKE_PROFIT",
                "PROFIT",
                "TRIGGERED_TP",
            ):
                order_type = OrderType.TAKE_PROFIT_MARKET
            else:
                # Fall back to the type map; if it resolves to a plain execution
                # type (MARKET / LIMIT), default to STOP_MARKET so a triggered
                # plan order is never classified as a vanilla market/limit order.
                mapped = _ORDER_TYPE_MAP.get(raw_type, OrderType.STOP_MARKET)
                order_type = (
                    OrderType.STOP_MARKET
                    if mapped in (OrderType.MARKET, OrderType.LIMIT)
                    else mapped
                )
            stop_price = trigger_price_val
        else:
            order_type = _ORDER_TYPE_MAP.get(raw_type, OrderType.MARKET)
            stop_price = None

        raw_status = (
            self._to_string(
                payload.get(
                    "status",
                    payload.get(
                        "orderStatus",
                        payload.get("state", payload.get("planStatus")),
                    ),
                )
            )
            .strip()
            .upper()
        )
        status = _STATUS_MAP.get(raw_status, OrderStatus.NEW)

        price_val = self._to_decimal(payload.get("price", payload.get("executePrice")))
        price = price_val if price_val > _DECIMAL_ZERO else None

        quantity = self._to_decimal(
            payload.get("qty", payload.get("size", payload.get("quantity")))
        )
        exec_qty = self._to_decimal(
            payload.get("cumQty", payload.get("baseVolume", payload.get("cumExecQty")))
        )

        created_at = self._to_datetime(payload.get("cTime", payload.get("createdTime")))
        updated_at = self._to_datetime(
            payload.get("uTime", payload.get("updatedTime", payload.get("cTime")))
        )

        if order_type is OrderType.TAKE_PROFIT_MARKET and client_order_id is not None:
            if client_order_id.startswith("bsl-"):
                client_order_id = None
        elif order_type is OrderType.STOP_MARKET and client_order_id is not None:
            if client_order_id.startswith("btp-"):
                client_order_id = None

        return Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=status,
            quantity=quantity,
            executed_quantity=exec_qty,
            price=price,
            stop_price=stop_price,
            client_order_id=client_order_id,
            created_at=created_at,
            updated_at=updated_at,
        )

    def map_protection_orders(self, payload: ExchangePayload) -> Sequence[Order]:
        """Map Bitget strategy/plan order payload into protection orders.

        A Bitget 'tpsl' strategy order may carry both stop-loss and take-profit
        legs within a single record. This method unpacks both legs into separate
        Order instances when both are present.
        """
        raw_sl = payload.get("stopLoss")
        raw_tp = payload.get("takeProfit")
        stop_loss_val = (
            self._to_decimal(cast(dict[str, object], raw_sl).get("triggerPrice"))
            if isinstance(raw_sl, dict)
            else self._to_decimal(raw_sl)
        )
        take_profit_val = (
            self._to_decimal(cast(dict[str, object], raw_tp).get("triggerPrice"))
            if isinstance(raw_tp, dict)
            else self._to_decimal(raw_tp)
        )

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

        return (self.map_order(payload),)

    def map_position(self, payload: ExchangePayload) -> Position:
        """Map Bitget V2/V3 position payload into Position model."""
        symbol = self._to_string(payload.get("symbol")).strip().upper()

        raw_side = (
            self._to_string(payload.get("holdSide", payload.get("posSide")))
            .strip()
            .upper()
        )
        side = _POSITION_SIDE_MAP.get(raw_side, PositionSide.LONG)

        quantity = self._to_decimal(
            payload.get("total", payload.get("size", payload.get("available")))
        )
        entry_price = self._to_decimal(
            payload.get("openPriceAvg", payload.get("avgPrice"))
        )
        current_price = self._to_decimal(
            payload.get("markPrice", payload.get("marketPrice"))
        )
        if current_price <= _DECIMAL_ZERO:
            current_price = entry_price

        unrealized_pnl = self._to_decimal(payload.get("unrealizedPL"))

        leverage_raw = payload.get("leverage")
        try:
            leverage = int(float(self._to_string(leverage_raw or "1")))
        except ValueError, TypeError:
            leverage = 1

        created_at = self._to_datetime(payload.get("cTime"))
        updated_at = self._to_datetime(payload.get("uTime", payload.get("cTime")))

        return Position(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            leverage=max(1, leverage),
            opened_at=created_at,
            updated_at=updated_at,
        )

    def map_account(self, payload: ExchangePayload) -> Account:
        """Map Bitget V2/V3 account/balance payload into Account model."""
        balances: list[Balance] = []

        data = payload.get("data")
        raw_list: list[object]
        if isinstance(data, list):
            raw_list = cast(list[object], data)
        elif isinstance(data, dict):
            dict_data = cast(dict[str, object], data)
            inner_list = dict_data.get("list", dict_data.get("assets"))
            if isinstance(inner_list, list):
                raw_list = cast(list[object], inner_list)
            else:
                raw_list = [dict_data]
        else:
            raw_list = [payload]

        for item in raw_list:
            if not isinstance(item, dict):
                continue
            item_dict = cast(ExchangePayload, item)
            asset = (
                self._to_string(item_dict.get("marginCoin", item_dict.get("coin")))
                .strip()
                .upper()
            )
            if not asset:
                continue

            available = self._to_decimal(
                item_dict.get("available", item_dict.get("maxTransferOut"))
            )
            locked = self._to_decimal(item_dict.get("frozen", item_dict.get("locked")))
            balances.append(
                Balance(
                    asset=asset,
                    free=available,
                    locked=locked,
                )
            )

        if not balances:
            balances.append(
                Balance(
                    asset="USDT",
                    free=_DECIMAL_ZERO,
                    locked=_DECIMAL_ZERO,
                )
            )

        return Account(
            balances=tuple(balances),
            can_trade=True,
            can_deposit=True,
            can_withdraw=True,
        )

    def map_trade(self, payload: ExchangePayload) -> Trade:
        """Map Bitget V2 trade/fills payload into Trade model."""
        trade_id = self._to_string(
            payload.get("tradeId", payload.get("fillId", payload.get("execId")))
        ).strip()
        order_id = self._to_string(payload.get("orderId")).strip()
        symbol = self._to_string(payload.get("symbol")).strip().upper()

        raw_side = self._to_string(payload.get("side")).strip().upper()
        side = _SIDE_MAP.get(raw_side, OrderSide.BUY)

        price = self._to_decimal(
            payload.get("price", payload.get("fillPrice", payload.get("execPrice")))
        )
        qty = self._to_decimal(
            payload.get(
                "size",
                payload.get(
                    "baseVolume",
                    payload.get("execQty", payload.get("qty")),
                ),
            )
        )
        quote_qty = self._to_decimal(
            payload.get("execValue", payload.get("quoteVolume"))
        )
        if quote_qty <= _DECIMAL_ZERO:
            quote_qty = price * qty

        raw_fee = payload.get("fee", payload.get("fillFee"))
        raw_fee_currency = payload.get("feeCurrency", payload.get("feeCoin"))
        fee_detail = payload.get("feeDetail")
        if raw_fee is None and isinstance(fee_detail, list) and fee_detail:
            first_fee = cast(list[object], fee_detail)[0]
            if isinstance(first_fee, dict):
                fee_dict = cast(dict[str, object], first_fee)
                raw_fee = fee_dict.get("fee")
                if raw_fee_currency is None:
                    raw_fee_currency = fee_dict.get("feeCoin")

        fee = self._to_decimal(raw_fee)
        fee_asset = self._to_string(raw_fee_currency or "USDT").strip().upper()

        executed_at = self._to_datetime(
            payload.get(
                "cTime",
                payload.get(
                    "createdTime",
                    payload.get(
                        "fillTime",
                        payload.get("uTime", payload.get("updatedTime")),
                    ),
                ),
            )
        )
        pnl_val = payload.get("pnl", payload.get("realizedPnl", payload.get("execPnl")))
        realized_pnl = (
            self._to_decimal(pnl_val)
            if pnl_val is not None and str(pnl_val).strip() != ""
            else None
        )

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
            realized_pnl=realized_pnl,
            is_liquidation=False,
        )

    def map_symbol_rules(self, payload: ExchangePayload) -> ExchangeSymbolRules:
        """Map Bitget V2 contract info payload into ExchangeSymbolRules."""
        symbol = self._to_string(payload.get("symbol")).strip().upper()

        min_qty = self._to_decimal(
            payload.get("minTradeNum", payload.get("minOrderNum")),
            _DEFAULT_MIN_QTY,
        )
        max_qty = self._to_decimal(
            payload.get("maxOrderQty", payload.get("maxOrderNum")),
            Decimal("1000000"),
        )
        qty_step = self._to_decimal(
            payload.get("sizeMultiplier"),
            _DEFAULT_QTY_STEP,
        )

        price_place_raw = payload.get("pricePlace")
        price_place = int(self._to_decimal(price_place_raw, Decimal("4")))
        price_tick = (
            Decimal(10) ** (-price_place) if price_place >= 0 else _DEFAULT_TICK_SIZE
        )

        min_notional_raw = payload.get("minTradeUSDT")
        min_notional = (
            self._to_decimal(min_notional_raw) if min_notional_raw is not None else None
        )

        return ExchangeSymbolRules(
            symbol=symbol,
            market_min_quantity=min_qty,
            market_max_quantity=max_qty,
            market_quantity_step=qty_step,
            minimum_notional=min_notional,
            minimum_price=_DECIMAL_ZERO,
            maximum_price=_DECIMAL_ZERO,
            price_tick_size=price_tick,
        )

    def map_market_universe_entry(
        self,
        payload: ExchangePayload,
    ) -> MarketUniverseEntry:
        """Map Bitget V2 ticker payload into MarketUniverseEntry."""
        symbol = self._to_string(payload.get("symbol")).strip().upper()
        turnover = self._to_decimal(
            payload.get("quoteVolume", payload.get("usdtVolume"))
        )
        volume = self._to_decimal(payload.get("baseVolume"))
        quote_volume = turnover if turnover > _DECIMAL_ZERO else volume
        bid_price = self._to_optional_decimal(payload.get("bidPr"))
        ask_price = self._to_optional_decimal(payload.get("askPr"))

        return MarketUniverseEntry(
            symbol=symbol,
            quote_volume=quote_volume,
            bid_price=bid_price,
            ask_price=ask_price,
        )

    # -------------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _to_string(value: object) -> str:
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _to_decimal(value: object, default: Decimal = _DECIMAL_ZERO) -> Decimal:
        if value is None:
            return default
        try:
            return Decimal(str(value))
        except InvalidOperation, TypeError, ValueError:
            return default

    @staticmethod
    def _to_optional_decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation, TypeError, ValueError:
            return None

    @staticmethod
    def _to_datetime(value: object) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if isinstance(value, datetime):
            return (
                value
                if value.tzinfo is not None
                else value.replace(tzinfo=timezone.utc)
            )

        text = str(value).strip()
        if text.isdigit():
            val = int(text)
            if val < 100_000_000_000:
                return datetime.fromtimestamp(val, tz=timezone.utc)
            return datetime.fromtimestamp(val / 1000, tz=timezone.utc)

        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)


# =============================================================================
# Aliases
# =============================================================================
BitgetMapper: Final[type[BitgetExchangeMapper]] = BitgetExchangeMapper
