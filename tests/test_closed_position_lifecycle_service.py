"""Closed Botragram position lifecycle aggregation regressions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    Interval,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    StrategyType,
    SubmissionAttemptStatus,
)
from botragram.models import (
    ClosedPositionLifecycle,
    Order,
    Position,
    SubmissionAttempt,
    Trade,
)
from botragram.services import (
    ClosedPositionLifecycleService,
    LiveTradingPerformanceService,
)
from botragram.storage.memory import MemoryClosedPositionLifecycleRepository

_NOW = datetime(2026, 8, 26, tzinfo=UTC)
_ENTRY_CLIENT_ID = "btg-11111111111111111111111111111111"
_EXIT_CLIENT_ID = "btp-22222222222222222222222222222222"


@dataclass(slots=True, kw_only=True)
class ExactTradeHistory:
    """Return all configured fills for one exact exchange order."""

    fills_by_order_id: dict[str, tuple[Trade, ...]]

    async def get_trades_for_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> tuple[Trade, ...]:
        """Return only the requested symbol/order identity."""
        return tuple(
            fill
            for fill in self.fills_by_order_id.get(order_id, ())
            if fill.symbol == symbol
        )


def _position() -> Position:
    """Build one durable Botragram-owned position."""
    return Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("105"),
        unrealized_pnl=Decimal("5"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        stop_loss=Decimal("98"),
        take_profit=Decimal("105"),
        stop_loss_client_algo_id="bsl-33333333333333333333333333333333",
        take_profit_client_algo_id=_EXIT_CLIENT_ID,
        entry_client_order_id=_ENTRY_CLIENT_ID,
    )


def _attempt() -> SubmissionAttempt:
    """Build exact durable entry ownership."""
    return SubmissionAttempt(
        client_order_id=_ENTRY_CLIENT_ID,
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        signal_generated_at=_NOW,
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        status=SubmissionAttemptStatus.COMPLETED,
        created_at=_NOW,
        updated_at=_NOW,
        exchange_order_id="entry-1",
    )


def _exit_order() -> Order:
    """Build an authoritative filled TP exit."""
    return Order(
        order_id="algo-1",
        client_order_id=_EXIT_CLIENT_ID,
        execution_order_id="exit-1",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.TAKE_PROFIT_MARKET,
        status=OrderStatus.FILLED,
        quantity=Decimal("1"),
        executed_quantity=Decimal("1"),
        price=None,
        stop_price=Decimal("105"),
        created_at=_NOW + timedelta(minutes=1),
        updated_at=_NOW + timedelta(minutes=2),
    )


def _fill(
    *,
    trade_id: str,
    order_id: str,
    side: OrderSide,
    fee: str,
    realized_pnl: str | None,
    seconds: int,
) -> Trade:
    """Build one exact exchange fill."""
    return Trade(
        trade_id=trade_id,
        order_id=order_id,
        symbol="BTCUSDT",
        side=side,
        price=Decimal("100"),
        quantity=Decimal("0.5"),
        quote_quantity=Decimal("50"),
        fee=Decimal(fee),
        fee_asset="USDT",
        realized_pnl=(Decimal(realized_pnl) if realized_pnl is not None else None),
        executed_at=_NOW + timedelta(seconds=seconds),
    )


@pytest.mark.asyncio
async def test_multi_fill_lifecycle_completes_once_and_is_restart_idempotent() -> None:
    """Aggregate every exact fill into one immutable entry lifecycle."""
    repository = MemoryClosedPositionLifecycleRepository()
    history = ExactTradeHistory(
        fills_by_order_id={
            "entry-1": (
                _fill(
                    trade_id="entry-a",
                    order_id="entry-1",
                    side=OrderSide.BUY,
                    fee="0.2",
                    realized_pnl="0",
                    seconds=1,
                ),
                _fill(
                    trade_id="entry-b",
                    order_id="entry-1",
                    side=OrderSide.BUY,
                    fee="0.3",
                    realized_pnl="0",
                    seconds=2,
                ),
            ),
            "exit-1": (
                _fill(
                    trade_id="exit-a",
                    order_id="exit-1",
                    side=OrderSide.SELL,
                    fee="0.4",
                    realized_pnl="2",
                    seconds=3,
                ),
                _fill(
                    trade_id="exit-b",
                    order_id="exit-1",
                    side=OrderSide.SELL,
                    fee="0.1",
                    realized_pnl="3",
                    seconds=4,
                ),
            ),
        }
    )
    first = ClosedPositionLifecycleService(
        repository=repository,
        trade_history=history,
    )

    for _ in range(2):
        await first.stage(
            position=_position(),
            attempt=_attempt(),
            exit_order=_exit_order(),
            close_reason=ClosedPositionReason.TAKE_PROFIT,
            provenance=ClosedPositionProvenance.PROTECTION_ORDER,
        )
        await first.complete(entry_client_order_id=_ENTRY_CLIENT_ID)

    restarted = ClosedPositionLifecycleService(
        repository=repository,
        trade_history=history,
    )
    await restarted.reconcile_pending_best_effort()
    completed = await repository.get_completed()

    assert len(completed) == 1
    assert completed[0].entry_client_order_id == _ENTRY_CLIENT_ID
    assert completed[0].gross_realized_pnl == Decimal("5")
    assert completed[0].fee == Decimal("1.0")
    assert completed[0].net_pnl == Decimal("4.0")
    assert completed[0].closed_at == _NOW + timedelta(seconds=4)


@pytest.mark.asyncio
async def test_entry_and_exit_fee_can_change_gross_win_into_net_loss() -> None:
    """Classify W/L/BE from net PnL after all lifecycle fees."""
    repository = MemoryClosedPositionLifecycleRepository()
    history = ExactTradeHistory(
        fills_by_order_id={
            "entry-1": (
                _fill(
                    trade_id="entry",
                    order_id="entry-1",
                    side=OrderSide.BUY,
                    fee="0.6",
                    realized_pnl="0",
                    seconds=1,
                ),
            ),
            "exit-1": (
                _fill(
                    trade_id="exit",
                    order_id="exit-1",
                    side=OrderSide.SELL,
                    fee="0.5",
                    realized_pnl="1",
                    seconds=2,
                ),
            ),
        }
    )
    lifecycle_service = ClosedPositionLifecycleService(
        repository=repository,
        trade_history=history,
    )
    await lifecycle_service.stage(
        position=_position(),
        attempt=_attempt(),
        exit_order=_exit_order(),
        close_reason=ClosedPositionReason.TAKE_PROFIT,
        provenance=ClosedPositionProvenance.PROTECTION_ORDER,
    )
    await lifecycle_service.complete(entry_client_order_id=_ENTRY_CLIENT_ID)

    record = await repository.get_by_entry_client_order_id(
        entry_client_order_id=_ENTRY_CLIENT_ID
    )
    assert isinstance(record, ClosedPositionLifecycle)
    assert record.gross_realized_pnl == Decimal("1")
    assert record.fee == Decimal("1.1")
    assert record.net_pnl == Decimal("-0.1")

    snapshot = await LiveTradingPerformanceService(
        lifecycle_repository=repository
    ).get_snapshot()
    assert snapshot.win_count == 0
    assert snapshot.loss_count == 1
    assert snapshot.break_even_count == 0
