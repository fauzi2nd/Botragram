"""
Botragram

Description:
    PAPER human execution authorization tests.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from botragram.config.risk_settings import RiskSettings
from botragram.engine import PnLEngine, RiskEngine, TradingEngine
from botragram.enums import AuthorizationStatus, SignalType, TradeMode
from botragram.models import (
    ExecutionAuthorization,
    Signal,
    TradingDecision,
    TradingResult,
)
from botragram.services import ExecutionAuthorizationService, PaperTradingService
from botragram.storage.memory import (
    MemoryExecutionAuthorizationRepository,
    MemoryOrderRepository,
    MemoryPositionRepository,
    MemoryTradeRepository,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _signal(*, symbol: str = "BTCUSDT", generated_at: datetime = _NOW) -> Signal:
    """Create one exact actionable discovery candidate."""
    return Signal(
        symbol=symbol,
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.8"),
        strategy_name="test",
        generated_at=generated_at,
    )


@dataclass(slots=True, kw_only=True)
class RecordingPaperService:
    """Represent the authoritative PAPER execution boundary in service tests."""

    blocked_symbols: set[str] = field(default_factory=set[str])
    calls: list[Signal] = field(default_factory=list[Signal])
    started: asyncio.Event = field(default_factory=asyncio.Event)
    block: bool = False

    async def execute(self, *, signal: Signal) -> TradingResult:
        """Apply the current simulated PAPER eligibility at approval time."""
        self.calls.append(signal)
        self.started.set()

        if self.block:
            await asyncio.Event().wait()

        allowed = signal.symbol not in self.blocked_symbols
        decision = TradingDecision(
            should_execute=allowed,
            signal=signal,
            risk_result=None,
            reason="Portfolio changed" if not allowed else "",
        )
        return TradingResult(
            executed=allowed,
            decision=decision,
            order=None,
            reason=decision.reason,
        )


@dataclass(slots=True)
class RecordingAuthorizationPublisher:
    """Capture application-to-adapter prepared authorization delivery."""

    authorizations: list[ExecutionAuthorization] = field(
        default_factory=list[ExecutionAuthorization],
    )

    async def publish_execution_authorization(
        self,
        *,
        authorization: ExecutionAuthorization,
    ) -> None:
        """Record one immutable authorization notification."""
        self.authorizations.append(authorization)


def _service(
    *,
    paper: RecordingPaperService | None = None,
    maximum_authorizations: int = 100,
) -> tuple[ExecutionAuthorizationService, RecordingPaperService]:
    """Create an isolated PAPER authorization boundary."""
    recording_paper = paper if paper is not None else RecordingPaperService()
    return (
        ExecutionAuthorizationService(
            authorization_repository=MemoryExecutionAuthorizationRepository(
                maximum_authorizations=maximum_authorizations,
            ),
            paper_trading_service=recording_paper,
            trade_mode=TradeMode.PAPER,
        ),
        recording_paper,
    )


def _actual_paper_service(*, maximum_positions: int) -> PaperTradingService:
    """Create the real persistence-backed PAPER execution boundary."""
    return PaperTradingService(
        order_repository=MemoryOrderRepository(),
        trade_repository=MemoryTradeRepository(),
        position_repository=MemoryPositionRepository(),
        trading_engine=TradingEngine(
            risk_engine=RiskEngine(
                settings=RiskSettings(max_open_positions=maximum_positions),
            ),
        ),
        pnl_engine=PnLEngine(),
    )


def test_prepare_creates_distinct_opaque_pending_authorizations() -> None:
    """Keep same-symbol opportunities distinct by opaque identity and signal time."""
    asyncio.run(_run_prepare_test())


async def _run_prepare_test() -> None:
    """Prepare two signals for one symbol at different generation times."""
    service, _ = _service()
    first = await service.prepare(signal=_signal(), now=_NOW)
    second = await service.prepare(
        signal=_signal(generated_at=_NOW + timedelta(minutes=1)),
        now=_NOW,
    )

    assert first.status is AuthorizationStatus.PENDING
    assert first.authorization_id != second.authorization_id
    assert len(first.authorization_id) == 32
    assert first.signal != second.signal


def test_authorization_service_rejects_live_execution_configuration() -> None:
    """Keep Phase 4A human authorization structurally PAPER-only."""
    with pytest.raises(ValueError, match="only in paper mode"):
        ExecutionAuthorizationService(
            authorization_repository=MemoryExecutionAuthorizationRepository(),
            paper_trading_service=RecordingPaperService(),
            trade_mode=TradeMode.LIVE,
        )


def test_prepare_publishes_through_the_adapter_protocol() -> None:
    """Deliver prepared opportunities without importing Telegram into the service."""
    asyncio.run(_run_prepare_publish_test())


async def _run_prepare_publish_test() -> None:
    """Prepare one opportunity and publish the immutable authorization result."""
    publisher = RecordingAuthorizationPublisher()
    service = ExecutionAuthorizationService(
        authorization_repository=MemoryExecutionAuthorizationRepository(),
        paper_trading_service=RecordingPaperService(),
        trade_mode=TradeMode.PAPER,
        authorization_publisher=publisher,
    )

    authorization = await service.prepare(signal=_signal(), now=_NOW)

    assert publisher.authorizations == [authorization]


def test_reject_and_duplicate_rejection_are_safe_without_execution() -> None:
    """Consume a rejection once and never invoke PAPER execution."""
    asyncio.run(_run_rejection_test())


async def _run_rejection_test() -> None:
    """Reject one pending authorization twice."""
    service, paper = _service()
    authorization = await service.prepare(signal=_signal(), now=_NOW)
    rejected = await service.reject(
        authorization_id=authorization.authorization_id,
        now=_NOW,
    )
    repeated = await service.reject(
        authorization_id=authorization.authorization_id,
        now=_NOW,
    )

    assert rejected.authorization is not None
    assert rejected.authorization.status is AuthorizationStatus.REJECTED
    assert repeated.trading_result is None
    assert paper.calls == []


def test_approve_consumes_once_and_delegates_to_paper() -> None:
    """Allow exactly one approved invocation through the PAPER boundary."""
    asyncio.run(_run_approval_test())


async def _run_approval_test() -> None:
    """Approve one authorization twice."""
    service, paper = _service()
    authorization = await service.prepare(signal=_signal(), now=_NOW)
    approved = await service.approve(
        authorization_id=authorization.authorization_id,
        now=_NOW,
    )
    repeated = await service.approve(
        authorization_id=authorization.authorization_id,
        now=_NOW,
    )

    assert approved.trading_result is not None
    assert approved.trading_result.executed
    assert repeated.trading_result is None
    assert len(paper.calls) == 1


def test_expired_unknown_and_restart_authorizations_cannot_execute() -> None:
    """Fail closed for stale, missing, and prior-process authorization IDs."""
    asyncio.run(_run_invalid_authorization_test())


async def _run_invalid_authorization_test() -> None:
    """Approve expired, unknown, and new-service records."""
    service, paper = _service()
    authorization = await service.prepare(signal=_signal(), now=_NOW)
    expired = await service.approve(
        authorization_id=authorization.authorization_id,
        now=_NOW + timedelta(minutes=6),
    )
    unknown = await service.approve(authorization_id="unknown", now=_NOW)
    restarted_service, _ = _service()
    restarted = await restarted_service.approve(
        authorization_id=authorization.authorization_id,
        now=_NOW,
    )

    assert expired.authorization is not None
    assert expired.authorization.status is AuthorizationStatus.EXPIRED
    assert expired.trading_result is None
    assert unknown.trading_result is None
    assert restarted.trading_result is None
    assert paper.calls == []


def test_approval_observes_current_paper_portfolio_state() -> None:
    """Delegate final post-preparation state validation to PAPER execution."""
    asyncio.run(_run_current_state_test())


async def _run_current_state_test() -> None:
    """Change the simulated portfolio after preparation before approval."""
    paper = RecordingPaperService(blocked_symbols={"BTCUSDT"})
    service, _ = _service(paper=paper)
    authorization = await service.prepare(signal=_signal(), now=_NOW)
    outcome = await service.approve(
        authorization_id=authorization.authorization_id,
        now=_NOW,
    )

    assert outcome.trading_result is not None
    assert not outcome.trading_result.executed
    assert outcome.trading_result.reason == "Portfolio changed"
    assert paper.calls == [authorization.signal]


def test_approval_revalidates_a_same_symbol_position_opened_after_prepare() -> None:
    """Use real PAPER state to block a signal that became a position update."""
    asyncio.run(_run_same_symbol_revalidation_test())


async def _run_same_symbol_revalidation_test() -> None:
    """Open the candidate's symbol after preparation and then approve it."""
    paper = _actual_paper_service(maximum_positions=2)
    service = ExecutionAuthorizationService(
        authorization_repository=MemoryExecutionAuthorizationRepository(),
        paper_trading_service=paper,
        trade_mode=TradeMode.PAPER,
    )
    signal = _signal()
    authorization = await service.prepare(signal=signal, now=_NOW)
    opened = await paper.execute(signal=signal)
    outcome = await service.approve(
        authorization_id=authorization.authorization_id,
        now=_NOW,
    )

    assert opened.executed
    assert outcome.trading_result is not None
    assert not outcome.trading_result.executed
    assert outcome.trading_result.reason == "Paper position remains open"


def test_approval_revalidates_capacity_reached_after_prepare() -> None:
    """Use real PAPER state to reject approval after another entry consumes capacity."""
    asyncio.run(_run_capacity_revalidation_test())


async def _run_capacity_revalidation_test() -> None:
    """Open another symbol after preparation before authorizing the candidate."""
    paper = _actual_paper_service(maximum_positions=1)
    service = ExecutionAuthorizationService(
        authorization_repository=MemoryExecutionAuthorizationRepository(),
        paper_trading_service=paper,
        trade_mode=TradeMode.PAPER,
    )
    authorization = await service.prepare(signal=_signal(), now=_NOW)
    opened = await paper.execute(
        signal=_signal(
            symbol="ETHUSDT",
            generated_at=_NOW + timedelta(minutes=1),
        )
    )
    outcome = await service.approve(
        authorization_id=authorization.authorization_id,
        now=_NOW,
    )

    assert opened.executed
    assert outcome.trading_result is not None
    assert not outcome.trading_result.executed
    assert outcome.trading_result.reason == "Maximum open positions reached"


def test_cancellation_consumes_authorization_before_paper_execution_finishes() -> None:
    """Prevent a retry when the owning approval task is cancelled."""
    asyncio.run(_run_cancellation_test())


async def _run_cancellation_test() -> None:
    """Cancel an in-flight PAPER authorization approval."""
    paper = RecordingPaperService(block=True)
    service, _ = _service(paper=paper)
    authorization = await service.prepare(signal=_signal(), now=_NOW)
    task = asyncio.create_task(
        service.approve(authorization_id=authorization.authorization_id, now=_NOW)
    )
    await paper.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    repeated = await service.approve(
        authorization_id=authorization.authorization_id,
        now=_NOW,
    )
    assert repeated.trading_result is None
    assert len(paper.calls) == 1


def test_authorization_repository_is_bounded() -> None:
    """Reject additional pending authorizations when no terminal record can prune."""
    asyncio.run(_run_bounded_storage_test())


async def _run_bounded_storage_test() -> None:
    """Fill a one-record authorization repository with a pending item."""
    service, _ = _service(maximum_authorizations=1)
    await service.prepare(signal=_signal(), now=_NOW)

    with pytest.raises(RuntimeError, match="capacity reached"):
        await service.prepare(
            signal=_signal(symbol="ETHUSDT"),
            now=_NOW,
        )
