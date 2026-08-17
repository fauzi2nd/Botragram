"""Protected LIVE Futures entry workflow tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app import TradingRuntimeControl
from botragram.enums import (
    Interval,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    StrategyType,
)
from botragram.models import Order, Position, RiskMetrics, RiskResult, Signal
from botragram.models.risk import PositionSize
from botragram.services import LiveFuturesEntryService

_NOW = datetime(2026, 8, 17, tzinfo=UTC)


def _signal() -> Signal:
    """Return one approved long signal."""
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("65000"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_SCALPING.value,
        generated_at=_NOW,
    )


def _risk_result() -> RiskResult:
    """Return one approved risk result."""
    return RiskResult(
        approved=True,
        position=PositionSize(
            quantity=Decimal("0.01"),
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


def _order() -> Order:
    """Return an acknowledged MARKET order."""
    return Order(
        order_id="entry-1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _position() -> Position:
    """Return the exchange-authoritative filled Futures position."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("0.012"),
        entry_price=Decimal("65100"),
        current_price=Decimal("65100"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )


@dataclass(slots=True)
class FakeOrderService:
    """Capture single entry submission calls."""

    order: Order = field(default_factory=_order)
    error: BaseException | None = None
    calls: int = 0

    async def submit(self, **_: object) -> Order:
        """Return one order or raise the configured submission failure."""
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.order


@dataclass(slots=True)
class FakePositionService:
    """Return the post-entry exchange position and capture persistence."""

    position: Position | None
    synchronized: bool = False
    saved: Position | None = None

    async def get(self, *, symbol: str, synchronize: bool = False) -> Position | None:
        """Return the current position while recording synchronization intent."""
        assert symbol == "BTCUSDT"
        self.synchronized = synchronize
        return self.position

    async def save(self, *, position: Position) -> None:
        """Capture metadata persistence."""
        self.saved = position


@dataclass(slots=True)
class FakeProtectionService:
    """Capture protection verification requests."""

    error: BaseException | None = None
    position: Position | None = None

    async def ensure(self, *, position: Position) -> Position:
        """Return verified protection or fail closed."""
        self.position = position
        if isinstance(self.error, asyncio.CancelledError):
            raise self.error
        if self.error is not None:
            raise self.error
        return position


def _service(
    *,
    order_service: FakeOrderService | None = None,
    position_service: FakePositionService | None = None,
    protection_service: FakeProtectionService | None = None,
    market_type: MarketType = MarketType.FUTURES,
) -> tuple[LiveFuturesEntryService, TradingRuntimeControl]:
    """Build the focused entry service with boundary fakes."""
    control = TradingRuntimeControl(market_type=market_type)
    return (
        LiveFuturesEntryService(
            market_type=market_type,
            order_service=order_service or FakeOrderService(),
            position_service=position_service or FakePositionService(_position()),
            protection_service=protection_service or FakeProtectionService(),
            runtime_control=control,
        ),
        control,
    )


@pytest.mark.asyncio
async def test_market_entry_syncs_actual_position_and_marks_protection_ready() -> None:
    """Use exchange quantity/price and persist strategy plus interval metadata."""
    positions = FakePositionService(_position())
    protection = FakeProtectionService()
    service, control = _service(
        position_service=positions,
        protection_service=protection,
    )

    order = await service.execute(
        signal=_signal(),
        risk_result=_risk_result(),
        interval=Interval.M15,
        order_type=OrderType.MARKET,
        price=None,
    )

    assert order.order_id == "entry-1"
    assert positions.synchronized
    assert positions.saved is not None
    assert positions.saved.quantity == Decimal("0.012")
    assert positions.saved.entry_price == Decimal("65100")
    assert positions.saved.interval is Interval.M15
    assert positions.saved.strategy_type is StrategyType.EMA_SCALPING
    assert protection.position == positions.saved
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_unverified_position_or_protection_keeps_gate_closed() -> None:
    """Never report a safe state when exchange position or SL/TP is unknown."""
    service, control = _service(position_service=FakePositionService(None))

    with pytest.raises(RuntimeError, match="active entry position"):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M1,
            order_type=OrderType.MARKET,
            price=None,
        )

    assert "position protection" in control.get_missing_startup_requirements()

    service, control = _service(
        protection_service=FakeProtectionService(error=RuntimeError("missing TP")),
    )
    with pytest.raises(RuntimeError, match="missing TP"):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M1,
            order_type=OrderType.MARKET,
            price=None,
        )
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_limit_rejection_and_submission_failure_never_retry() -> None:
    """Reject asynchronous LIMIT entries and keep an ambiguous submission unsafe."""
    orders = FakeOrderService(error=RuntimeError("timeout"))
    service, control = _service(order_service=orders)

    with pytest.raises(ValueError, match="MARKET"):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M1,
            order_type=OrderType.LIMIT,
            price=Decimal("64000"),
        )
    assert orders.calls == 0

    with pytest.raises(RuntimeError, match="timeout"):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M1,
            order_type=OrderType.MARKET,
            price=None,
        )
    assert orders.calls == 1
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_cancellation_propagates_with_protection_gate_closed() -> None:
    """Do not convert cancellation into a safe or retried entry result."""
    orders = FakeOrderService(error=asyncio.CancelledError())
    service, control = _service(order_service=orders)

    with pytest.raises(asyncio.CancelledError):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M1,
            order_type=OrderType.MARKET,
            price=None,
        )

    assert orders.calls == 1
    assert "position protection" in control.get_missing_startup_requirements()
