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
    SubmissionAttemptStatus,
)
from botragram.exceptions import LiveEntryPreflightError, VenueRuleValidationError
from botragram.models import (
    Order,
    Position,
    RiskMetrics,
    RiskResult,
    Signal,
    SubmissionAttempt,
)
from botragram.models.risk import PositionSize
from botragram.services import LiveFuturesEntryService, LivePostEntryRecoveryService
from botragram.storage.memory import MemorySubmissionAttemptRepository
from botragram.storage.memory.live_recovery_repository import (
    MemoryLiveRecoveryRepository,
)

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
    normalization_error: BaseException | None = None
    normalized_quantity: Decimal | None = None
    submitted_risk_result: RiskResult | None = None
    calls: int = 0

    async def normalize_futures_market_quantity(
        self, *, symbol: str, quantity: Decimal
    ) -> Decimal:
        """Return the test's already-valid quantity."""
        assert symbol == "BTCUSDT"
        if self.normalization_error is not None:
            raise self.normalization_error
        return self.normalized_quantity or quantity

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
        client_order_id: str | None = None,
    ) -> Order:
        """Return one order or raise the configured submission failure."""
        del signal, order_type, price, client_order_id
        self.calls += 1
        self.submitted_risk_result = risk_result
        if self.error is not None:
            raise self.error
        return self.order

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Reject unexpected reconciliation in Phase 5A success-path tests."""
        del symbol, client_order_id
        raise AssertionError("Unexpected order reconciliation")


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

    async def observe(self, *, symbol: str) -> Position | None:
        """Return the authoritative position without mutating persistence."""
        assert symbol == "BTCUSDT"
        return self.position

    async def save(self, *, position: Position) -> None:
        """Capture metadata persistence."""
        self.saved = position

    async def delete(self, *, symbol: str) -> bool:
        """Delete the stored position for the symbol."""
        existed = self.position is not None and self.position.symbol == symbol
        if existed:
            self.position = None
        return existed


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

    async def probe_persisted_leg(
        self, *, position: Position, order_type: OrderType, client_id: str
    ) -> str:
        return "not_found"
        if isinstance(self.error, asyncio.CancelledError):
            raise self.error
        if self.error is not None:
            raise self.error
        return position


class FailingSubmissionAttemptRepository(MemorySubmissionAttemptRepository):
    """Fail one configured durable transition without exchange interaction."""

    __slots__ = ("_failed", "_failure_status")

    def __init__(self, *, failure_status: SubmissionAttemptStatus) -> None:
        """Configure the one transition that deterministically fails."""
        super().__init__()
        self._failed = False
        self._failure_status = failure_status

    async def save(self, *, attempt: SubmissionAttempt) -> None:
        """Fail exactly once before delegating later durable transitions."""
        if not self._failed and attempt.status is self._failure_status:
            self._failed = True
            raise RuntimeError(f"configured {attempt.status.value} persistence failure")
        await super().save(attempt=attempt)


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
            submission_attempt_repository=MemorySubmissionAttemptRepository(),
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
async def test_normalized_notional_uses_authoritative_risk_entry_price() -> None:
    """Retain current risk-price sizing after venue quantity normalization."""
    orders = FakeOrderService(normalized_quantity=Decimal("0.02"))
    service, _ = _service(order_service=orders)
    risk_result = RiskResult(
        approved=True,
        position=PositionSize(
            quantity=Decimal("0.01"),
            notional=Decimal("750"),
            leverage=1,
        ),
        metrics=RiskMetrics(
            entry_price=Decimal("75000"),
            stop_loss=Decimal("74000"),
            take_profit=Decimal("76000"),
            risk_amount=Decimal("10"),
            reward_amount=Decimal("10"),
            risk_reward_ratio=Decimal("1"),
        ),
    )

    await service.execute(
        signal=_signal(),
        risk_result=risk_result,
        interval=Interval.M15,
        order_type=OrderType.MARKET,
        price=None,
    )

    assert orders.submitted_risk_result is not None
    assert orders.submitted_risk_result.position.notional == Decimal("1500")


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


@pytest.mark.asyncio
async def test_prepared_persistence_failure_never_reaches_entry_post() -> None:
    """A crash before PREPARED leaves no mutation or replayable durable intent."""
    orders = FakeOrderService()
    repository = FailingSubmissionAttemptRepository(
        failure_status=SubmissionAttemptStatus.PREPARED
    )
    control = TradingRuntimeControl(market_type=MarketType.FUTURES)
    service = LiveFuturesEntryService(
        market_type=MarketType.FUTURES,
        order_service=orders,
        position_service=FakePositionService(_position()),
        protection_service=FakeProtectionService(),
        runtime_control=control,
        submission_attempt_repository=repository,
    )

    with pytest.raises(RuntimeError, match="prepared persistence failure"):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M15,
            order_type=OrderType.MARKET,
            price=None,
        )

    assert orders.calls == 0
    assert await repository.get_incomplete() == ()
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_completion_persistence_failure_recovers_same_acknowledged_attempt() -> (
    None
):
    """Verified protection without COMPLETED remains recoverable without a new POST."""
    orders = FakeOrderService()
    positions = FakePositionService(_position())
    protection = FakeProtectionService()
    repository = FailingSubmissionAttemptRepository(
        failure_status=SubmissionAttemptStatus.COMPLETED
    )
    control = TradingRuntimeControl(market_type=MarketType.FUTURES)
    service = LiveFuturesEntryService(
        market_type=MarketType.FUTURES,
        order_service=orders,
        position_service=positions,
        protection_service=protection,
        runtime_control=control,
        submission_attempt_repository=repository,
    )

    with pytest.raises(RuntimeError, match="completed persistence failure"):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M15,
            order_type=OrderType.MARKET,
            price=None,
        )

    incomplete = await repository.get_incomplete()
    assert len(incomplete) == 1
    assert incomplete[0].status is SubmissionAttemptStatus.ACKNOWLEDGED
    assert orders.calls == 1

    await LivePostEntryRecoveryService(
        submission_attempt_repository=repository,
        live_recovery_repository=MemoryLiveRecoveryRepository(
            attempt_repo=repository,
            position_repo=positions,  # type: ignore[arg-type]
        ),
        position_service=positions,
        protection_service=protection,
        runtime_control=control,
    ).recover_acknowledged(attempt=incomplete[0])

    assert orders.calls == 1
    assert await repository.get_incomplete() == ()
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_venue_rejection_prevents_prepared_and_entry_post() -> None:
    """Invalid venue quantity must not create a durable mutation intent."""
    orders = FakeOrderService(
        normalization_error=VenueRuleValidationError("below minimum")
    )
    service, _ = _service(order_service=orders)

    with pytest.raises(VenueRuleValidationError, match="below minimum"):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M15,
            order_type=OrderType.MARKET,
            price=None,
        )

    assert orders.calls == 0
    assert await service.submission_attempt_repository.get_incomplete() == ()


@pytest.mark.asyncio
async def test_operational_preflight_failure_preserves_unmutated_entry_state() -> None:
    """Wrap a venue read failure without creating an uncertain submission."""
    orders = FakeOrderService(normalization_error=RuntimeError("mark price failed"))
    service, control = _service(order_service=orders)

    with pytest.raises(LiveEntryPreflightError, match="preflight failed") as error:
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M15,
            order_type=OrderType.MARKET,
            price=None,
        )

    assert isinstance(error.value.__cause__, RuntimeError)
    assert orders.calls == 0
    assert await service.submission_attempt_repository.get_incomplete() == ()
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_preflight_cancellation_propagates_without_closing_protection_gate() -> (
    None
):
    """Never wrap cancellation from a pre-mutation venue read."""
    orders = FakeOrderService(normalization_error=asyncio.CancelledError())
    service, control = _service(order_service=orders)

    with pytest.raises(asyncio.CancelledError):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M15,
            order_type=OrderType.MARKET,
            price=None,
        )

    assert orders.calls == 0
    assert await service.submission_attempt_repository.get_incomplete() == ()
    assert "position protection" not in control.get_missing_startup_requirements()
