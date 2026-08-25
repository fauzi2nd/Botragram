"""LIVE Botragram lifecycle-ledger performance aggregation tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    PositionSide,
)
from botragram.models import (
    ClosedPositionLifecycle,
    PendingClosedPositionLifecycle,
)
from botragram.services import LiveTradingPerformanceService
from botragram.storage.memory import MemoryClosedPositionLifecycleRepository

_NOW = datetime(2026, 8, 25, tzinfo=UTC)


@dataclass(slots=True)
class MutableClock:
    """Provide deterministic monotonic time for refresh-cache testing."""

    value: float = 0.0

    def __call__(self) -> float:
        """Return the current deterministic monotonic value."""
        return self.value


def _lifecycle(
    *,
    identity: str,
    gross: str,
    fee: str,
    seconds: int,
) -> ClosedPositionLifecycle:
    """Build one authoritative completed lifecycle."""
    gross_value = Decimal(gross)
    fee_value = Decimal(fee)
    return ClosedPositionLifecycle(
        ownership=PendingClosedPositionLifecycle(
            entry_client_order_id=identity,
            symbol="BTCUSDT",
            position_side=PositionSide.LONG,
            entry_order_id=f"entry-{identity}",
            exit_client_order_id=f"exit-client-{identity}",
            exit_order_id=f"exit-{identity}",
            close_reason=ClosedPositionReason.TAKE_PROFIT,
            provenance=ClosedPositionProvenance.PROTECTION_ORDER,
            recorded_at=_NOW + timedelta(seconds=seconds),
        ),
        gross_realized_pnl=gross_value,
        fee=fee_value,
        fee_asset="USDT",
        net_pnl=gross_value - fee_value,
        closed_at=_NOW + timedelta(seconds=seconds),
    )


async def _save(
    *,
    repository: MemoryClosedPositionLifecycleRepository,
    lifecycle: ClosedPositionLifecycle,
) -> None:
    """Stage and complete one lifecycle through repository contracts."""
    await repository.stage(lifecycle=lifecycle.ownership)
    await repository.complete(lifecycle=lifecycle)


@pytest.mark.asyncio
async def test_live_performance_counts_one_net_outcome_per_lifecycle() -> None:
    """Count W/L/BE from net PnL, never from exit order or fill count."""
    repository = MemoryClosedPositionLifecycleRepository()
    for lifecycle in (
        _lifecycle(identity="win", gross="5", fee="2", seconds=1),
        _lifecycle(identity="loss", gross="1", fee="2", seconds=2),
        _lifecycle(identity="flat", gross="1", fee="1", seconds=3),
    ):
        await _save(repository=repository, lifecycle=lifecycle)
    service = LiveTradingPerformanceService(lifecycle_repository=repository)

    snapshot = await service.get_snapshot()

    assert snapshot.closed_trade_count == 3
    assert snapshot.win_count == 1
    assert snapshot.loss_count == 1
    assert snapshot.break_even_count == 1
    assert snapshot.realized_pnl == Decimal("2")
    assert snapshot.win_rate_percent == Decimal("50")


@pytest.mark.asyncio
async def test_live_performance_caches_lifecycle_ledger_within_refresh_window() -> None:
    """Avoid repeated dashboard aggregation before the local cache expires."""
    clock = MutableClock()
    repository = MemoryClosedPositionLifecycleRepository()
    await _save(
        repository=repository,
        lifecycle=_lifecycle(identity="win", gross="2", fee="1", seconds=1),
    )
    service = LiveTradingPerformanceService(
        lifecycle_repository=repository,
        refresh_seconds=10.0,
        monotonic_clock=clock,
    )

    first = await service.get_snapshot()
    await _save(
        repository=repository,
        lifecycle=_lifecycle(identity="loss", gross="0", fee="1", seconds=2),
    )
    clock.value = 9.9
    second = await service.get_snapshot()
    clock.value = 10.0
    third = await service.get_snapshot()

    assert first is second
    assert third.closed_trade_count == 2
    assert third.realized_pnl == Decimal("0")


def test_live_performance_rejects_invalid_refresh_configuration() -> None:
    """Reject a non-positive local-ledger refresh interval."""
    with pytest.raises(ValueError, match="refresh interval"):
        LiveTradingPerformanceService(
            lifecycle_repository=MemoryClosedPositionLifecycleRepository(),
            refresh_seconds=0.0,
        )
