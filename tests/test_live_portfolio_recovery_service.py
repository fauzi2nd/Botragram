"""Deterministic LIVE portfolio recovery service tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.app import TradingRuntimeControl
from botragram.enums import (
    Interval,
    LivePortfolioRecoveryStatus,
    LivePortfolioRecoveryUnsafeReason,
    PositionSide,
    StrategyType,
)
from botragram.models import LivePortfolioRecoveryResult, Position
from botragram.services import LivePortfolioRecoveryService
from botragram.storage.memory import MemoryCandleRepository, MemorySignalRepository

_NOW = datetime(2026, 8, 18, tzinfo=UTC)


@dataclass(slots=True)
class RecordingPositionService:
    """Provide an authoritative portfolio and record persistence order."""

    positions: tuple[Position, ...]
    events: list[str]
    fail_symbol: str | None = None
    cancel_sync: bool = False
    fail_sync: bool = False

    async def sync(self) -> tuple[Position, ...]:
        """Return the configured active exchange portfolio."""
        self.events.append("sync")
        if self.cancel_sync:
            raise asyncio.CancelledError()
        if self.fail_sync:
            raise RuntimeError("configured synchronization failure")
        return self.positions

    async def save(self, *, position: Position) -> None:
        """Record one persistence boundary and optionally fail it."""
        self.events.append(f"{position.symbol}:persist")
        if position.symbol == self.fail_symbol:
            raise RuntimeError("configured persistence failure")


@dataclass(slots=True)
class RecordingProtectionService:
    """Record sequential protection verification calls."""

    events: list[str]
    fail_symbol: str | None = None
    cancel_symbol: str | None = None

    async def ensure(self, *, position: Position) -> Position:
        """Return the verified position or raise the configured outcome."""
        self.events.append(f"{position.symbol}:protect")
        if position.symbol == self.cancel_symbol:
            raise asyncio.CancelledError()
        if position.symbol == self.fail_symbol:
            raise RuntimeError("configured protection failure")
        return position


def _position(
    symbol: str,
    *,
    interval: Interval | None = Interval.M1,
    strategy_type: StrategyType | None = StrategyType.EMA_SCALPING,
) -> Position:
    """Build one complete immutable live position snapshot."""
    return Position(
        symbol=symbol,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("101"),
        unrealized_pnl=Decimal("1"),
        leverage=2,
        opened_at=_NOW,
        updated_at=_NOW,
        interval=interval,
        strategy_type=strategy_type,
        stop_loss=Decimal("98"),
        take_profit=Decimal("104"),
        stop_loss_client_algo_id=f"bsl-{symbol.lower()}",
        take_profit_client_algo_id=f"btp-{symbol.lower()}",
    )


def _service(
    *,
    positions: tuple[Position, ...],
    events: list[str],
    fail_persist: str | None = None,
    fail_protection: str | None = None,
    cancel_sync: bool = False,
    fail_sync: bool = False,
    cancel_protection: str | None = None,
) -> tuple[LivePortfolioRecoveryService, TradingRuntimeControl]:
    """Construct recovery with deterministic protocol-compatible fakes."""
    control = TradingRuntimeControl()
    return (
        LivePortfolioRecoveryService(
            position_service=RecordingPositionService(
                positions=positions,
                events=events,
                fail_symbol=fail_persist,
                cancel_sync=cancel_sync,
                fail_sync=fail_sync,
            ),
            protection_service=RecordingProtectionService(
                events=events,
                fail_symbol=fail_protection,
                cancel_symbol=cancel_protection,
            ),
            runtime_control=control,
            signal_repository=MemorySignalRepository(),
            candle_repository=MemoryCandleRepository(),
        ),
        control,
    )


@pytest.mark.asyncio
async def test_no_positions_is_a_clean_portfolio_state() -> None:
    """Classify an empty authoritative portfolio without protection work."""
    events: list[str] = []
    service, control = _service(positions=(), events=events)

    result = await service.recover()

    assert result.status is LivePortfolioRecoveryStatus.NO_POSITIONS
    assert result.recovered_positions == ()
    assert events == ["sync"]
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_portfolio_sync_failure_does_not_use_local_fallback() -> None:
    """Classify an unavailable authoritative exchange portfolio as unsafe."""
    events: list[str] = []
    service, control = _service(positions=(), events=events, fail_sync=True)

    result = await service.recover()

    assert result.status is LivePortfolioRecoveryStatus.UNSAFE
    assert result.unsafe_reason is (
        LivePortfolioRecoveryUnsafeReason.PORTFOLIO_SYNC_FAILED
    )
    assert result.unsafe_symbol is None
    assert result.recovered_positions == ()
    assert events == ["sync"]
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_single_position_is_persisted_before_protection() -> None:
    """Return one safe verified position after the required durable ordering."""
    events: list[str] = []
    position = _position("BTCUSDT")
    service, control = _service(positions=(position,), events=events)

    result = await service.recover()

    assert result.status is LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE
    assert result.recovered_positions == (position,)
    assert events == ["sync", "BTCUSDT:persist", "BTCUSDT:protect"]
    assert "position protection" not in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_multiple_positions_are_recovered_in_symbol_order_and_stay_gated() -> (
    None
):
    """Protect every portfolio position without enabling the singular runtime."""
    events: list[str] = []
    service, control = _service(
        positions=(_position("ETHUSDT"), _position("BTCUSDT"), _position("SOLUSDT")),
        events=events,
    )

    result = await service.recover()

    assert result.status is LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE
    assert [position.symbol for position in result.recovered_positions] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    ]
    assert events == [
        "sync",
        "BTCUSDT:persist",
        "BTCUSDT:protect",
        "ETHUSDT:persist",
        "ETHUSDT:protect",
        "SOLUSDT:persist",
        "SOLUSDT:protect",
    ]
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_unknown_metadata_fails_before_persistence_or_protection() -> None:
    """Never infer strategy or interval for an unmanaged exchange position."""
    events: list[str] = []
    service, control = _service(
        positions=(_position("BTCUSDT", interval=None, strategy_type=None),),
        events=events,
    )

    result = await service.recover()

    assert result.status is LivePortfolioRecoveryStatus.UNSAFE
    assert result.unsafe_reason is (
        LivePortfolioRecoveryUnsafeReason.UNKNOWN_POSITION_METADATA
    )
    assert result.unsafe_symbol == "BTCUSDT"
    assert result.recovered_positions == ()
    assert events == ["sync"]
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_persistence_failure_is_fail_fast_without_protection() -> None:
    """Stop later recovery when a merged position cannot be made durable."""
    events: list[str] = []
    service, control = _service(
        positions=(_position("BTCUSDT"), _position("ETHUSDT")),
        events=events,
        fail_persist="ETHUSDT",
    )

    result = await service.recover()

    assert result.status is LivePortfolioRecoveryStatus.UNSAFE
    assert result.unsafe_reason is (
        LivePortfolioRecoveryUnsafeReason.POSITION_PERSISTENCE_FAILED
    )
    assert result.unsafe_symbol == "ETHUSDT"
    assert [position.symbol for position in result.recovered_positions] == ["BTCUSDT"]
    assert events == ["sync", "BTCUSDT:persist", "BTCUSDT:protect", "ETHUSDT:persist"]
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_protection_failure_is_fail_fast_after_earlier_safe_position() -> None:
    """Keep prior verified protection while refusing later portfolio recovery."""
    events: list[str] = []
    service, control = _service(
        positions=(_position("BTCUSDT"), _position("ETHUSDT"), _position("SOLUSDT")),
        events=events,
        fail_protection="ETHUSDT",
    )

    result = await service.recover()

    assert result.status is LivePortfolioRecoveryStatus.UNSAFE
    assert result.unsafe_reason is LivePortfolioRecoveryUnsafeReason.PROTECTION_FAILED
    assert result.unsafe_symbol == "ETHUSDT"
    assert [position.symbol for position in result.recovered_positions] == ["BTCUSDT"]
    assert events == [
        "sync",
        "BTCUSDT:persist",
        "BTCUSDT:protect",
        "ETHUSDT:persist",
        "ETHUSDT:protect",
    ]
    assert "position protection" in control.get_missing_startup_requirements()


@pytest.mark.asyncio
async def test_cancellation_propagates_and_keeps_gate_closed() -> None:
    """Do not convert sync or protection cancellation into an unsafe result."""
    events: list[str] = []
    sync_service, sync_control = _service(
        positions=(),
        events=events,
        cancel_sync=True,
    )

    with pytest.raises(asyncio.CancelledError):
        await sync_service.recover()

    assert events == ["sync"]
    assert "position protection" in sync_control.get_missing_startup_requirements()

    protection_service, protection_control = _service(
        positions=(_position("BTCUSDT"), _position("ETHUSDT")),
        events=events,
        cancel_protection="BTCUSDT",
    )
    with pytest.raises(asyncio.CancelledError):
        await protection_service.recover()

    assert events[-3:] == ["sync", "BTCUSDT:persist", "BTCUSDT:protect"]
    assert (
        "position protection" in protection_control.get_missing_startup_requirements()
    )


def test_result_rejects_inconsistent_safe_status() -> None:
    """Keep result status invariants strict and immutable."""
    with pytest.raises(ValueError, match="Multiple-position"):
        replace(
            LivePortfolioRecoveryResult(
                status=LivePortfolioRecoveryStatus.SINGLE_POSITION_SAFE,
                recovered_positions=(_position("BTCUSDT"),),
            ),
            status=LivePortfolioRecoveryStatus.MULTIPLE_POSITIONS_SAFE,
        )
