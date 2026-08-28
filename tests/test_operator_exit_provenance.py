"""Operator-exit provenance survives canonical LIVE reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    ExchangeEnvironment,
    Interval,
    MarketType,
    OperatorExitStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    StrategyType,
    SubmissionAttemptStatus,
    TradeMode,
)
from botragram.models import (
    LiveRuntimePositionContext,
    Order,
    PendingClosedPositionLifecycle,
    Position,
    SubmissionAttempt,
    Trade,
)
from botragram.services import (
    ClosedPositionLifecycleService,
    LiveNaturalExitRecoveryService,
    LivePositionLifecycleCoordinator,
    OperatorExitService,
)
from botragram.storage.memory import (
    MemoryClosedPositionLifecycleRepository,
    MemoryOperatorExitRepository,
    MemoryPositionRepository,
    MemorySubmissionAttemptRepository,
)

_NOW = datetime(2026, 8, 28, tzinfo=UTC)
_SYMBOL = "BTCUSDT"
_ENTRY_CLIENT_ID = "btg-33333333333333333333333333333333"
_ENTRY_ORDER_ID = "entry-order"
_STOP_CLIENT_ID = "bsl-11111111111111111111111111111111"
_TAKE_PROFIT_CLIENT_ID = "btp-22222222222222222222222222222222"


class _CountingLifecycleRepository(MemoryClosedPositionLifecycleRepository):
    """Count durable ownership staging attempts around canonical cleanup."""

    __slots__ = ("stage_calls",)

    def __init__(self) -> None:
        """Initialize empty lifecycle storage and staging telemetry."""
        super().__init__()
        self.stage_calls = 0

    async def stage(self, *, lifecycle: PendingClosedPositionLifecycle) -> None:
        """Record and delegate one immutable ownership staging attempt."""
        self.stage_calls += 1
        await super().stage(lifecycle=lifecycle)


@dataclass(slots=True)
class _OperatorExchange:
    """Model one filled close followed by canonical protection cleanup."""

    position: Position
    protections: dict[str, Order]
    is_flat: bool = False
    close_order: Order | None = None
    close_calls: int = 0
    recovery_get_calls: int = 0
    cancel_calls: list[str] = field(default_factory=list[str])

    async def get_all(self, *, synchronize: bool = False) -> tuple[Position, ...]:
        """Return the current authoritative exposure snapshot."""
        del synchronize
        return () if self.is_flat else (self.position,)

    async def observe(self, *, symbol: str) -> Position | None:
        """Return one exact authoritative exposure without persistence writes."""
        if self.is_flat or symbol.upper() != self.position.symbol.upper():
            return None
        return self.position

    async def close_position_exact(
        self,
        *,
        position: Position,
        client_order_id: str,
    ) -> Order:
        """Fill one exact reduce-only close identity and make exposure flat."""
        assert position == self.position
        self.close_calls += 1
        order = Order(
            order_id="operator-exit-order",
            symbol=position.symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=position.quantity,
            executed_quantity=position.quantity,
            client_order_id=client_order_id,
            created_at=_NOW,
            updated_at=_NOW,
        )
        self.close_order = order
        self.is_flat = True
        return order

    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Return the previously filled close through its durable identity."""
        self.recovery_get_calls += 1
        order = self.close_order
        if (
            order is None
            or order.symbol.upper() != symbol.upper()
            or order.client_order_id != client_order_id
        ):
            raise AssertionError("operator close identity must already exist")
        return order

    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[Position, ...]:
        """Return canonical portfolio reads after the close fill."""
        if self.is_flat:
            return ()
        if symbol is None or symbol.upper() == self.position.symbol.upper():
            return (self.position,)
        return ()

    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> tuple[Order, ...]:
        """Return only active Botragram-owned protection legs."""
        return tuple(
            order
            for order in self.protections.values()
            if order.status is OrderStatus.NEW
            and (symbol is None or order.symbol.upper() == symbol.upper())
        )

    async def get_protection_order_history(
        self,
        *,
        symbol: str,
        start_time: datetime,
        end_time: datetime | None = None,
    ) -> tuple[Order, ...]:
        """Reject unexpected protection-history fallback in this exact path."""
        del symbol, start_time, end_time
        raise AssertionError("operator ownership must bypass natural-exit inference")

    async def get_protection_order_by_client_id(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> Order:
        """Return one exact current or terminal protection identity."""
        order = self.protections[client_id]
        assert order.symbol.upper() == symbol.upper()
        return order

    async def get_trades(
        self,
        *,
        symbol: str | None,
        limit: int,
    ) -> tuple[Trade, ...]:
        """Reject natural manual-close inference for an operator-owned exit."""
        del symbol, limit
        raise AssertionError("operator ownership must bypass manual-close inference")

    async def get_order(self, *, symbol: str, order_id: str) -> Order:
        """Reject natural standard-order lookup for an operator-owned exit."""
        del symbol, order_id
        raise AssertionError("operator ownership must bypass natural order lookup")

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> None:
        """Cancel one exact owned protection leg after flat exposure is proven."""
        order = self.protections[client_id]
        assert order.symbol.upper() == symbol.upper()
        self.cancel_calls.append(client_id)
        self.protections[client_id] = replace(order, status=OrderStatus.CANCELED)

    async def get_trades_for_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> tuple[Trade, ...]:
        """Return exact entry or operator-exit fills for ledger enrichment."""
        assert symbol.upper() == self.position.symbol.upper()
        if order_id == _ENTRY_ORDER_ID:
            return (
                _trade(
                    trade_id="entry-fill",
                    order_id=order_id,
                    side=OrderSide.BUY,
                    realized_pnl=None,
                ),
            )
        close_order = self.close_order
        if close_order is not None and order_id == close_order.order_id:
            return (
                _trade(
                    trade_id="exit-fill",
                    order_id=order_id,
                    side=OrderSide.SELL,
                    realized_pnl=Decimal("1"),
                ),
            )
        return ()


@dataclass(slots=True)
class _CanonicalReconciler:
    """Reuse the natural/runtime cleanup boundary after operator staging."""

    natural_exit_service: LiveNaturalExitRecoveryService
    runtime_control: TradingRuntimeControl
    calls: int = 0

    async def reconcile_context(self) -> object | None:
        """Reconcile lifecycle and restore READY after flat cleanup succeeds."""
        self.calls += 1
        await self.natural_exit_service.reconcile()
        self.runtime_control.set_position_protection_ready(True)
        return object()


@dataclass(slots=True)
class _StreamOwner:
    """Provide the unused stream-cleanup boundary for a close-only operation."""

    stop_calls: int = 0

    async def stop_all(self) -> None:
        """Record an unexpected stream stop without affecting the test state."""
        self.stop_calls += 1


def _position() -> Position:
    """Build one fully managed LIVE Futures position."""
    return Position(
        symbol=_SYMBOL,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        stop_loss=Decimal("90"),
        take_profit=Decimal("110"),
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        stop_loss_client_algo_id=_STOP_CLIENT_ID,
        take_profit_client_algo_id=_TAKE_PROFIT_CLIENT_ID,
        entry_client_order_id=_ENTRY_CLIENT_ID,
    )


def _protection(
    *,
    order_type: OrderType,
    client_order_id: str,
    stop_price: Decimal,
) -> Order:
    """Build one active exact Botragram-owned protection leg."""
    return Order(
        order_id=client_order_id,
        symbol=_SYMBOL,
        side=OrderSide.SELL,
        order_type=order_type,
        status=OrderStatus.NEW,
        quantity=Decimal("1"),
        executed_quantity=Decimal("0"),
        stop_price=stop_price,
        client_order_id=client_order_id,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _trade(
    *,
    trade_id: str,
    order_id: str,
    side: OrderSide,
    realized_pnl: Decimal | None,
) -> Trade:
    """Build one exact authoritative fill for lifecycle enrichment."""
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        symbol=_SYMBOL,
        side=side,
        price=Decimal("100"),
        quantity=Decimal("1"),
        quote_quantity=Decimal("100"),
        fee=Decimal("0.1"),
        fee_asset="USDT",
        executed_at=_NOW,
        realized_pnl=realized_pnl,
    )


@pytest.mark.asyncio
async def test_operator_exit_ledger_ownership_survives_canonical_cleanup_once() -> None:
    """Persist one operator close exactly once through natural/runtime cleanup."""
    position = _position()
    positions = MemoryPositionRepository()
    await positions.save(position=position)
    submissions = MemorySubmissionAttemptRepository()
    await submissions.save(
        attempt=SubmissionAttempt(
            client_order_id=_ENTRY_CLIENT_ID,
            symbol=_SYMBOL,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=position.quantity,
            signal_generated_at=_NOW,
            interval=Interval.M15,
            strategy_type=StrategyType.EMA_CROSS,
            status=SubmissionAttemptStatus.COMPLETED,
            exchange_order_id=_ENTRY_ORDER_ID,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    operator_repository = MemoryOperatorExitRepository()
    lifecycle_repository = _CountingLifecycleRepository()
    exchange = _OperatorExchange(
        position=position,
        protections={
            _STOP_CLIENT_ID: _protection(
                order_type=OrderType.STOP_MARKET,
                client_order_id=_STOP_CLIENT_ID,
                stop_price=Decimal("90"),
            ),
            _TAKE_PROFIT_CLIENT_ID: _protection(
                order_type=OrderType.TAKE_PROFIT_MARKET,
                client_order_id=_TAKE_PROFIT_CLIENT_ID,
                stop_price=Decimal("110"),
            ),
        },
    )
    lifecycle_service = ClosedPositionLifecycleService(
        repository=lifecycle_repository,
        trade_history=exchange,
    )
    coordinator = LivePositionLifecycleCoordinator()
    runtime_control = TradingRuntimeControl(market_type=MarketType.FUTURES)
    runtime_control.set_runtime_contexts(
        contexts=(
            LiveRuntimePositionContext(
                symbol=_SYMBOL,
                interval=Interval.M15,
                strategy_type=StrategyType.EMA_CROSS,
            ),
        )
    )
    natural_exit_service = LiveNaturalExitRecoveryService(
        exchange_client=exchange,
        position_repository=positions,
        submission_attempt_repository=submissions,
        operator_exit_repository=operator_repository,
        closed_lifecycle_service=lifecycle_service,
        lifecycle_coordinator=coordinator,
    )
    reconciler = _CanonicalReconciler(
        natural_exit_service=natural_exit_service,
        runtime_control=runtime_control,
    )
    stream_owner = _StreamOwner()
    service = OperatorExitService(
        trade_mode=TradeMode.LIVE,
        market_type=MarketType.FUTURES,
        exchange_environment=ExchangeEnvironment.TESTNET,
        runtime_control=runtime_control,
        operator_exit_repository=operator_repository,
        position_repository=positions,
        market_stream_owner=stream_owner,
        live_position_service=exchange,
        live_exchange=exchange,
        submission_attempt_repository=submissions,
        closed_lifecycle_service=lifecycle_service,
        live_runtime_reconciler=reconciler,
        lifecycle_coordinator=coordinator,
    )

    confirmation = await service.request_close_all(requested_by="telegram:7")
    snapshot = await service.confirm(
        confirmation_id=confirmation.confirmation_id,
        requested_by="telegram:7",
        token="CONFIRM",
    )
    await natural_exit_service.reconcile()
    completed = tuple(await lifecycle_repository.get_completed())

    assert snapshot.status is OperatorExitStatus.COMPLETE
    assert exchange.close_calls == 1
    assert exchange.recovery_get_calls == 1
    assert set(exchange.cancel_calls) == {_STOP_CLIENT_ID, _TAKE_PROFIT_CLIENT_ID}
    assert lifecycle_repository.stage_calls == 1
    assert len(completed) == 1
    assert completed[0].ownership.close_reason is ClosedPositionReason.OPERATOR_EXIT
    assert (
        completed[0].ownership.provenance
        is ClosedPositionProvenance.OPERATOR_EXIT_ORDER
    )
    assert await positions.get_by_symbol(symbol=_SYMBOL) is None
    assert not runtime_control.operator_exit_in_progress
    assert runtime_control.is_position_protection_ready
    assert reconciler.calls == 2
    assert stream_owner.stop_calls == 0
