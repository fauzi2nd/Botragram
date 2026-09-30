"""Exercise order persistence and exchange side-effect boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.engine.order.order_engine import OrderEngine
from botragram.enums import OrderSide, OrderStatus, OrderType, SignalType
from botragram.models import ExchangeSymbolRules, Order, RiskMetrics, RiskResult, Signal
from botragram.models.risk import PositionSize
from botragram.services.execution.order_service import OrderService
from botragram.storage.memory.order_repository import MemoryOrderRepository

__all__: list[str] = []

_NOW = datetime(2026, 9, 30, tzinfo=UTC)
_QUANTITY = Decimal("0.01")


def _order() -> Order:
    """Return one exchange order snapshot."""
    return Order(
        order_id="order-1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        quantity=_QUANTITY,
        executed_quantity=_QUANTITY,
        created_at=_NOW,
        updated_at=_NOW,
        client_order_id="client-1",
    )


def _signal() -> Signal:
    """Return an executable signal."""
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("65000"),
        confidence=Decimal("1"),
        strategy_name="test",
        generated_at=_NOW,
    )


def _risk_result() -> RiskResult:
    """Return an approved risk decision."""
    return RiskResult(
        approved=True,
        position=PositionSize(
            quantity=_QUANTITY,
            notional=Decimal("650"),
            leverage=1,
        ),
        metrics=RiskMetrics(
            entry_price=Decimal("65000"),
            stop_loss=Decimal("64000"),
            take_profit=Decimal("66000"),
            risk_amount=Decimal("10"),
            reward_amount=Decimal("10"),
            risk_reward_ratio=Decimal("1"),
        ),
    )


@dataclass(slots=True)
class _RecordingExchange:
    """Record exchange mutations without network access."""

    created_client_ids: list[str | None] = field(default_factory=list[str | None])
    canceled_order_ids: list[str] = field(default_factory=list[str])
    fetched_order_ids: list[str] = field(default_factory=list[str])

    async def get_reference_price(self, *, symbol: str) -> Decimal:
        """Return a safe reference price."""
        assert symbol == "BTCUSDT"
        return Decimal("65000")

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return a safe mark price."""
        assert symbol == "BTCUSDT"
        return Decimal("65000")

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return venue quantity rules."""
        return ExchangeSymbolRules(
            symbol=symbol,
            market_min_quantity=Decimal("0.001"),
            market_max_quantity=Decimal("10"),
            market_quantity_step=Decimal("0.001"),
            price_tick_size=Decimal("0.01"),
        )

    async def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        """Record one exchange submission."""
        assert (symbol, side, order_type, quantity, price) == (
            "BTCUSDT",
            OrderSide.BUY,
            OrderType.MARKET,
            _QUANTITY,
            None,
        )
        self.created_client_ids.append(client_order_id)
        return _order()

    async def cancel_order(self, *, symbol: str, order_id: str) -> Order:
        """Record one exchange cancellation."""
        assert symbol == "BTCUSDT"
        self.canceled_order_ids.append(order_id)
        return _order()

    async def get_order(self, *, symbol: str, order_id: str) -> Order:
        """Record one exchange lookup."""
        assert symbol == "BTCUSDT"
        self.fetched_order_ids.append(order_id)
        return _order()

    async def get_order_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Return the order for its stable client identity."""
        assert (symbol, client_order_id) == ("BTCUSDT", "client-1")
        return _order()


class _FailingOrderRepository(MemoryOrderRepository):
    """Fail the persistence step after an exchange mutation."""

    async def save(self, *, order: Order) -> None:
        """Reject persistence without altering repository state."""
        raise OSError("database unavailable")


class _CancelledOrderRepository(MemoryOrderRepository):
    """Cancel during persistence after an exchange mutation."""

    async def save(self, *, order: Order) -> None:
        """Propagate cancellation without storing the order."""
        raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_submit_persists_order_with_stable_client_identity() -> None:
    """A successful submit creates and persists exactly one order."""
    exchange = _RecordingExchange()
    repository = MemoryOrderRepository()
    service = OrderService(
        order_engine=OrderEngine(exchange_client=exchange),
        order_repository=repository,
    )

    order = await service.submit(
        signal=_signal(),
        risk_result=_risk_result(),
        client_order_id="client-1",
    )

    assert exchange.created_client_ids == ["client-1"]
    assert (
        await repository.get_by_id(order_id=order.order_id, symbol=order.symbol)
        == order
    )


@pytest.mark.asyncio
async def test_submit_persistence_failure_does_not_hide_exchange_side_effect() -> None:
    """A failed save propagates after one submission without automatic retry."""
    exchange = _RecordingExchange()
    service = OrderService(
        order_engine=OrderEngine(exchange_client=exchange),
        order_repository=_FailingOrderRepository(),
    )

    with pytest.raises(OSError, match="database unavailable"):
        await service.submit(
            signal=_signal(),
            risk_result=_risk_result(),
            client_order_id="client-1",
        )

    assert exchange.created_client_ids == ["client-1"]


@pytest.mark.asyncio
async def test_submit_persistence_cancellation_propagates() -> None:
    """Cancellation after submission is not hidden or retried."""
    exchange = _RecordingExchange()
    service = OrderService(
        order_engine=OrderEngine(exchange_client=exchange),
        order_repository=_CancelledOrderRepository(),
    )

    with pytest.raises(asyncio.CancelledError):
        await service.submit(
            signal=_signal(),
            risk_result=_risk_result(),
            client_order_id="client-1",
        )

    assert exchange.created_client_ids == ["client-1"]


@pytest.mark.asyncio
async def test_invalid_cancel_identity_never_reaches_exchange() -> None:
    """Reject an empty order identifier before a cancellation side effect."""
    exchange = _RecordingExchange()
    service = OrderService(
        order_engine=OrderEngine(exchange_client=exchange),
        order_repository=MemoryOrderRepository(),
    )

    with pytest.raises(ValueError, match="Order identifier must not be empty"):
        await service.cancel(symbol="BTCUSDT", order_id="  ")

    assert exchange.canceled_order_ids == []
