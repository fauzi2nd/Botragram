"""Natural LIVE exit and orphan-protection recovery regressions."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.enums import (
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
from botragram.models import Order, Position, SubmissionAttempt
from botragram.services import LiveNaturalExitRecoveryService
from botragram.storage.memory import (
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
        ambiguous_after_remove: bool = False,
        keep_after_cancel: bool = False,
    ) -> None:
        self.positions = positions
        self.protections = list(protections)
        self.exact_only_protections = list(exact_only_protections)
        self.ambiguous_after_remove = ambiguous_after_remove
        self.keep_after_cancel = keep_after_cancel
        self.cancel_calls: list[tuple[str, str]] = []

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
