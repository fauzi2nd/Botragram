"""LIVE acknowledged-entry post-recovery tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app import TradingRuntimeControl
from botragram.enums import (
    Interval,
    OrderSide,
    OrderType,
    PositionSide,
    StrategyType,
    SubmissionAttemptStatus,
)
from botragram.models import Order, Position, SubmissionAttempt
from botragram.repositories.live_recovery_repository import LiveRecoveryRepository
from botragram.services import (
    LivePostEntryRecoveryResult,
    LivePostEntryRecoveryService,
)
from botragram.services.live_post_entry_recovery_service import LiveOrderFetch
from botragram.storage.memory import MemorySubmissionAttemptRepository
from botragram.storage.memory.live_recovery_repository import (
    MemoryLiveRecoveryRepository,
)

_NOW = datetime(2026, 8, 18, tzinfo=UTC)
_CLIENT_ORDER_ID = "btg-00000000000000000000000000000000"


def _attempt(
    *,
    status: SubmissionAttemptStatus = SubmissionAttemptStatus.ACKNOWLEDGED,
) -> SubmissionAttempt:
    """Build one acknowledged durable entry attempt."""
    return SubmissionAttempt(
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        signal_generated_at=_NOW,
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_SCALPING,
        status=status,
        created_at=_NOW,
        updated_at=_NOW,
        exchange_order_id="entry-42",
    )


def _position(*, quantity: Decimal = Decimal("0.012")) -> Position:
    """Build one exchange-authoritative position snapshot."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=quantity,
        entry_price=Decimal("65100"),
        current_price=Decimal("65100"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )


@dataclass(slots=True)
class FakePositionService:
    """Return configured authoritative position snapshots."""

    responses: list[Position | BaseException | None]
    calls: list[tuple[str, bool]] = field(default_factory=list[tuple[str, bool]])
    saved: list[Position] = field(default_factory=list[Position])
    # Represent a durable persisted position (from prior sync)
    persisted: Position | None = None

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        """Return the next configured position visibility result.

        When `synchronize` is False return the durable persisted value.
        When True, return from the configured visibility `responses`.
        """
        self.calls.append((symbol, synchronize))
        if not synchronize:
            return self.persisted

        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    async def save(self, *, position: Position) -> None:
        """Capture persisted runtime metadata."""
        self.saved.append(position)

    async def delete(self, *, symbol: str) -> bool:
        """Delete persisted position for symbol and return whether it existed."""
        existed = self.persisted is not None and self.persisted.symbol == symbol
        if existed:
            self.persisted = None
        return existed


@dataclass(slots=True)
class FakeProtectionService:
    """Capture one protection-verification request."""

    error: BaseException | None = None
    positions: list[Position] = field(default_factory=list[Position])

    async def ensure(self, *, position: Position) -> Position:
        """Return the verified position or raise the configured failure."""
        self.positions.append(position)
        if self.error is not None:
            raise self.error
        return position

    async def probe_persisted_leg(
        self, *, position: Position, order_type: OrderType, client_id: str
    ) -> str:
        """Return default NOT_FOUND probe result unless overridden in tests."""
        return "not_found"


@dataclass(slots=True)
class FakeOrderService:
    """Return a configured authoritative order snapshot."""

    order: Order

    async def get_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        return self.order


async def _service(
    *,
    responses: list[Position | BaseException | None],
    protection: FakeProtectionService | None = None,
    order: LiveOrderFetch | None = None,
) -> tuple[
    LivePostEntryRecoveryService,
    MemorySubmissionAttemptRepository,
    FakePositionService,
    FakeProtectionService,
    TradingRuntimeControl,
]:
    """Build recovery service dependencies without exchange transport."""
    repository = MemorySubmissionAttemptRepository()
    attempt = _attempt()
    await repository.save(attempt=attempt)
    positions = FakePositionService(responses=responses)
    resolved_protection = protection or FakeProtectionService()
    control = TradingRuntimeControl()
    return (
        LivePostEntryRecoveryService(
            submission_attempt_repository=repository,
            live_recovery_repository=MemoryLiveRecoveryRepository(
                attempt_repo=repository,
                position_repo=positions,  # type: ignore[arg-type]
            ),
            position_service=positions,
            protection_service=resolved_protection,
            runtime_control=control,
            order_service=order,
        ),
        repository,
        positions,
        resolved_protection,
        control,
    )


@pytest.mark.asyncio
async def test_filled_entry_with_zero_position_resolves_without_exposure() -> None:
    """If exchange order is FILLED but position is zero, mark resolved-no-exposure."""
    from botragram.enums import OrderStatus
    from botragram.models import Order

    # position service returns None (not visible)
    order = Order(
        order_id="entry-42",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )

    # Persisted prior position exists (entry context) but current visibility is None
    persisted = _position(quantity=Decimal("4361"))
    service, repository, positions, protection, _control = await _service(
        responses=[None, None], order=FakeOrderService(order=order)
    )
    positions.persisted = persisted

    result = await service.recover_acknowledged(attempt=_attempt())

    completed = await repository.get_by_client_order_id(
        client_order_id=_CLIENT_ORDER_ID
    )
    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE
    assert positions.saved == []
    assert protection.positions == []
    assert completed is not None
    from botragram.enums import SubmissionAttemptStatus

    assert completed.status is SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE

    # Ensure repository no longer reports the attempt as incomplete
    incompletes = await repository.get_incomplete()
    assert all(a.client_order_id != _CLIENT_ORDER_ID for a in incompletes)
    # Runtime readiness should be clear for position protection
    assert "position protection" not in _control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_atomic_repository_transition_is_preferred_for_no_exposure() -> None:
    """A repository-level atomic transition should own the terminal
    no-exposure state.
    """
    from botragram.enums import OrderStatus
    from botragram.models import Order

    order = Order(
        order_id="entry-atomic",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )

    class AtomicRepo(MemorySubmissionAttemptRepository):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[str] = []

        async def resolve_no_exposure(
            self,
            *,
            symbol: str,
            attempt: SubmissionAttempt,
        ) -> None:
            self.calls.append(f"resolve:{symbol}:{attempt.status.value}")
            await self.save(
                attempt=replace(
                    attempt,
                    status=SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE,
                    updated_at=datetime.now(UTC),
                )
            )

    class AtomicLiveRecoveryRepo(LiveRecoveryRepository):
        def __init__(
            self,
            *,
            attempt_repo: AtomicRepo,
            position_repo: FakePositionService,
        ) -> None:
            self._attempt_repo = attempt_repo
            self._position_repo = position_repo

        async def resolve_no_exposure(
            self,
            *,
            symbol: str,
            attempt: SubmissionAttempt,
        ) -> None:
            await self._position_repo.delete(symbol=symbol)
            await self._attempt_repo.resolve_no_exposure(symbol=symbol, attempt=attempt)

    repository = AtomicRepo()
    attempt = _attempt()
    await repository.save(attempt=attempt)
    positions = FakePositionService(responses=[None, None])
    positions.persisted = _position(quantity=Decimal("4361"))
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=repository,
        live_recovery_repository=AtomicLiveRecoveryRepo(
            attempt_repo=repository,
            position_repo=positions,
        ),
        position_service=positions,
        protection_service=FakeProtectionService(),
        runtime_control=TradingRuntimeControl(),
        order_service=FakeOrderService(order=order),
    )

    result = await service.recover_acknowledged(attempt=attempt)

    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE
    assert repository.calls == ["resolve:BTCUSDT:resolved_no_exposure"]
    assert positions.persisted is None
    stored = await repository.get_by_client_order_id(client_order_id=_CLIENT_ORDER_ID)
    assert stored is not None
    assert stored.status is SubmissionAttemptStatus.RESOLVED_NO_EXPOSURE


@pytest.mark.asyncio
async def test_no_persisted_prior_position_blocks_resolution() -> None:
    """A: ACK + FILLED + zero current + NO prior persisted position -> BLOCKED."""
    from botragram.enums import OrderStatus
    from botragram.models import Order

    order = Order(
        order_id="entry-1",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )

    service, repository, positions, _protection, control = await _service(
        responses=[None, None], order=FakeOrderService(order=order)
    )

    # no persisted prior position
    positions.persisted = None

    result = await service.recover_acknowledged(attempt=_attempt())
    assert result is LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE
    acknowledged = await repository.get_by_client_order_id(
        client_order_id=_CLIENT_ORDER_ID
    )
    assert (
        acknowledged is not None
        and acknowledged.status is SubmissionAttemptStatus.ACKNOWLEDGED
    )
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_ambiguous_entry_order_blocks_resolution() -> None:
    """B: ACK + ambiguous/nonterminal entry order + zero position -> BLOCKED."""
    from botragram.enums import OrderStatus
    from botragram.models import Order

    order = Order(
        order_id="entry-2",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0"),
        price=None,
        status=OrderStatus.NEW,
        created_at=_NOW,
        updated_at=_NOW,
    )

    service, repository, positions, _protection, _control = await _service(
        responses=[None, None], order=FakeOrderService(order=order)
    )
    # persisted prior exists so we reach order reconciliation
    from botragram.models import Position

    positions.persisted = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss_client_algo_id="stop-1",
    )

    result = await service.recover_acknowledged(attempt=_attempt())
    assert result is LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE
    acknowledged = await repository.get_by_client_order_id(
        client_order_id=_CLIENT_ORDER_ID
    )
    assert (
        acknowledged is not None
        and acknowledged.status is SubmissionAttemptStatus.ACKNOWLEDGED
    )


@pytest.mark.asyncio
async def test_persisted_stop_found_blocks_resolution() -> None:
    """C: persisted prior position with STOP found -> BLOCKED (no deletion)."""
    from botragram.enums import OrderStatus
    from botragram.models import Order

    order = Order(
        order_id="entry-3",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )

    class ActiveStopProtection(FakeProtectionService):
        async def probe_persisted_leg(
            self, *, position: Position, order_type: OrderType, client_id: str
        ) -> str:
            if order_type is OrderType.STOP_MARKET:
                return "active"
            return "not_found"

    service, _repository, positions, _protection, _control = await _service(
        responses=[None, None],
        protection=ActiveStopProtection(),
        order=FakeOrderService(order=order),
    )
    from botragram.models import Position

    positions.persisted = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss_client_algo_id="stop-1",
        take_profit_client_algo_id="tp-1",
    )

    result = await service.recover_acknowledged(attempt=_attempt())
    assert result is LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE
    # persisted position must not have been deleted
    assert positions.persisted is not None


@pytest.mark.asyncio
async def test_protection_probe_unknown_blocks_resolution() -> None:
    """D: protection probe UNKNOWN/error -> BLOCKED."""
    from botragram.enums import OrderStatus
    from botragram.models import Order

    order = Order(
        order_id="entry-4",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )

    class ErroringProtection(FakeProtectionService):
        async def probe_persisted_leg(
            self, *, position: Position, order_type: OrderType, client_id: str
        ) -> str:
            raise RuntimeError("probe failure")

    service, _repository, positions, _protection, _control = await _service(
        responses=[None, None],
        protection=ErroringProtection(),
        order=FakeOrderService(order=order),
    )
    from botragram.models import Position

    positions.persisted = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss_client_algo_id="stop-1",
        take_profit_client_algo_id="tp-1",
    )

    result = await service.recover_acknowledged(attempt=_attempt())
    assert result is LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE


@pytest.mark.asyncio
async def test_repository_persistence_failure_blocks_and_keeps_observability() -> None:
    """F: failing terminal persistence keeps attempt blocked."""

    class FailingLiveRecoveryRepo(LiveRecoveryRepository):
        async def resolve_no_exposure(
            self,
            *,
            symbol: str,
            attempt: SubmissionAttempt,
        ) -> None:
            raise RuntimeError("persistence failed")

    # build inputs
    from botragram.enums import OrderStatus
    from botragram.models import Order

    order = Order(
        order_id="entry-5",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )

    # assemble service with failing repo
    repository = MemorySubmissionAttemptRepository()
    attempt = _attempt()
    await repository.save(attempt=attempt)
    positions = FakePositionService(responses=[None, None])
    positions.persisted = _position(quantity=Decimal("4361"))
    protection = FakeProtectionService()
    control = TradingRuntimeControl()
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=repository,
        live_recovery_repository=FailingLiveRecoveryRepo(),
        position_service=positions,
        protection_service=protection,
        runtime_control=control,
        order_service=FakeOrderService(order=order),
    )

    with pytest.raises(RuntimeError):
        await service.recover_acknowledged(attempt=attempt)

    # original attempt still ACK
    ack = await repository.get_by_client_order_id(client_order_id=_CLIENT_ORDER_ID)
    assert ack is not None and ack.status is SubmissionAttemptStatus.ACKNOWLEDGED
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_cancellation_propagates_for_various_operations() -> None:
    """G: cancellation during various GET/save operations must propagate."""

    # 1) cancellation during order GET
    class CancelOrderService(FakeOrderService):
        async def get_by_client_order_id(
            self, *, symbol: str, client_order_id: str
        ) -> Order:
            raise asyncio.CancelledError()

    positions = FakePositionService(responses=[None, None])
    positions.persisted = _position(quantity=Decimal("4361"))
    protection = FakeProtectionService()
    repository = MemorySubmissionAttemptRepository()
    attempt = _attempt()
    await repository.save(attempt=attempt)
    from botragram.enums import OrderStatus

    order = Order(
        order_id="entry-cancel",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )

    service = LivePostEntryRecoveryService(
        submission_attempt_repository=repository,
        live_recovery_repository=MemoryLiveRecoveryRepository(
            attempt_repo=repository,
            position_repo=positions,  # type: ignore[arg-type]
        ),
        position_service=positions,
        protection_service=protection,
        runtime_control=TradingRuntimeControl(),
        order_service=CancelOrderService(order=order),
    )

    with pytest.raises(asyncio.CancelledError):
        await service.recover_acknowledged(attempt=attempt)

    # 2) cancellation during protection probe
    class CancelProtection(FakeProtectionService):
        async def probe_persisted_leg(
            self, *, position: Position, order_type: OrderType, client_id: str
        ) -> str:
            raise asyncio.CancelledError()

    positions = FakePositionService(responses=[None, None])
    positions.persisted = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("4361"),
        entry_price=Decimal("65000"),
        current_price=Decimal("65000"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss_client_algo_id="stop-1",
        take_profit_client_algo_id="tp-1",
    )
    repository = MemorySubmissionAttemptRepository()
    attempt = _attempt()
    await repository.save(attempt=attempt)
    order2 = Order(
        order_id="entry-ord2",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )

    service = LivePostEntryRecoveryService(
        submission_attempt_repository=repository,
        live_recovery_repository=MemoryLiveRecoveryRepository(
            attempt_repo=repository,
            position_repo=positions,  # type: ignore[arg-type]
        ),
        position_service=positions,
        protection_service=CancelProtection(),
        runtime_control=TradingRuntimeControl(),
        order_service=FakeOrderService(order=order2),
    )

    with pytest.raises(asyncio.CancelledError):
        await service.recover_acknowledged(attempt=attempt)

    # 3) cancellation during repository save
    class RepoCancelOnSave(LiveRecoveryRepository):
        async def resolve_no_exposure(
            self,
            *,
            symbol: str,
            attempt: SubmissionAttempt,
        ) -> None:
            raise asyncio.CancelledError()

    repository = MemorySubmissionAttemptRepository()
    attempt = _attempt()
    await repository.save(attempt=attempt)
    positions = FakePositionService(responses=[None, None])
    positions.persisted = _position(quantity=Decimal("4361"))
    order3 = Order(
        order_id="entry-3rd",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )
    service = LivePostEntryRecoveryService(
        submission_attempt_repository=repository,
        live_recovery_repository=RepoCancelOnSave(),
        position_service=positions,
        protection_service=FakeProtectionService(),
        runtime_control=TradingRuntimeControl(),
        order_service=FakeOrderService(order=order3),
    )

    with pytest.raises(asyncio.CancelledError):
        await service.recover_acknowledged(attempt=attempt)


@pytest.mark.asyncio
async def test_attempts_in_non_acknowledged_states_are_ignored() -> None:
    """I/J: PREPARED and UNRESOLVED attempts remain blocking (recover rejects)."""
    repository = MemorySubmissionAttemptRepository()
    prepared = _attempt(status=SubmissionAttemptStatus.PREPARED)
    unresolved = _attempt(status=SubmissionAttemptStatus.UNRESOLVED)
    await repository.save(attempt=prepared)
    await repository.save(attempt=unresolved)

    service, _, _, _, _ = await _service(responses=[_position()])

    with pytest.raises(RuntimeError):
        await service.recover_acknowledged(attempt=prepared)

    with pytest.raises(RuntimeError):
        await service.recover_acknowledged(attempt=unresolved)


@pytest.mark.asyncio
async def test_multiple_incomplete_keeps_blocking() -> None:
    """L: multiple incomplete attempts keep the system in blocking state."""
    repository = MemorySubmissionAttemptRepository()
    a1 = _attempt()
    from dataclasses import replace

    a2 = replace(a1, client_order_id="other-000000000000000000000000000000")
    await repository.save(attempt=a1)
    await repository.save(attempt=a2)

    incompletes = await repository.get_incomplete()
    assert len(incompletes) >= 2


@pytest.mark.asyncio
async def test_runtime_continuation_after_resolved_no_exposure_clears_runtime() -> None:
    """N: RESOLVED_NO_EXPOSURE clears runtime position context and readiness."""
    from botragram.enums import OrderStatus
    from botragram.models import Order

    order = Order(
        order_id="entry-6",
        client_order_id=_CLIENT_ORDER_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01"),
        executed_quantity=Decimal("0.01"),
        price=None,
        status=OrderStatus.FILLED,
        created_at=_NOW,
        updated_at=_NOW,
    )

    service, repository, positions, _protection, control = await _service(
        responses=[None, None], order=FakeOrderService(order=order)
    )
    # prior persisted authoritative position
    positions.persisted = _position(quantity=Decimal("4361"))

    result = await service.recover_acknowledged(attempt=_attempt())
    assert result is LivePostEntryRecoveryResult.RESOLVED_NO_EXPOSURE

    # repository excludes the attempt from incomplete set
    incompletes = await repository.get_incomplete()
    assert all(a.client_order_id != _CLIENT_ORDER_ID for a in incompletes)

    # local persisted position is cleared after the durable terminal state is set.
    assert positions.persisted is None
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_visible_position_restores_metadata_and_completes_attempt() -> None:
    """Persist exchange quantities plus durable runtime metadata before completion."""
    service, repository, positions, protection, control = await _service(
        responses=[_position()]
    )

    result = await service.recover_acknowledged(attempt=_attempt())

    completed = await repository.get_by_client_order_id(
        client_order_id=_CLIENT_ORDER_ID,
    )
    assert result is LivePostEntryRecoveryResult.COMPLETED
    assert positions.calls == [("BTCUSDT", True)]
    assert positions.saved[0].quantity == Decimal("0.012")
    assert positions.saved[0].entry_price == Decimal("65100")
    assert positions.saved[0].interval is Interval.M15
    assert positions.saved[0].strategy_type is StrategyType.EMA_SCALPING
    assert protection.positions == positions.saved
    assert completed is not None
    assert completed.status is SubmissionAttemptStatus.COMPLETED
    assert completed.exchange_order_id == "entry-42"
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_visibility_retry_is_bounded_and_keeps_acknowledged_when_absent() -> None:
    """Do not manufacture a position or complete an attempt without visibility."""
    service, repository, positions, protection, control = await _service(
        responses=[None, _position()]
    )

    result = await service.recover_acknowledged(attempt=_attempt())

    assert result is LivePostEntryRecoveryResult.COMPLETED
    assert positions.calls[0] == ("BTCUSDT", True)
    assert len(positions.calls) >= 2 and positions.calls[1][0] == "BTCUSDT"
    assert len(protection.positions) == 1
    completed = await repository.get_by_client_order_id(
        client_order_id=_CLIENT_ORDER_ID,
    )
    assert completed is not None
    assert completed.status is SubmissionAttemptStatus.COMPLETED
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_missing_or_zero_position_remains_acknowledged_and_gate_closed() -> None:
    """Fail closed when the exchange cannot prove an open entry position."""
    service, repository, positions, protection, control = await _service(
        responses=[None, _position(quantity=Decimal("0"))]
    )

    result = await service.recover_acknowledged(attempt=_attempt())

    assert result is LivePostEntryRecoveryResult.POSITION_NOT_VISIBLE
    assert positions.calls[0] == ("BTCUSDT", True)
    assert len(positions.calls) >= 2 and positions.calls[1][0] == "BTCUSDT"
    assert positions.saved == []
    assert protection.positions == []
    acknowledged = await repository.get_by_client_order_id(
        client_order_id=_CLIENT_ORDER_ID,
    )
    assert acknowledged is not None
    assert acknowledged.status is SubmissionAttemptStatus.ACKNOWLEDGED
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_protection_failure_keeps_acknowledged_and_gate_closed() -> None:
    """Never complete a visible position before mandatory protection verifies."""
    protection = FakeProtectionService(error=RuntimeError("missing take profit"))
    service, repository, positions, _, control = await _service(
        responses=[_position()],
        protection=protection,
    )

    with pytest.raises(RuntimeError, match="missing take profit"):
        await service.recover_acknowledged(attempt=_attempt())

    assert len(positions.saved) == 1
    acknowledged = await repository.get_by_client_order_id(
        client_order_id=_CLIENT_ORDER_ID,
    )
    assert acknowledged is not None
    assert acknowledged.status is SubmissionAttemptStatus.ACKNOWLEDGED
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_cancellation_propagates_without_completion() -> None:
    """Keep cancellation distinct from a safe post-entry recovery result."""
    service, repository, _, _, control = await _service(
        responses=[asyncio.CancelledError()]
    )

    with pytest.raises(asyncio.CancelledError):
        await service.recover_acknowledged(attempt=_attempt())

    acknowledged = await repository.get_by_client_order_id(
        client_order_id=_CLIENT_ORDER_ID,
    )
    assert acknowledged is not None
    assert acknowledged.status is SubmissionAttemptStatus.ACKNOWLEDGED
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_non_acknowledged_attempt_is_rejected_without_boundary_calls() -> None:
    """Keep the post-entry stage isolated from submission-order reconciliation."""
    service, _, positions, protection, _ = await _service(responses=[_position()])

    with pytest.raises(RuntimeError, match="acknowledged"):
        await service.recover_acknowledged(
            attempt=_attempt(status=SubmissionAttemptStatus.PREPARED)
        )

    assert positions.calls == []
    assert protection.positions == []
