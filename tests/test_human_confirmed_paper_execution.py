"""
Botragram

Description:
    Human-confirmed PAPER opportunity orchestration tests.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.enums import AuthorizationStatus, Interval, SignalType, TradeMode
from botragram.models import (
    ExecutionAuthorization,
    ExecutionAuthorizationOutcome,
    Signal,
    TradingDecision,
    TradingResult,
)
from botragram.services import (
    ExecutionAuthorizationService,
    HumanConfirmedPaperExecutionService,
)
from botragram.storage.memory import MemoryExecutionAuthorizationRepository

_NOW = datetime(2099, 1, 1, tzinfo=UTC)


def _signal(
    symbol: str,
    *,
    signal_type: SignalType = SignalType.BUY,
) -> Signal:
    """Create one actionable discovery candidate."""
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        price=Decimal("100"),
        confidence=Decimal("0.8"),
        strategy_name="test",
        generated_at=_NOW,
    )


@dataclass(slots=True, kw_only=True)
class FakeDiscoveryService:
    """Return a fixed ranked discovery sequence."""

    candidates: tuple[Signal, ...]
    block: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def discover(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> Sequence[Signal]:
        """Return the configured ranked candidates."""
        del quote_asset, interval, candle_limit, max_symbols, top_n
        self.started.set()

        if self.block:
            await asyncio.Event().wait()

        return self.candidates


@dataclass(slots=True)
class RecordingPublisher:
    """Capture prepared authorizations at the adapter boundary."""

    authorizations: list[ExecutionAuthorization] = field(
        default_factory=list[ExecutionAuthorization],
    )

    async def publish_execution_authorization(
        self,
        *,
        authorization: ExecutionAuthorization,
    ) -> None:
        """Record a published pending authorization."""
        self.authorizations.append(authorization)


@dataclass(slots=True)
class RecordingPaperExecutor:
    """Record final authorization execution requests."""

    calls: list[Signal] = field(default_factory=list[Signal])

    async def execute(self, *, signal: Signal) -> TradingResult:
        """Record exactly one final PAPER execution request."""
        self.calls.append(signal)
        return TradingResult(
            executed=True,
            decision=TradingDecision(
                should_execute=True,
                signal=signal,
                risk_result=None,
            ),
            order=None,
        )


def _service(
    *,
    candidates: tuple[Signal, ...],
    maximum_authorizations: int = 100,
) -> tuple[
    HumanConfirmedPaperExecutionService,
    ExecutionAuthorizationService,
    RecordingPublisher,
    RecordingPaperExecutor,
]:
    """Create a fully isolated confirmation workflow."""
    publisher = RecordingPublisher()
    paper = RecordingPaperExecutor()
    authorization_service = ExecutionAuthorizationService(
        authorization_repository=MemoryExecutionAuthorizationRepository(
            maximum_authorizations=maximum_authorizations,
        ),
        paper_trading_service=paper,
        trade_mode=TradeMode.PAPER,
        authorization_publisher=publisher,
    )
    return (
        HumanConfirmedPaperExecutionService(
            discovery_service=FakeDiscoveryService(candidates=candidates),
            authorization_service=authorization_service,
        ),
        authorization_service,
        publisher,
        paper,
    )


async def _run_cycle(
    service: HumanConfirmedPaperExecutionService,
) -> Sequence[ExecutionAuthorization]:
    """Run one standard bounded confirmation discovery cycle."""
    return await service.execute(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=100,
        max_symbols=20,
        top_n=5,
    )


def test_confirmation_cycle_prepares_and_publishes_without_execution() -> None:
    """Prepare ranked candidates without invoking PAPER until approval."""
    asyncio.run(_run_confirmation_cycle_test())


async def _run_confirmation_cycle_test() -> None:
    """Verify a cycle preserves ranking and waits for approval."""
    candidates = (
        _signal("ETHUSDT"),
        _signal("BTCUSDT", signal_type=SignalType.SELL),
    )
    service, authorization_service, publisher, paper = _service(candidates=candidates)

    authorizations = await _run_cycle(service)

    assert tuple(item.signal for item in authorizations) == candidates
    assert publisher.authorizations == list(authorizations)
    assert paper.calls == []

    outcome = await authorization_service.approve(
        authorization_id=authorizations[0].authorization_id,
    )

    assert outcome.trading_result is not None
    assert outcome.trading_result.executed
    assert paper.calls == [candidates[0]]


def test_confirmation_cycle_handles_empty_and_rejected_opportunities() -> None:
    """Avoid authorizations for no opportunities and execution for rejection."""
    asyncio.run(_run_empty_and_rejected_test())


async def _run_empty_and_rejected_test() -> None:
    """Run an empty cycle and reject one separately prepared authorization."""
    empty, _, empty_publisher, empty_paper = _service(candidates=())

    assert await _run_cycle(empty) == ()
    assert empty_publisher.authorizations == []
    assert empty_paper.calls == []

    service, authorization_service, _, paper = _service(
        candidates=(_signal("BTCUSDT"),),
    )
    authorizations = await _run_cycle(service)
    outcome = await authorization_service.reject(
        authorization_id=authorizations[0].authorization_id,
    )

    assert outcome.trading_result is None
    assert paper.calls == []


def test_confirmation_cycle_suppresses_equivalent_pending_candidates() -> None:
    """Do not publish equivalent still-pending candidates on repeated cycles."""
    asyncio.run(_run_duplicate_cycle_test())


async def _run_duplicate_cycle_test() -> None:
    """Run the same ranked opportunity cycle twice."""
    service, _, publisher, paper = _service(candidates=(_signal("BTCUSDT"),))

    first = await _run_cycle(service)
    second = await _run_cycle(service)

    assert len(first) == 1
    assert second == ()
    assert publisher.authorizations == list(first)
    assert paper.calls == []


def test_confirmation_cycle_respects_bounded_pending_capacity() -> None:
    """Fail explicitly rather than creating unbounded pending authorizations."""
    asyncio.run(_run_capacity_test())


async def _run_capacity_test() -> None:
    """Attempt to prepare two non-equivalent candidates in a one-item store."""
    service, _, publisher, paper = _service(
        candidates=(_signal("BTCUSDT"), _signal("ETHUSDT")),
        maximum_authorizations=1,
    )

    with pytest.raises(RuntimeError, match="capacity reached"):
        await _run_cycle(service)

    assert len(publisher.authorizations) == 1
    assert paper.calls == []


def test_confirmation_cycle_propagates_cancellation_without_execution() -> None:
    """Keep confirmation discovery cancellation owned by the runtime cycle."""
    asyncio.run(_run_cancellation_test())


async def _run_cancellation_test() -> None:
    """Cancel a waiting discovery operation."""
    discovery = FakeDiscoveryService(candidates=(_signal("BTCUSDT"),), block=True)
    publisher = RecordingPublisher()
    paper = RecordingPaperExecutor()
    authorization_service = ExecutionAuthorizationService(
        authorization_repository=MemoryExecutionAuthorizationRepository(),
        paper_trading_service=paper,
        trade_mode=TradeMode.PAPER,
        authorization_publisher=publisher,
    )
    service = HumanConfirmedPaperExecutionService(
        discovery_service=discovery,
        authorization_service=authorization_service,
    )
    task = asyncio.create_task(_run_cycle(service))
    await discovery.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert publisher.authorizations == []
    assert paper.calls == []


@pytest.mark.parametrize(
    ("first_action", "second_action"),
    (("approve", "approve"), ("approve", "reject"), ("reject", "approve")),
)
def test_concurrent_authorization_consumption_has_one_terminal_transition(
    first_action: str,
    second_action: str,
) -> None:
    """Atomically consume concurrent approval and rejection callbacks."""
    asyncio.run(_run_concurrent_consumption_test(first_action, second_action))


async def _run_concurrent_consumption_test(
    first_action: str,
    second_action: str,
) -> None:
    """Race two terminal authorization requests through the real repository."""
    service, authorization_service, _, paper = _service(
        candidates=(_signal("BTCUSDT"),)
    )
    authorization = (await _run_cycle(service))[0]

    async def consume(action: str) -> ExecutionAuthorizationOutcome:
        """Execute one terminal action without inspecting internal state."""
        if action == "approve":
            return await authorization_service.approve(
                authorization_id=authorization.authorization_id,
            )

        return await authorization_service.reject(
            authorization_id=authorization.authorization_id,
        )

    outcomes = await asyncio.gather(consume(first_action), consume(second_action))

    assert len(outcomes) == 2
    assert len(paper.calls) <= 1
    assert sum(outcome.trading_result is not None for outcome in outcomes) <= 1
    current = await authorization_service.get(
        authorization_id=authorization.authorization_id,
    )
    assert current is not None
    assert current.status in (
        AuthorizationStatus.APPROVED,
        AuthorizationStatus.REJECTED,
    )
