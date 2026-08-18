"""LIVE acknowledged-entry post-recovery tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
from botragram.models import Position, SubmissionAttempt
from botragram.services import (
    LivePostEntryRecoveryResult,
    LivePostEntryRecoveryService,
)
from botragram.storage.memory import MemorySubmissionAttemptRepository

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

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        """Return the next configured position visibility result."""
        self.calls.append((symbol, synchronize))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    async def save(self, *, position: Position) -> None:
        """Capture persisted runtime metadata."""
        self.saved.append(position)


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


async def _service(
    *,
    responses: list[Position | BaseException | None],
    protection: FakeProtectionService | None = None,
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
            position_service=positions,
            protection_service=resolved_protection,
            runtime_control=control,
        ),
        repository,
        positions,
        resolved_protection,
        control,
    )


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
    assert positions.calls == [("BTCUSDT", True), ("BTCUSDT", True)]
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
    assert positions.calls == [("BTCUSDT", True), ("BTCUSDT", True)]
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
