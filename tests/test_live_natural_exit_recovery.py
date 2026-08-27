"""Natural LIVE exit and orphan-protection recovery regressions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.enums import (
    ClosedPositionReason,
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    StrategyType,
    SubmissionAttemptStatus,
)
from botragram.exceptions import (
    ExchangeOrderNotFoundError,
    ExchangeOrderOutcomeUnknownError,
)
from botragram.models import (
    ClosedPositionLifecycle,
    Order,
    PendingClosedPositionLifecycle,
    Position,
    SubmissionAttempt,
    Trade,
)
from botragram.services import (
    ClosedPositionLifecycleService,
    LiveNaturalExitRecoveryService,
)
from botragram.storage.memory import (
    MemoryClosedPositionLifecycleRepository,
    MemoryPositionRepository,
    MemorySubmissionAttemptRepository,
)

_NOW = datetime(2026, 8, 21, tzinfo=UTC)
_SYMBOL = "4USDT"
_STOP_ID = "bsl-00000000000000000000000000000000"
_TP_ID = "btp-00000000000000000000000000000000"


class FakeNaturalExitExchange:
    """Expose deterministic authoritative state and cancellation outcomes."""

    def __init__(
        self,
        *,
        positions: tuple[Position, ...] = (),
        protections: tuple[Order, ...] = (),
        exact_only_protections: tuple[Order, ...] = (),
        protection_history: tuple[Order, ...] = (),
        ambiguous_after_remove: bool = False,
        keep_after_cancel: bool = False,
    ) -> None:
        self.positions = positions
        self.protections = list(protections)
        self.exact_only_protections = list(exact_only_protections)
        self.protection_history = protection_history
        self.ambiguous_after_remove = ambiguous_after_remove
        self.keep_after_cancel = keep_after_cancel
        self.cancel_calls: list[tuple[str, str]] = []
        self.history_calls: list[tuple[str, datetime]] = []

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[Position, ...]:
        return tuple(
            position
            for position in self.positions
            if symbol is None or position.symbol == symbol.upper()
        )

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[Order, ...]:
        return tuple(
            order
            for order in self.protections
            if symbol is None or order.symbol == symbol.upper()
        )

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        for order in (*self.protections, *self.exact_only_protections):
            if order.symbol == symbol.upper() and order.client_order_id == client_id:
                return order
        raise ExchangeOrderNotFoundError("configured protection not found")

    async def get_protection_order_history(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> tuple[Order, ...]:
        del end_time
        self.history_calls.append((symbol.upper(), start_time))
        return tuple(
            order for order in self.protection_history if order.symbol == symbol.upper()
        )

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> None:
        self.cancel_calls.append((symbol.upper(), client_id))

        if not self.keep_after_cancel:
            self.protections = [
                order
                for order in self.protections
                if order.client_order_id != client_id
            ]
            self.exact_only_protections = [
                order
                for order in self.exact_only_protections
                if order.client_order_id != client_id
            ]

        if self.ambiguous_after_remove or self.keep_after_cancel:
            raise ExchangeOrderOutcomeUnknownError("configured ambiguous cancellation")


def _position() -> Position:
    return Position(
        symbol=_SYMBOL,
        side=PositionSide.SHORT,
        quantity=Decimal("885"),
        entry_price=Decimal("0.01129"),
        current_price=Decimal("0.01151"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("0.01151"),
        take_profit=Decimal("0.01084"),
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        stop_loss_client_algo_id=_STOP_ID,
        take_profit_client_algo_id=_TP_ID,
        entry_client_order_id="btg-00000000000000000000000000000000",
    )


def _protection(
    *,
    order_type: OrderType,
    client_id: str,
    trigger: str,
) -> Order:
    return Order(
        order_id=f"order-{order_type.value}",
        symbol=_SYMBOL,
        side=OrderSide.BUY,
        order_type=order_type,
        status=OrderStatus.NEW,
        quantity=Decimal("885"),
        executed_quantity=Decimal("0"),
        price=None,
        stop_price=Decimal(trigger),
        created_at=_NOW,
        updated_at=_NOW,
        client_order_id=client_id,
    )


async def _repository() -> MemoryPositionRepository:
    repository = MemoryPositionRepository()
    await repository.save(position=_position())
    return repository


@pytest.mark.asyncio
async def test_reconcile_cancels_exact_orphan_tp_and_deletes_stale_position() -> None:
    repository = await _repository()
    exchange = FakeNaturalExitExchange(
        protections=(
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
        )
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == [(_SYMBOL, _TP_ID)]
    assert exchange.protections == []
    assert await repository.get_by_symbol(symbol=_SYMBOL) is None


@pytest.mark.asyncio
async def test_reconcile_cancels_both_exact_orphans_deterministically() -> None:
    repository = await _repository()
    exchange = FakeNaturalExitExchange(
        protections=(
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
            _protection(
                order_type=OrderType.STOP_MARKET,
                client_id=_STOP_ID,
                trigger="0.01151",
            ),
        )
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == [
        (_SYMBOL, _STOP_ID),
        (_SYMBOL, _TP_ID),
    ]
    assert await repository.get_by_symbol(symbol=_SYMBOL) is None


@pytest.mark.asyncio
async def test_reconcile_fails_closed_on_unknown_orphan_identity() -> None:
    repository = await _repository()
    unknown = _protection(
        order_type=OrderType.TAKE_PROFIT_MARKET,
        client_id="external-protection",
        trigger="0.01084",
    )
    exchange = FakeNaturalExitExchange(protections=(unknown,))
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    with pytest.raises(RuntimeError, match="durable client identity"):
        await service.reconcile()

    assert exchange.cancel_calls == []
    assert await repository.get_by_symbol(symbol=_SYMBOL) is not None


@pytest.mark.asyncio
async def test_reconcile_accepts_ambiguous_delete_when_get_proves_absent() -> None:
    repository = await _repository()
    exchange = FakeNaturalExitExchange(
        protections=(
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
        ),
        ambiguous_after_remove=True,
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == [(_SYMBOL, _TP_ID)]
    assert await repository.get_by_symbol(symbol=_SYMBOL) is None


@pytest.mark.asyncio
async def test_reconcile_preserves_stale_position_when_delete_unresolved() -> None:
    repository = await _repository()
    exchange = FakeNaturalExitExchange(
        protections=(
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
        ),
        keep_after_cancel=True,
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    with pytest.raises(RuntimeError, match="Ambiguous LIVE orphan"):
        await service.reconcile()

    assert exchange.cancel_calls == [(_SYMBOL, _TP_ID)]
    assert await repository.get_by_symbol(symbol=_SYMBOL) is not None


@pytest.mark.asyncio
async def test_reconcile_does_not_retry_delete_when_bulk_snapshot_lags() -> None:
    """Require exact lookup rather than a stale empty bulk response after DELETE."""

    class StaleBulkAfterDeleteExchange(FakeNaturalExitExchange):
        def __init__(self) -> None:
            super().__init__(
                protections=(
                    _protection(
                        order_type=OrderType.TAKE_PROFIT_MARKET,
                        client_id=_TP_ID,
                        trigger="0.01084",
                    ),
                ),
            )
            self.hide_from_bulk = False

        async def get_open_protection_orders(
            self,
            *,
            symbol: str | None = None,
        ) -> tuple[Order, ...]:
            if self.hide_from_bulk:
                return ()
            return await super().get_open_protection_orders(symbol=symbol)

        async def cancel_protection_order(
            self,
            *,
            symbol: str,
            client_id: str,
        ) -> None:
            self.cancel_calls.append((symbol.upper(), client_id))
            self.hide_from_bulk = True

    repository = await _repository()
    exchange = StaleBulkAfterDeleteExchange()
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    with pytest.raises(RuntimeError, match="remains active after cancellation"):
        await service.reconcile()

    assert exchange.cancel_calls == [(_SYMBOL, _TP_ID)]
    assert await repository.get_by_symbol(symbol=_SYMBOL) is not None


@pytest.mark.asyncio
async def test_reconcile_waits_for_delayed_exact_cancellation_without_repeating_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow Binance's delayed exact GET result without a second DELETE."""

    class DelayedExactCancellationExchange(FakeNaturalExitExchange):
        def __init__(self) -> None:
            super().__init__(
                protections=(
                    _protection(
                        order_type=OrderType.TAKE_PROFIT_MARKET,
                        client_id=_TP_ID,
                        trigger="0.01084",
                    ),
                )
            )
            self.exact_reads_after_cancel = 0

        async def cancel_protection_order(
            self,
            *,
            symbol: str,
            client_id: str,
        ) -> None:
            self.cancel_calls.append((symbol.upper(), client_id))

        async def get_protection_order_by_client_id(
            self,
            *,
            symbol: str,
            client_id: str,
        ) -> Order:
            if self.cancel_calls:
                self.exact_reads_after_cancel += 1
                if self.exact_reads_after_cancel == 3:
                    self.protections = []
                    raise ExchangeOrderNotFoundError("configured cancellation proof")
            return await super().get_protection_order_by_client_id(
                symbol=symbol,
                client_id=client_id,
            )

    async def no_delay(_: float) -> None:
        """Keep the bounded reconciliation test fast."""

    monkeypatch.setattr(
        "botragram.services.live_natural_exit_recovery_service.asyncio.sleep",
        no_delay,
    )
    repository = await _repository()
    exchange = DelayedExactCancellationExchange()
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == [(_SYMBOL, _TP_ID)]
    assert exchange.exact_reads_after_cancel >= 3
    assert await repository.get_by_symbol(symbol=_SYMBOL) is None


@pytest.mark.asyncio
async def test_reconcile_leaves_active_position_protection_untouched() -> None:
    position = _position()
    repository = await _repository()
    exchange = FakeNaturalExitExchange(
        positions=(position,),
        protections=(
            _protection(
                order_type=OrderType.STOP_MARKET,
                client_id=_STOP_ID,
                trigger="0.01151",
            ),
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
        ),
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == []
    assert await repository.get_by_symbol(symbol=_SYMBOL) == position


@pytest.mark.asyncio
async def test_reconcile_deletes_stale_position_when_no_orphan_remains() -> None:
    repository = await _repository()
    exchange = FakeNaturalExitExchange()
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == []
    assert await repository.get_by_symbol(symbol=_SYMBOL) is None


@pytest.mark.asyncio
async def test_reconcile_blocks_before_mutation_when_attempt_is_incomplete() -> None:
    """Preserve 5C.4E/5C.4F lifecycle ownership until attempt recovery finishes."""
    repository = await _repository()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(
        attempt=SubmissionAttempt(
            client_order_id="btg-00000000000000000000000000000000",
            symbol=_SYMBOL,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("885"),
            signal_generated_at=_NOW,
            interval=Interval.M15,
            strategy_type=StrategyType.EMA_CROSS,
            status=SubmissionAttemptStatus.ACKNOWLEDGED,
            exchange_order_id="entry-1",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    exchange = FakeNaturalExitExchange(
        protections=(
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
        )
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=attempts,
    )

    with pytest.raises(RuntimeError, match="lifecycle recovery"):
        await service.reconcile()

    assert exchange.cancel_calls == []
    assert len(exchange.protections) == 1
    assert await repository.get_by_symbol(symbol=_SYMBOL) is not None


@pytest.mark.asyncio
async def test_reconcile_exact_lookup_catches_leg_hidden_from_bulk_snapshot() -> None:
    """Preserve durable identity when the bulk open-order view momentarily lags."""
    repository = await _repository()
    exchange = FakeNaturalExitExchange(
        exact_only_protections=(
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
        )
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == [(_SYMBOL, _TP_ID)]
    assert exchange.exact_only_protections == []
    assert await repository.get_by_symbol(symbol=_SYMBOL) is None


@pytest.mark.asyncio
async def test_reconcile_rechecks_zero_exposure_before_durable_delete() -> None:
    """Do not delete local identity if exposure appears after final bulk snapshot."""

    class ReappearingPositionExchange(FakeNaturalExitExchange):
        def __init__(self) -> None:
            super().__init__()
            self.position_reads = 0

        async def get_positions(
            self,
            *,
            symbol: str | None = None,
        ) -> tuple[Position, ...]:
            self.position_reads += 1
            if self.position_reads <= 2:
                return ()
            position = _position()
            if symbol is None or position.symbol == symbol.upper():
                return (position,)
            return ()

    repository = await _repository()
    exchange = ReappearingPositionExchange()
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    with pytest.raises(RuntimeError, match="exposure reappeared"):
        await service.reconcile()

    assert exchange.cancel_calls == []
    assert await repository.get_by_symbol(symbol=_SYMBOL) is not None


@pytest.mark.asyncio
async def test_reconcile_accepts_exact_pending_stop_orphan() -> None:
    """Treat an interrupted stepped STOP as durable owned orphan protection."""
    pending_id = "bsl-22222222222222222222222222222222"
    position = replace(
        _position(),
        pending_stop_loss=Decimal("0.01140"),
        pending_stop_loss_client_algo_id=pending_id,
        pending_protection_step=1,
    )
    repository = MemoryPositionRepository()
    await repository.save(position=position)
    exchange = FakeNaturalExitExchange(
        protections=(
            _protection(
                order_type=OrderType.STOP_MARKET,
                client_id=pending_id,
                trigger="0.01140",
            ),
        )
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == [(_SYMBOL, pending_id)]
    assert await repository.get_by_symbol(symbol=_SYMBOL) is None


class SnapshotNaturalExitExchange(FakeNaturalExitExchange):
    """Return one deterministic sequence of complete portfolio snapshots."""

    def __init__(
        self,
        *,
        snapshots: tuple[tuple[Position, ...], ...],
        protections: tuple[Order, ...] = (),
    ) -> None:
        super().__init__(protections=protections)
        self.snapshots = snapshots
        self.snapshot_index = 0

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[Position, ...]:
        if symbol is not None:
            return await super().get_positions(symbol=symbol)
        snapshot = self.snapshots[min(self.snapshot_index, len(self.snapshots) - 1)]
        self.snapshot_index += 1
        self.positions = snapshot
        return snapshot


def _completed_attempt(*, position: Position) -> SubmissionAttempt:
    """Build durable evidence for one completed protected entry."""
    entry_client_order_id = position.entry_client_order_id
    assert entry_client_order_id is not None
    return SubmissionAttempt(
        client_order_id=entry_client_order_id,
        symbol=position.symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=position.quantity,
        signal_generated_at=_NOW,
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        status=SubmissionAttemptStatus.COMPLETED,
        exchange_order_id="entry-1",
        created_at=_NOW,
        updated_at=_NOW,
    )


@pytest.mark.asyncio
async def test_reconcile_adopts_stable_fresh_protected_entry() -> None:
    """Retry GET-only after a newly completed entry settles into visibility."""
    position = _position()
    repository = await _repository()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=_completed_attempt(position=position))
    exchange = SnapshotNaturalExitExchange(
        snapshots=((), (position,), (position,), (position,), (position,)),
        protections=(
            _protection(
                order_type=OrderType.STOP_MARKET,
                client_id=_STOP_ID,
                trigger="0.01151",
            ),
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
        ),
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=attempts,
    )

    await service.reconcile()

    assert exchange.cancel_calls == []
    assert exchange.snapshot_index == 5
    assert await repository.get_by_symbol(symbol=_SYMBOL) == position


@pytest.mark.asyncio
async def test_reconcile_fails_closed_on_new_unmanaged_exposure() -> None:
    """Never retry an added exposure that lacks durable ownership evidence."""
    position = _position()
    exchange = SnapshotNaturalExitExchange(snapshots=((), (position,)))
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=MemoryPositionRepository(),
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    with pytest.raises(RuntimeError, match="gained an unmanaged exposure"):
        await service.reconcile()

    assert exchange.cancel_calls == []


@pytest.mark.asyncio
async def test_reconcile_retries_a_known_natural_exit_until_stable() -> None:
    """Treat a durable position disappearing mid-pass as retryable read state."""
    position = _position()
    repository = await _repository()
    exchange = SnapshotNaturalExitExchange(
        snapshots=((position,), (), (), (), ()),
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == []
    assert await repository.get_by_symbol(symbol=_SYMBOL) is None


@pytest.mark.asyncio
async def test_reconcile_retries_when_a_position_exits_after_initial_reads() -> None:
    """Retry GET-only when a stable active position exits before final order read."""
    position = _position()
    repository = await _repository()
    exchange = SnapshotNaturalExitExchange(
        snapshots=((position,), (position,), (), (), (), ()),
        protections=(
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
        ),
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    await service.reconcile()

    assert exchange.cancel_calls == [(_SYMBOL, _TP_ID)]
    assert await repository.get_by_symbol(symbol=_SYMBOL) is None


@pytest.mark.asyncio
async def test_reconcile_fails_closed_when_portfolio_never_stabilizes() -> None:
    """Bound changed snapshots without retrying a mutation or looping forever."""
    position = _position()
    repository = await _repository()
    exchange = SnapshotNaturalExitExchange(
        snapshots=((position,), (), (position,), (), (position,), ()),
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
    )

    with pytest.raises(RuntimeError, match="did not stabilize"):
        await service.reconcile()

    assert exchange.cancel_calls == []
    assert await repository.get_by_symbol(symbol=_SYMBOL) == position


@pytest.mark.asyncio
async def test_reconcile_fails_closed_when_fresh_protection_is_unknown() -> None:
    """Require exact STOP and TP proof before accepting a newly visible entry."""

    class UnknownProtectionExchange(SnapshotNaturalExitExchange):
        async def get_protection_order_by_client_id(
            self,
            *,
            symbol: str,
            client_id: str,
        ) -> Order:
            raise ExchangeOrderOutcomeUnknownError("configured protection unknown")

    position = _position()
    repository = await _repository()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=_completed_attempt(position=position))
    exchange = UnknownProtectionExchange(snapshots=((), (position,)))
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=attempts,
    )

    with pytest.raises(ExchangeOrderOutcomeUnknownError):
        await service.reconcile()

    assert exchange.cancel_calls == []


@pytest.mark.asyncio
async def test_reconcile_deletes_proven_exit_when_performance_history_fails() -> None:
    """Do not let post-cleanup telemetry failure block a safe deletion."""

    class FailingTradeHistory:
        async def get_trades_for_order(
            self,
            *,
            symbol: str,
            order_id: str,
        ) -> tuple[Trade, ...]:
            del symbol, order_id
            raise RuntimeError("configured performance history failure")

    repository = await _repository()
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=_completed_attempt(position=_position()))
    lifecycle_repository = MemoryClosedPositionLifecycleRepository()
    filled_stop = replace(
        _protection(
            order_type=OrderType.STOP_MARKET,
            client_id=_STOP_ID,
            trigger="0.01151",
        ),
        order_id="filled-stop",
        status=OrderStatus.FILLED,
    )
    exchange = FakeNaturalExitExchange(exact_only_protections=(filled_stop,))
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=repository,
        submission_attempt_repository=attempts,
        closed_lifecycle_service=ClosedPositionLifecycleService(
            repository=lifecycle_repository,
            trade_history=FailingTradeHistory(),
        ),
    )

    await service.reconcile()

    assert await repository.get_by_symbol(symbol=_SYMBOL) is None
    assert len(await lifecycle_repository.get_pending()) == 1


@pytest.mark.asyncio
async def test_staging_failure_preserves_natural_exit_identity_until_restart() -> None:
    """Retry durable staging without repeating completed protection cleanup."""

    class FailOnceLifecycleRepository(MemoryClosedPositionLifecycleRepository):
        def __init__(self) -> None:
            super().__init__()
            self.fail_stage = True
            self.stage_calls = 0

        async def stage(
            self,
            *,
            lifecycle: PendingClosedPositionLifecycle,
        ) -> None:
            self.stage_calls += 1
            if self.fail_stage:
                raise RuntimeError("configured lifecycle stage failure")
            await super().stage(lifecycle=lifecycle)

    class ExactTradeHistory:
        async def get_trades_for_order(
            self,
            *,
            symbol: str,
            order_id: str,
        ) -> tuple[Trade, ...]:
            del symbol
            return {
                "entry-1": (
                    _fill(
                        trade_id="entry-fill",
                        order_id="entry-1",
                        side=OrderSide.SELL,
                        realized_pnl="0",
                    ),
                ),
                "filled-exit": (
                    _fill(
                        trade_id="exit-fill",
                        order_id="filled-exit",
                        side=OrderSide.BUY,
                        realized_pnl="2",
                    ),
                ),
            }[order_id]

    position = _position()
    positions = MemoryPositionRepository()
    await positions.save(position=position)
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=_completed_attempt(position=position))
    lifecycle_repository = FailOnceLifecycleRepository()
    filled_stop = replace(
        _protection(
            order_type=OrderType.STOP_MARKET,
            client_id=_STOP_ID,
            trigger="0.01151",
        ),
        order_id="filled-exit",
        status=OrderStatus.FILLED,
        executed_quantity=position.quantity,
    )
    exchange = FakeNaturalExitExchange(
        protections=(
            _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_id=_TP_ID,
                trigger="0.01084",
            ),
        ),
        exact_only_protections=(filled_stop,),
    )

    def build_service() -> LiveNaturalExitRecoveryService:
        return LiveNaturalExitRecoveryService(
            exchange_client=exchange,
            position_repository=positions,
            submission_attempt_repository=attempts,
            closed_lifecycle_service=ClosedPositionLifecycleService(
                repository=lifecycle_repository,
                trade_history=ExactTradeHistory(),
            ),
        )

    with pytest.raises(RuntimeError, match="configured lifecycle stage failure"):
        await build_service().reconcile()

    assert await positions.get_by_symbol(symbol=_SYMBOL) == position
    assert exchange.cancel_calls == [(_SYMBOL, _TP_ID)]
    assert await lifecycle_repository.get_completed() == ()

    lifecycle_repository.fail_stage = False
    await build_service().reconcile()
    completed = await lifecycle_repository.get_completed()

    assert await positions.get_by_symbol(symbol=_SYMBOL) is None
    assert exchange.cancel_calls == [(_SYMBOL, _TP_ID)]
    assert lifecycle_repository.stage_calls == 2
    assert len(completed) == 1
    assert completed[0].entry_client_order_id == position.entry_client_order_id


class _ExactLifecycleTradeHistory:
    """Return complete fills for the shared entry and recovered exit IDs."""

    async def get_trades_for_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> tuple[Trade, ...]:
        del symbol
        if order_id == "entry-1":
            return (
                _fill(
                    trade_id="entry-fill",
                    order_id=order_id,
                    side=OrderSide.SELL,
                    realized_pnl="0",
                ),
            )
        if order_id == "filled-exit":
            return (
                _fill(
                    trade_id="exit-fill",
                    order_id=order_id,
                    side=OrderSide.BUY,
                    realized_pnl="2",
                ),
            )
        return ()


@pytest.mark.asyncio
async def test_restart_recovers_filled_stop_replacement_lost_before_commit() -> None:
    """Converge the soak race from bounded authoritative algo history."""
    position = _position()
    positions = MemoryPositionRepository()
    await positions.save(position=position)
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=_completed_attempt(position=position))
    lifecycles = MemoryClosedPositionLifecycleRepository()
    replacement = replace(
        _protection(
            order_type=OrderType.STOP_MARKET,
            client_id="bsl-22222222222222222222222222222222",
            trigger="0.01120",
        ),
        order_id="replacement-algo",
        execution_order_id="filled-exit",
        status=OrderStatus.FILLED,
        executed_quantity=position.quantity,
    )
    exchange = FakeNaturalExitExchange(protection_history=(replacement,))
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=positions,
        submission_attempt_repository=attempts,
        closed_lifecycle_service=ClosedPositionLifecycleService(
            repository=lifecycles,
            trade_history=_ExactLifecycleTradeHistory(),
        ),
    )

    await service.reconcile()
    await service.reconcile()
    completed = await lifecycles.get_completed()

    assert await positions.get_by_symbol(symbol=_SYMBOL) is None
    assert exchange.history_calls == [(_SYMBOL, position.opened_at)]
    assert exchange.cancel_calls == []
    assert len(completed) == 1
    assert completed[0].ownership.exit_client_order_id == replacement.client_order_id
    assert completed[0].ownership.close_reason is ClosedPositionReason.STEPPED_STOP


@pytest.mark.asyncio
async def test_restart_keeps_identity_when_filled_replacement_is_ambiguous() -> None:
    """Never guess lifecycle ownership from multiple matching historical exits."""
    position = _position()
    positions = MemoryPositionRepository()
    await positions.save(position=position)
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=_completed_attempt(position=position))
    replacements = tuple(
        replace(
            _protection(
                order_type=OrderType.STOP_MARKET,
                client_id=f"bsl-{digit * 32}",
                trigger=trigger,
            ),
            order_id=f"replacement-{digit}",
            execution_order_id=f"filled-{digit}",
            status=OrderStatus.FILLED,
            executed_quantity=position.quantity,
        )
        for digit, trigger in (("2", "0.01120"), ("3", "0.01110"))
    )
    lifecycles = MemoryClosedPositionLifecycleRepository()
    exchange = FakeNaturalExitExchange(protection_history=replacements)
    service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=positions,
        submission_attempt_repository=attempts,
        closed_lifecycle_service=ClosedPositionLifecycleService(
            repository=lifecycles,
            trade_history=_ExactLifecycleTradeHistory(),
        ),
    )

    with pytest.raises(RuntimeError, match="exactly one authoritative FILLED"):
        await service.reconcile()

    assert await positions.get_by_symbol(symbol=_SYMBOL) == position
    assert await lifecycles.get_completed() == ()
    assert exchange.cancel_calls == []


def _fill(
    *,
    trade_id: str,
    order_id: str,
    side: OrderSide,
    realized_pnl: str,
) -> Trade:
    """Build one exact Futures fill for lifecycle enrichment."""
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        symbol=_SYMBOL,
        side=side,
        price=Decimal("0.011"),
        quantity=Decimal("885"),
        quote_quantity=Decimal("9.735"),
        fee=Decimal("0.1"),
        fee_asset="USDT",
        realized_pnl=Decimal(realized_pnl),
        executed_at=_NOW,
    )


@pytest.mark.parametrize(
    ("order_type", "client_id", "trigger", "protection_step", "expected_reason"),
    (
        (
            OrderType.TAKE_PROFIT_MARKET,
            _TP_ID,
            "0.01084",
            0,
            ClosedPositionReason.TAKE_PROFIT,
        ),
        (
            OrderType.STOP_MARKET,
            _STOP_ID,
            "0.01151",
            0,
            ClosedPositionReason.STOP_LOSS,
        ),
        (
            OrderType.STOP_MARKET,
            _STOP_ID,
            "0.01151",
            1,
            ClosedPositionReason.STEPPED_STOP,
        ),
    ),
)
@pytest.mark.asyncio
async def test_natural_exit_records_one_tp_sl_or_stepped_stop_lifecycle(
    order_type: OrderType,
    client_id: str,
    trigger: str,
    protection_step: int,
    expected_reason: ClosedPositionReason,
) -> None:
    """Record one authoritative lifecycle for every natural close reason."""

    class ExactTradeHistory:
        async def get_trades_for_order(
            self,
            *,
            symbol: str,
            order_id: str,
        ) -> tuple[Trade, ...]:
            del symbol
            return {
                "entry-1": (
                    _fill(
                        trade_id="entry-fill",
                        order_id="entry-1",
                        side=OrderSide.SELL,
                        realized_pnl="0",
                    ),
                ),
                "filled-exit": (
                    _fill(
                        trade_id="exit-fill",
                        order_id="filled-exit",
                        side=OrderSide.BUY,
                        realized_pnl="2",
                    ),
                ),
            }[order_id]

    position = replace(_position(), protection_step=protection_step)
    position_repository = MemoryPositionRepository()
    await position_repository.save(position=position)
    attempts = MemorySubmissionAttemptRepository()
    await attempts.save(attempt=_completed_attempt(position=position))
    lifecycle_repository = MemoryClosedPositionLifecycleRepository()
    filled_exit = replace(
        _protection(
            order_type=order_type,
            client_id=client_id,
            trigger=trigger,
        ),
        order_id="filled-exit",
        status=OrderStatus.FILLED,
        executed_quantity=position.quantity,
    )
    service = LiveNaturalExitRecoveryService(
        exchange_client=FakeNaturalExitExchange(exact_only_protections=(filled_exit,)),
        position_repository=position_repository,
        submission_attempt_repository=attempts,
        closed_lifecycle_service=ClosedPositionLifecycleService(
            repository=lifecycle_repository,
            trade_history=ExactTradeHistory(),
        ),
    )

    await service.reconcile()
    completed = await lifecycle_repository.get_completed()

    assert await position_repository.get_by_symbol(symbol=_SYMBOL) is None
    assert len(completed) == 1
    assert isinstance(completed[0], ClosedPositionLifecycle)
    assert completed[0].ownership.close_reason is expected_reason


@pytest.mark.asyncio
async def test_performance_ownership_failure_preserves_durable_identity() -> None:
    """Do not delete Position when lifecycle ownership cannot be proven durable."""

    class FailingLifecycleRepository(MemoryClosedPositionLifecycleRepository):
        async def get_by_entry_client_order_id(
            self,
            *,
            entry_client_order_id: str,
        ) -> ClosedPositionLifecycle | PendingClosedPositionLifecycle | None:
            del entry_client_order_id
            raise RuntimeError("configured lifecycle ownership failure")

    class EmptyTradeHistory:
        async def get_trades_for_order(
            self,
            *,
            symbol: str,
            order_id: str,
        ) -> tuple[Trade, ...]:
            del symbol, order_id
            return ()

    repository = await _repository()
    service = LiveNaturalExitRecoveryService(
        exchange_client=FakeNaturalExitExchange(),
        position_repository=repository,
        submission_attempt_repository=MemorySubmissionAttemptRepository(),
        closed_lifecycle_service=ClosedPositionLifecycleService(
            repository=FailingLifecycleRepository(),
            trade_history=EmptyTradeHistory(),
        ),
    )

    with pytest.raises(RuntimeError, match="configured lifecycle ownership failure"):
        await service.reconcile()

    assert await repository.get_by_symbol(symbol=_SYMBOL) is not None
