"""Futures PRICE_FILTER trigger-normalization regression tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.config.risk_settings import RiskSettings
from botragram.engine import RiskEngine
from botragram.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    StrategyType,
)
from botragram.exceptions import ExchangeOrderNotFoundError, VenueRuleValidationError
from botragram.exchanges.binance.futures_client import BinanceFuturesExchangeClient
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import ExchangeSymbolRules, Order, Position
from botragram.services import LivePositionProtectionService
from botragram.storage.memory import MemoryPositionRepository

_NOW = datetime(2026, 8, 18, tzinfo=UTC)


class RecordingPositionRepository(MemoryPositionRepository):
    """Record durable position writes performed by protection reconciliation."""

    __slots__ = ("saved_positions",)

    def __init__(self) -> None:
        """Initialize an empty recording repository."""
        super().__init__()
        self.saved_positions: list[Position] = []

    async def save(self, *, position: Position) -> None:
        """Record and persist one immutable position snapshot."""
        self.saved_positions.append(position)
        await super().save(position=position)


class ProtectionPlanExchange(BinanceFuturesExchangeClient):
    """Provide deterministic read and mutation boundaries for one protection plan."""

    __slots__ = (
        "events",
        "mark_price",
        "mark_price_error",
        "orders",
        "rules",
        "rules_error",
    )

    rules: ExchangeSymbolRules
    mark_price: Decimal
    rules_error: BaseException | None
    mark_price_error: BaseException | None
    events: list[str]
    orders: list[Order]

    def __init__(
        self,
        *,
        rules: ExchangeSymbolRules,
        mark_price: Decimal,
        rules_error: BaseException | None = None,
        mark_price_error: BaseException | None = None,
    ) -> None:
        """Initialize an isolated Futures client double."""
        super().__init__(
            rest=BinanceRestClient(base_url="https://example.test"),
            mapper=BinanceExchangeMapper(),
        )
        self.rules = rules
        self.mark_price = mark_price
        self.rules_error = rules_error
        self.mark_price_error = mark_price_error
        self.events = []
        self.orders = []

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return configured PRICE_FILTER rules or propagate the test failure."""
        self.events.append("rules")
        assert symbol == self.rules.symbol
        if self.rules_error is not None:
            raise self.rules_error
        return self.rules

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return configured MARK_PRICE or propagate the test failure."""
        self.events.append("mark_price")
        assert symbol == self.rules.symbol
        if self.mark_price_error is not None:
            raise self.mark_price_error
        return self.mark_price

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[Order, ...]:
        """Return currently created test protection orders."""
        self.events.append("open_protections")
        return tuple(
            order
            for order in self.orders
            if symbol is None or order.symbol == symbol.upper()
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
    ) -> tuple[Order, ...]:
        """Record exactly one requested logical protection-leg mutation."""
        trigger_price = stop_loss if stop_loss is not None else take_profit
        order_type = (
            OrderType.STOP_MARKET
            if stop_loss is not None
            else OrderType.TAKE_PROFIT_MARKET
        )
        assert trigger_price is not None
        client_order_id = (
            stop_loss_client_algo_id
            if stop_loss is not None
            else take_profit_client_algo_id
        )
        assert client_order_id is not None
        self.events.append(f"post:{order_type.value}")
        order = Order(
            order_id=f"protection-{len(self.orders) + 1}",
            symbol=symbol,
            side=side,
            order_type=order_type,
            status=OrderStatus.NEW,
            quantity=quantity,
            executed_quantity=Decimal("0"),
            price=None,
            stop_price=trigger_price,
            created_at=_NOW,
            updated_at=_NOW,
            client_order_id=client_order_id,
        )
        self.orders.append(order)
        return (order,)

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Return one exact test protection identity through a GET-only lookup."""
        self.events.append("get_protection_by_client_id")
        for order in self.orders:
            if order.symbol == symbol.upper() and order.client_order_id == client_id:
                return order
        raise ExchangeOrderNotFoundError("configured protection is not found")


def _rules(
    *,
    minimum_price: str = "0.0000010",
    maximum_price: str = "200",
    tick_size: str = "0.0000010",
) -> ExchangeSymbolRules:
    """Return deterministic Futures MARKET and PRICE_FILTER rules."""
    return ExchangeSymbolRules(
        symbol="1000BONKUSDT",
        market_min_quantity=Decimal("1"),
        market_max_quantity=Decimal("100000"),
        market_quantity_step=Decimal("1"),
        minimum_price=Decimal(minimum_price),
        maximum_price=Decimal(maximum_price),
        price_tick_size=Decimal(tick_size),
    )


def _position() -> Position:
    """Return the original 1000BONK long protection regression position."""
    return Position(
        symbol="1000BONKUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("0.002294"),
        current_price=Decimal("0.002294"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        strategy_type=StrategyType.EMA_CROSS,
    )


def test_binance_mapper_maps_price_filter() -> None:
    """Keep raw Binance PRICE_FILTER payloads inside the vendor mapper."""
    rules = BinanceExchangeMapper().map_market_entry_rules(
        {
            "symbol": "1000BONKUSDT",
            "filters": [
                {
                    "filterType": "PRICE_FILTER",
                    "minPrice": "0.0000010",
                    "maxPrice": "200",
                    "tickSize": "0.0000010",
                },
                {
                    "filterType": "LOT_SIZE",
                    "minQty": "1",
                    "maxQty": "10000000",
                    "stepSize": "1",
                },
                {
                    "filterType": "MARKET_LOT_SIZE",
                    "minQty": "1",
                    "maxQty": "100000",
                    "stepSize": "1",
                },
            ],
        }
    )

    assert rules.minimum_price == Decimal("0.0000010")
    assert rules.maximum_price == Decimal("200")
    assert rules.price_tick_size == Decimal("0.0000010")


@pytest.mark.parametrize(
    ("position_side", "order_type", "raw", "expected"),
    [
        (PositionSide.LONG, OrderType.STOP_MARKET, "0.00224812", "0.0022490"),
        (PositionSide.LONG, OrderType.TAKE_PROFIT_MARKET, "0.00238576", "0.0023850"),
        (PositionSide.SHORT, OrderType.STOP_MARKET, "0.00238576", "0.0023850"),
        (PositionSide.SHORT, OrderType.TAKE_PROFIT_MARKET, "0.00224812", "0.0022490"),
    ],
)
def test_normalizes_protection_trigger_conservatively(
    position_side: PositionSide,
    order_type: OrderType,
    raw: str,
    expected: str,
) -> None:
    """Use the intended directional PRICE_FILTER rounding for every logical leg."""
    normalized = _rules().normalize_protection_trigger(
        raw_trigger_price=Decimal(raw),
        position_side=position_side,
        order_type=order_type,
        mark_price=Decimal("0.002294"),
    )

    assert normalized == Decimal(expected)
    if (position_side, order_type) in {
        (PositionSide.LONG, OrderType.STOP_MARKET),
        (PositionSide.SHORT, OrderType.TAKE_PROFIT_MARKET),
    }:
        assert normalized >= Decimal(raw)
    else:
        assert normalized <= Decimal(raw)


def test_normalizes_against_an_arbitrary_minimum_anchored_grid() -> None:
    """Use minPrice as the grid origin rather than assuming zero anchoring."""
    rules = _rules(minimum_price="0.10", maximum_price="100", tick_size="0.25")

    assert rules.normalize_protection_trigger(
        raw_trigger_price=Decimal("1.23"),
        position_side=PositionSide.LONG,
        order_type=OrderType.STOP_MARKET,
        mark_price=Decimal("2"),
    ) == Decimal("1.35")
    assert rules.normalize_protection_trigger(
        raw_trigger_price=Decimal("2.13"),
        position_side=PositionSide.LONG,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        mark_price=Decimal("2"),
    ) == Decimal("2.10")


@pytest.mark.parametrize("raw", ["0.0000009", "201"])
def test_rejects_trigger_outside_price_filter_bounds(raw: str) -> None:
    """Fail closed rather than clamping an invalid trigger into venue bounds."""
    with pytest.raises(VenueRuleValidationError):
        _rules().normalize_protection_trigger(
            raw_trigger_price=Decimal(raw),
            position_side=PositionSide.LONG,
            order_type=OrderType.STOP_MARKET,
            mark_price=Decimal("0.002294"),
        )


def test_rejects_missing_or_invalid_price_tick_size() -> None:
    """Require a usable PRICE_FILTER tick before plan normalization."""
    with pytest.raises(ValueError):
        _rules(tick_size="0")


@pytest.mark.asyncio
async def test_invalid_mark_plan_creates_no_identity_or_post() -> None:
    """Reject immediately-triggerable protection before durable mutation state."""
    repository = RecordingPositionRepository()
    exchange = ProtectionPlanExchange(
        rules=_rules(),
        mark_price=Decimal("0.002248"),
    )
    service = LivePositionProtectionService(
        exchange_client=exchange,
        position_repository=repository,
        risk_engine=RiskEngine(settings=RiskSettings()),
    )

    with pytest.raises(VenueRuleValidationError):
        await service.ensure(position=_position())

    assert repository.saved_positions == []
    assert exchange.orders == []
    assert all(not event.startswith("post:") for event in exchange.events)


@pytest.mark.asyncio
async def test_rule_or_mark_read_failure_creates_no_identity_or_post() -> None:
    """Leave durable and exchange mutation state untouched when reads fail."""
    for rules_error, mark_price_error in (
        (RuntimeError("rule lookup failed"), None),
        (None, RuntimeError("mark lookup failed")),
    ):
        repository = RecordingPositionRepository()
        exchange = ProtectionPlanExchange(
            rules=_rules(),
            mark_price=Decimal("0.002294"),
            rules_error=rules_error,
            mark_price_error=mark_price_error,
        )
        service = LivePositionProtectionService(
            exchange_client=exchange,
            position_repository=repository,
            risk_engine=RiskEngine(settings=RiskSettings()),
        )

        with pytest.raises(RuntimeError):
            await service.ensure(position=_position())

        assert repository.saved_positions == []
        assert exchange.orders == []


def test_mark_price_cancellation_propagates() -> None:
    """Never convert cancellation into a fallback protection decision."""

    async def run() -> None:
        service = LivePositionProtectionService(
            exchange_client=ProtectionPlanExchange(
                rules=_rules(),
                mark_price=Decimal("0.002294"),
                mark_price_error=asyncio.CancelledError(),
            ),
            position_repository=RecordingPositionRepository(),
            risk_engine=RiskEngine(settings=RiskSettings()),
        )
        await service.ensure(position=_position())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run())


@pytest.mark.asyncio
async def test_initial_protection_submits_normalized_stop_before_take_profit() -> None:
    """Persist and submit final venue prices in strict STOP-then-TP sequence."""
    repository = RecordingPositionRepository()
    exchange = ProtectionPlanExchange(
        rules=_rules(),
        mark_price=Decimal("0.002294"),
    )
    service = LivePositionProtectionService(
        exchange_client=exchange,
        position_repository=repository,
        risk_engine=RiskEngine(settings=RiskSettings()),
    )

    protected = await service.ensure(position=_position())

    assert [order.stop_price for order in exchange.orders] == [
        Decimal("0.0022490"),
        Decimal("0.0023850"),
    ]
    assert exchange.events.index("post:stop_market") < exchange.events.index(
        "post:take_profit_market"
    )
    assert repository.saved_positions[0].stop_loss == Decimal("0.0022490")
    assert repository.saved_positions[0].take_profit is None
    assert repository.saved_positions[1].take_profit == Decimal("0.0023850")
    assert protected.stop_loss == Decimal("0.0022490")
    assert protected.take_profit == Decimal("0.0023850")


def _recovered_position() -> Position:
    """Return the 1000BONK position with durable final venue triggers."""
    return replace(
        _position(),
        stop_loss=Decimal("0.0022490"),
        take_profit=Decimal("0.0023850"),
        stop_loss_client_algo_id="bsl-00000000000000000000000000000000",
        take_profit_client_algo_id="btp-00000000000000000000000000000000",
    )


def _recovered_order(
    *,
    order_type: OrderType,
    trigger_price: Decimal,
    client_order_id: str,
) -> Order:
    """Return one authoritative 1000BONK protection-order GET result."""
    return Order(
        order_id=f"recovered-{order_type.value}",
        symbol="1000BONKUSDT",
        side=OrderSide.SELL,
        order_type=order_type,
        status=OrderStatus.NEW,
        quantity=Decimal("4361"),
        executed_quantity=Decimal("0"),
        price=None,
        stop_price=trigger_price,
        created_at=_NOW,
        updated_at=_NOW,
        client_order_id=client_order_id,
    )


@pytest.mark.asyncio
async def test_restart_verifies_exact_normalized_1000bonk_protection_without_post() -> (
    None
):
    """Reconcile exact durable venue triggers through identities without reposting."""
    position = _recovered_position()
    exchange = ProtectionPlanExchange(rules=_rules(), mark_price=Decimal("0.002294"))
    exchange.orders.extend(
        (
            _recovered_order(
                order_type=OrderType.STOP_MARKET,
                trigger_price=Decimal("0.0022490"),
                client_order_id=position.stop_loss_client_algo_id or "",
            ),
            _recovered_order(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                trigger_price=Decimal("0.0023850"),
                client_order_id=position.take_profit_client_algo_id or "",
            ),
        )
    )
    repository = RecordingPositionRepository()
    service = LivePositionProtectionService(
        exchange_client=exchange,
        position_repository=repository,
        risk_engine=RiskEngine(settings=RiskSettings()),
    )

    protected = await service.ensure(position=position)

    assert protected.stop_loss == Decimal("0.0022490")
    assert protected.take_profit == Decimal("0.0023850")
    assert not any(event.startswith("post:") for event in exchange.events)
    assert exchange.events.count("get_protection_by_client_id") == 2


@pytest.mark.asyncio
async def test_restart_rejects_mismatched_normalized_protection_without_post() -> None:
    """Fail closed when an identity resolves to a trigger other than durable state."""
    position = _recovered_position()
    exchange = ProtectionPlanExchange(rules=_rules(), mark_price=Decimal("0.002294"))
    exchange.orders.append(
        _recovered_order(
            order_type=OrderType.STOP_MARKET,
            trigger_price=Decimal("0.0022480"),
            client_order_id=position.stop_loss_client_algo_id or "",
        )
    )
    service = LivePositionProtectionService(
        exchange_client=exchange,
        position_repository=RecordingPositionRepository(),
        risk_engine=RiskEngine(settings=RiskSettings()),
    )

    with pytest.raises(RuntimeError, match="does not match"):
        await service.ensure(position=position)

    assert not any(event.startswith("post:") for event in exchange.events)
