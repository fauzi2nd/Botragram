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
from botragram.engine.market_calendar import MarketCalendarEngine
from botragram.enums import (
    AssetClass,
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
    CfdContractSpec,
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

    __slots__ = ("_calendar",)

    def __init__(self, calendar: MarketCalendarEngine | None = None) -> None:
        """Initialize the Bitget CFD mapper with an optional calendar."""
        self._calendar = calendar if calendar is not None else MarketCalendarEngine()

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
            case "ecn":
                return cleaned
            case _:
                raise ValueError(
                    f"Invalid CFD mode: {mode!r}. Accepted values are: "
                    "'ecn', 'zero_fee', 'pro'."
                )

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
        if not order_id:
            raise ValueError("Bitget CFD order payload missing required orderId")

        client_order_id = (
            self._to_string(
                payload.get("clientOid", payload.get("clientOrderId", ""))
            ).strip()
            or None
        )
        trx_id = (
            self._to_string(payload.get("trxId", payload.get("trx_id", ""))).strip()
            or None
        )
        execution_order_id = (
            self._to_string(
                payload.get("executionOrderId", payload.get("execution_order_id", ""))
            ).strip()
            or trx_id
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
                "qty", payload.get("size", payload.get("quantity", _DECIMAL_ZERO))
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
            execution_order_id=execution_order_id,
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
            self._to_string(payload.get("side", payload.get("posSide", "LONG")))
            .strip()
            .upper()
        )
        position_side = _POSITION_SIDE_MAP.get(raw_side, PositionSide.LONG)

        quantity = self._to_decimal(
            payload.get(
                "qty",
                payload.get(
                    "total",
                    payload.get("holdAmount", payload.get("size", _DECIMAL_ZERO)),
                ),
            )
        )
        entry_price = self._to_decimal(
            payload.get(
                "openPrice",
                payload.get(
                    "openPriceAvg",
                    payload.get("entryPrice", payload.get("avgPrice", _DECIMAL_ZERO)),
                ),
            )
        )
        current_price = self._to_decimal(
            payload.get("markPrice", payload.get("marketPrice", entry_price))
        )
        if current_price <= _DECIMAL_ZERO:
            current_price = entry_price

        unrealized_pnl = self._to_decimal(
            payload.get(
                "unrealizedPnl",
                payload.get(
                    "unrealizedPl",
                    payload.get("upl", payload.get("totalProfit", _DECIMAL_ZERO)),
                ),
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

        raw_pos_id = self._to_string(
            payload.get("positionId", payload.get("posId", ""))
        ).strip()
        position_id = raw_pos_id if raw_pos_id else None

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
            position_id=position_id,
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

    def map_instrument_spec(self, payload: ExchangePayload) -> CfdContractSpec:
        """Map Bitget CFD instrument metadata payload into CfdContractSpec model."""
        raw_symbol = self._to_string(payload.get("symbol")).strip()
        if not raw_symbol:
            raise ValueError("Instrument payload missing symbol")
        symbol = self.normalize_symbol(raw_symbol)
        asset_class = self._calendar.classify_asset(symbol)

        contract_size = self._to_decimal(
            payload.get("contractSize", payload.get("contract_size", _DECIMAL_ZERO))
        )
        min_lot = self._to_decimal(
            payload.get(
                "minVolume",
                payload.get(
                    "min_volume",
                    payload.get("minLots", payload.get("min_lot", _DECIMAL_ZERO)),
                ),
            )
        )
        max_lot = self._to_decimal(
            payload.get(
                "maxVolume",
                payload.get(
                    "max_volume",
                    payload.get("maxLots", payload.get("max_lot", _DECIMAL_ZERO)),
                ),
            )
        )
        lot_step = self._to_decimal(
            payload.get(
                "stepVolume",
                payload.get(
                    "step_volume",
                    payload.get("lotStep", payload.get("lot_step", _DECIMAL_ZERO)),
                ),
            )
        )
        tick_size = self._to_decimal(
            payload.get("tickSize", payload.get("tick_size", _DECIMAL_ZERO))
        )

        leverage_raw = payload.get("leverage", payload.get("maxLeverage", 100))
        try:
            leverage = int(float(self._to_string(leverage_raw)))
        except ValueError, TypeError:
            leverage = 100

        max_lev_raw = payload.get("maxLeverage", payload.get("leverage", leverage))
        try:
            max_leverage = int(float(self._to_string(max_lev_raw)))
        except ValueError, TypeError:
            max_leverage = leverage
        if max_leverage < leverage:
            max_leverage = leverage

        trade_time = (
            self._to_string(
                payload.get("tradeTime", payload.get("trade_time", ""))
            ).strip()
            or None
        )
        margin_currency = (
            self._to_string(
                payload.get("marginCurrency", payload.get("margin_currency", ""))
            )
            .strip()
            .upper()
            or None
        )
        profit_currency = (
            self._to_string(
                payload.get("profitCurrency", payload.get("profit_currency", ""))
            )
            .strip()
            .upper()
            or None
        )
        price_currency = (
            self._to_string(
                payload.get("priceCurrency", payload.get("price_currency", ""))
            )
            .strip()
            .upper()
            or None
        )

        ex_rate_raw = payload.get("exchangeRate", payload.get("exchange_rate"))
        exchange_rate = (
            self._to_decimal(ex_rate_raw) if ex_rate_raw is not None else None
        )
        if exchange_rate is not None and exchange_rate <= _DECIMAL_ZERO:
            exchange_rate = None

        m_usd_raw = payload.get("marginUsdRate", payload.get("margin_usd_rate"))
        margin_usd_rate = self._to_decimal(m_usd_raw) if m_usd_raw is not None else None
        if margin_usd_rate is not None and margin_usd_rate <= _DECIMAL_ZERO:
            margin_usd_rate = None

        raw_enable = payload.get("enable", payload.get("enabled"))
        enable: bool
        if raw_enable is None:
            enable = False
        else:
            match str(raw_enable).strip().lower():
                case "2" | "true":
                    enable = True
                case "1" | "0" | "false":
                    enable = False
                case _:
                    enable = False

        # Pip size derivation
        raw_pip = payload.get("pipSize", payload.get("pip_size"))
        if raw_pip is not None:
            pip_size = self._to_decimal(raw_pip)
        elif asset_class is AssetClass.FOREX:
            pip_size = (
                tick_size * Decimal("10")
                if tick_size < Decimal("0.001")
                else Decimal("0.01")
            )
            if pip_size <= _DECIMAL_ZERO:
                pip_size = (
                    Decimal("0.0001") if not symbol.endswith("JPY") else Decimal("0.01")
                )
        elif asset_class is AssetClass.COMMODITY:
            clean = symbol.upper()
            if clean.startswith("XAU"):
                pip_size = Decimal("0.10")
            elif clean.startswith("XAG"):
                pip_size = Decimal("0.01")
            else:
                pip_size = tick_size if tick_size > _DECIMAL_ZERO else Decimal("0.01")
        elif asset_class is AssetClass.INDEX:
            pip_size = Decimal("1.0")
        else:
            pip_size = Decimal("1.0")

        return CfdContractSpec(
            symbol=symbol,
            asset_class=asset_class,
            contract_size=contract_size,
            pip_size=pip_size,
            tick_size=tick_size,
            min_lot=min_lot,
            max_lot=max_lot,
            lot_step=lot_step,
            default_leverage=leverage,
            max_leverage=max_leverage,
            trade_time=trade_time,
            margin_currency=margin_currency,
            profit_currency=profit_currency,
            price_currency=price_currency,
            exchange_rate=exchange_rate,
            margin_usd_rate=margin_usd_rate,
            enable=enable,
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
