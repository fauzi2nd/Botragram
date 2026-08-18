"""LIVE submission-attempt lifecycle tests."""

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
    SubmissionAttemptStatus,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
    ExchangeOrderRejectedError,
)
from botragram.models import (
    Order,
    Position,
    RiskMetrics,
    RiskResult,
    Signal,
    SubmissionAttempt,
)
from botragram.models.risk import PositionSize
from botragram.repositories import SubmissionAttemptRepository
from botragram.services import LiveFuturesEntryService

_NOW = datetime(2026, 8, 17, tzinfo=UTC)


def _signal() -> Signal:
    """Return an approved BUY signal."""
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("65000"),
        confidence=Decimal("0.9"),
        strategy_name="ema_scalping",
        generated_at=_NOW,
    )


def _risk_result() -> RiskResult:
    """Return an approved Futures position size."""
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


def _order(*, client_order_id: str | None = None) -> Order:
    """Return one exchange-acknowledged MARKET order."""
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
        client_order_id=client_order_id,
    )


def _position() -> Position:
    """Return one exchange-authoritative Futures position."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("0.01"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )


@dataclass(slots=True)
class RecordingSubmissionAttemptRepository(SubmissionAttemptRepository):
    """Capture durable attempt lifecycle operations."""

    events: list[str] = field(default_factory=list[str])
    attempts: dict[str, SubmissionAttempt] = field(
        default_factory=dict[str, SubmissionAttempt]
    )
    fail_status: SubmissionAttemptStatus | None = None

    async def save(self, *, attempt: SubmissionAttempt) -> None:
        """Record one persistence transition or inject one deterministic failure."""
        self.events.append(f"save:{attempt.status.value}")
        if attempt.status is self.fail_status:
            raise RuntimeError(f"cannot save {attempt.status.value}")
        self.attempts[attempt.client_order_id] = attempt

    async def get_by_client_order_id(
        self, *, client_order_id: str
    ) -> SubmissionAttempt | None:
        """Return one stored attempt."""
        return self.attempts.get(client_order_id)

    async def get_unresolved(self) -> tuple[SubmissionAttempt, ...]:
        """Return currently blocking attempts."""
        return tuple(
            attempt
            for attempt in self.attempts.values()
            if attempt.status
            in (
                SubmissionAttemptStatus.PREPARED,
                SubmissionAttemptStatus.UNRESOLVED,
            )
        )

    async def get_incomplete(self) -> tuple[SubmissionAttempt, ...]:
        """Return attempts requiring lifecycle recovery."""
        return tuple(
            attempt
            for attempt in self.attempts.values()
            if attempt.status is not SubmissionAttemptStatus.REJECTED
            and attempt.status is not SubmissionAttemptStatus.COMPLETED
        )


@dataclass(slots=True)
class RecordingOrderService:
    """Capture exactly one attempted remote submission."""

    events: list[str]
    error: BaseException | None = None
    returned_client_order_id: str | None = None
    echo_client_order_id: bool = False
    reconcile_echo_client_order_id: bool = False
    calls: int = 0
    client_order_ids: list[str | None] = field(default_factory=list[str | None])
    reconciled_orders: list[Order | BaseException] = field(
        default_factory=list[Order | BaseException]
    )

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
        client_order_id: str | None = None,
    ) -> Order:
        """Record the identity sent to the remote order boundary."""
        del signal, risk_result, order_type, price
        self.events.append("submit")
        self.calls += 1
        self.client_order_ids.append(client_order_id)
        if self.error is not None:
            raise self.error
        return _order(
            client_order_id=(
                client_order_id
                if self.echo_client_order_id
                else self.returned_client_order_id
            )
        )

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Return the next authoritative reconciliation response."""
        del symbol
        if self.reconciled_orders:
            response = self.reconciled_orders.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response
        if self.reconcile_echo_client_order_id:
            return _order(client_order_id=client_order_id)
        raise AssertionError("Unexpected order reconciliation")


@dataclass(slots=True)
class FakePositionService:
    """Provide one synchronized position for the protected-entry path."""

    position: Position | None = field(default_factory=_position)

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        """Return the configured position."""
        assert symbol == "BTCUSDT"
        assert synchronize
        return self.position

    async def save(self, *, position: Position) -> None:
        """Accept persisted runtime metadata."""
        del position


@dataclass(slots=True)
class FakeProtectionService:
    """Verify protection or fail after acknowledgement."""

    error: BaseException | None = None

    async def ensure(self, *, position: Position) -> Position:
        """Return protection verification outcome."""
        if self.error is not None:
            raise self.error
        return position


def _service(
    *,
    repository: RecordingSubmissionAttemptRepository | None = None,
    order_service: RecordingOrderService | None = None,
    protection_service: FakeProtectionService | None = None,
) -> tuple[
    LiveFuturesEntryService,
    TradingRuntimeControl,
    RecordingSubmissionAttemptRepository,
    RecordingOrderService,
]:
    """Build one isolated LIVE entry boundary and its observable dependencies."""
    events: list[str] = []
    resolved_repository = repository or RecordingSubmissionAttemptRepository(
        events=events
    )
    resolved_order_service = order_service or RecordingOrderService(events=events)
    control = TradingRuntimeControl(market_type=MarketType.FUTURES)
    return (
        LiveFuturesEntryService(
            market_type=MarketType.FUTURES,
            order_service=resolved_order_service,
            position_service=FakePositionService(),
            protection_service=protection_service or FakeProtectionService(),
            runtime_control=control,
            submission_attempt_repository=resolved_repository,
        ),
        control,
        resolved_repository,
        resolved_order_service,
    )


async def _execute(service: LiveFuturesEntryService) -> Order:
    """Execute one supported protected MARKET entry."""
    return await service.execute(
        signal=_signal(),
        risk_result=_risk_result(),
        interval=Interval.M15,
        order_type=OrderType.MARKET,
        price=None,
    )


@pytest.mark.asyncio
async def test_prepared_attempt_persists_before_submit_and_acknowledges() -> None:
    """Persist one exact logical identity before its only remote mutation."""
    service, _, repository, orders = _service()
    orders.echo_client_order_id = True

    order = await _execute(service)

    attempt = next(iter(repository.attempts.values()))
    assert repository.events == [
        "save:prepared",
        "submit",
        "save:acknowledged",
        "save:completed",
    ]
    assert orders.events == repository.events
    assert orders.client_order_ids == [attempt.client_order_id]
    assert order.client_order_id == attempt.client_order_id
    assert attempt.status is SubmissionAttemptStatus.COMPLETED
    assert attempt.exchange_order_id == "entry-1"
    assert attempt.client_order_id.startswith("btg-")
    assert len(attempt.client_order_id) == 36


@pytest.mark.asyncio
async def test_unresolved_attempt_blocks_another_live_entry_without_submission() -> (
    None
):
    """Retain a global fail-closed gate until future reconciliation exists."""
    repository = RecordingSubmissionAttemptRepository()
    blocking_attempt = SubmissionAttempt(
        client_order_id="btg-00000000000000000000000000000000",
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        signal_generated_at=_NOW,
        interval=Interval.M15,
        strategy_type=None,
        status=SubmissionAttemptStatus.UNRESOLVED,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repository.attempts[blocking_attempt.client_order_id] = blocking_attempt
    orders = RecordingOrderService(events=[])
    service, control, _, _ = _service(repository=repository, order_service=orders)

    with pytest.raises(RuntimeError, match="unresolved"):
        await _execute(service)

    assert orders.calls == 0
    assert len(repository.attempts) == 1
    assert control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_limit_rejection_and_prepared_persistence_failure_do_not_submit() -> None:
    """Reject local invalid operations and failed durable intent before POST."""
    service, _, repository, orders = _service()

    with pytest.raises(ValueError, match="MARKET"):
        await service.execute(
            signal=_signal(),
            risk_result=_risk_result(),
            interval=Interval.M15,
            order_type=OrderType.LIMIT,
            price=Decimal("64000"),
        )
    assert repository.events == []
    assert orders.calls == 0

    repository.fail_status = SubmissionAttemptStatus.PREPARED
    with pytest.raises(RuntimeError, match="cannot save prepared"):
        await _execute(service)
    assert orders.calls == 0


@pytest.mark.asyncio
async def test_submission_failure_and_cancellation_become_unresolved() -> None:
    """Do not retry ambiguous mutations and propagate cancellation unchanged."""
    events: list[str] = []
    repository = RecordingSubmissionAttemptRepository(events=events)
    orders = RecordingOrderService(events=events, error=RuntimeError("timeout"))
    service, control, _, _ = _service(repository=repository, order_service=orders)

    with pytest.raises(RuntimeError, match="timeout"):
        await _execute(service)
    assert orders.calls == 1
    assert (
        next(iter(repository.attempts.values())).status
        is SubmissionAttemptStatus.UNRESOLVED
    )
    assert events == ["save:prepared", "submit", "save:unresolved"]
    assert "position protection" in control.get_missing_startup_requirements()

    events = []
    repository = RecordingSubmissionAttemptRepository(events=events)
    orders = RecordingOrderService(events=events, error=asyncio.CancelledError())
    service, control, _, _ = _service(repository=repository, order_service=orders)
    with pytest.raises(asyncio.CancelledError):
        await _execute(service)
    assert orders.calls == 1
    assert (
        next(iter(repository.attempts.values())).status
        is SubmissionAttemptStatus.UNRESOLVED
    )
    assert events == ["save:prepared", "submit", "save:unresolved"]
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_mismatch_and_acknowledgement_persistence_failure_fail_closed() -> None:
    """Never treat a mismatched or durably unrecorded acknowledgement as safe."""
    events: list[str] = []
    repository = RecordingSubmissionAttemptRepository(events=events)
    orders = RecordingOrderService(events=events, returned_client_order_id="foreign")
    service, control, _, _ = _service(repository=repository, order_service=orders)

    with pytest.raises(RuntimeError, match="mismatched"):
        await _execute(service)
    assert orders.calls == 1
    assert (
        next(iter(repository.attempts.values())).status
        is SubmissionAttemptStatus.UNRESOLVED
    )
    assert "position protection" in control.get_missing_startup_requirements()

    events = []
    repository = RecordingSubmissionAttemptRepository(
        events=events,
        fail_status=SubmissionAttemptStatus.ACKNOWLEDGED,
    )
    orders = RecordingOrderService(events=events)
    service, control, _, _ = _service(repository=repository, order_service=orders)
    with pytest.raises(RuntimeError, match="cannot save acknowledged"):
        await _execute(service)
    assert orders.calls == 1
    assert (
        next(iter(repository.attempts.values())).status
        is SubmissionAttemptStatus.UNRESOLVED
    )
    assert events == [
        "save:prepared",
        "submit",
        "save:acknowledged",
        "save:unresolved",
    ]
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_protection_failure_after_acknowledgement_preserves_acknowledgement() -> (
    None
):
    """Keep known remote acknowledgement distinct from later protection failure."""
    repository = RecordingSubmissionAttemptRepository()
    service, control, _, orders = _service(
        repository=repository,
        protection_service=FakeProtectionService(error=RuntimeError("missing TP")),
    )

    with pytest.raises(RuntimeError, match="missing TP"):
        await _execute(service)

    assert orders.calls == 1
    assert (
        next(iter(repository.attempts.values())).status
        is SubmissionAttemptStatus.ACKNOWLEDGED
    )
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_completed_attempts_generate_distinct_logical_client_ids() -> None:
    """Generate one unique identity per independently acknowledged entry."""
    service, _, repository, orders = _service()

    await _execute(service)
    await _execute(service)

    assert orders.calls == 2
    assert len(repository.attempts) == 2
    assert (
        len({attempt.client_order_id for attempt in repository.attempts.values()}) == 2
    )


@pytest.mark.asyncio
async def test_known_rejection_is_terminal_without_reconciliation() -> None:
    """Persist an explicit remote rejection without an authoritative read."""
    events: list[str] = []
    repository = RecordingSubmissionAttemptRepository(events=events)
    orders = RecordingOrderService(
        events=events,
        error=ExchangeOrderRejectedError("rejected"),
    )
    service, _, _, _ = _service(repository=repository, order_service=orders)

    with pytest.raises(ExchangeOrderRejectedError):
        await _execute(service)

    assert orders.calls == 1
    assert (
        next(iter(repository.attempts.values())).status
        is SubmissionAttemptStatus.REJECTED
    )
    assert events == ["save:prepared", "submit", "save:rejected"]


@pytest.mark.asyncio
async def test_ambiguous_submission_reconciles_using_the_original_client_id() -> None:
    """Resolve a lost POST response through bounded GET-only lookup."""
    events: list[str] = []
    repository = RecordingSubmissionAttemptRepository(events=events)
    orders = RecordingOrderService(
        events=events,
        error=ExchangeOrderOutcomeUnknownError("timeout"),
        reconcile_echo_client_order_id=True,
    )
    service, control, _, _ = _service(repository=repository, order_service=orders)

    order = await _execute(service)

    attempt = next(iter(repository.attempts.values()))
    assert orders.calls == 1
    assert order.client_order_id == attempt.client_order_id
    assert attempt.status is SubmissionAttemptStatus.COMPLETED
    assert attempt.exchange_order_id == "entry-1"
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_ambiguous_submission_handles_delayed_order_visibility() -> None:
    """Retry only the authoritative GET when the first read has no order yet."""
    events: list[str] = []
    repository = RecordingSubmissionAttemptRepository(events=events)
    orders = RecordingOrderService(
        events=events,
        error=ExchangeOrderOutcomeUnknownError("timeout"),
        reconcile_echo_client_order_id=True,
        reconciled_orders=[ExchangeOrderNotFoundError("not found")],
    )
    service, _, _, _ = _service(repository=repository, order_service=orders)

    await _execute(service)

    assert orders.calls == 1
    assert (
        next(iter(repository.attempts.values())).status
        is SubmissionAttemptStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_ambiguous_exhaustion_remains_unresolved_and_blocks_entry() -> None:
    """Leave unresolved state fail-closed without another entry POST."""
    events: list[str] = []
    repository = RecordingSubmissionAttemptRepository(events=events)
    orders = RecordingOrderService(
        events=events,
        error=ExchangeOrderOutcomeUnknownError("timeout"),
        reconciled_orders=[
            ExchangeOrderNotFoundError("not found"),
            ExchangeOrderNotFoundError("not found"),
        ],
    )
    service, control, _, _ = _service(repository=repository, order_service=orders)

    with pytest.raises(RuntimeError, match="remains unresolved"):
        await _execute(service)
    with pytest.raises(RuntimeError, match="unresolved"):
        await _execute(service)

    assert orders.calls == 1
    assert (
        next(iter(repository.attempts.values())).status
        is SubmissionAttemptStatus.UNRESOLVED
    )
    assert "position protection" in control.get_missing_startup_requirements()
