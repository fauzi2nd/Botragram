"""
Botragram

Description:
    Autonomous PAPER opportunity execution tests.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from botragram.enums import Interval, SignalType
from botragram.models import Signal, TradingDecision, TradingResult
from botragram.services import AutonomousPaperExecutionService

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _signal(symbol: str) -> Signal:
    """Create one ranked actionable candidate."""
    return Signal(
        symbol=symbol,
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.8"),
        strategy_name="test",
        generated_at=_NOW,
    )


def _result(signal: Signal) -> TradingResult:
    """Create one deterministic rejected PAPER result."""
    decision = TradingDecision(
        should_execute=False,
        signal=signal,
        risk_result=None,
        reason="Portfolio capacity reached",
    )
    return TradingResult(
        executed=False,
        decision=decision,
        order=None,
        reason=decision.reason,
    )


@dataclass(slots=True, kw_only=True)
class FakeDiscoveryService:
    """Return a controlled ranked candidate sequence."""

    candidates: tuple[Signal, ...]
    block: bool = False
    calls: int = 0
    discovery_started: asyncio.Event = field(default_factory=asyncio.Event)

    async def discover(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> tuple[Signal, ...]:
        """Record one discovery request."""
        del quote_asset, interval, candle_limit, max_symbols, top_n
        self.calls += 1
        self.discovery_started.set()

        if self.block:
            await asyncio.Event().wait()

        return self.candidates


@dataclass(slots=True, kw_only=True)
class FakePaperTradingService:
    """Record PAPER executions without creating positions or orders."""

    calls: list[str] = field(default_factory=list[str])

    async def execute(
        self,
        *,
        signal: Signal,
        initial_balance: Decimal | None = None,
        interval: Interval | None = None,
    ) -> TradingResult:
        """Record one candidate execution."""
        del initial_balance, interval
        self.calls.append(signal.symbol)
        return _result(signal)


def test_autonomous_service_returns_no_result_when_discovery_is_empty() -> None:
    """Verify an empty candidate set performs no PAPER execution."""
    asyncio.run(_run_empty_cycle_test())


async def _run_empty_cycle_test() -> None:
    """Execute an empty autonomous cycle."""
    discovery = FakeDiscoveryService(candidates=())
    paper = FakePaperTradingService()
    service = AutonomousPaperExecutionService(
        discovery_service=discovery,
        paper_trading_service=paper,
    )

    results = await service.execute(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=100,
        max_symbols=20,
        top_n=5,
    )

    assert results == ()
    assert discovery.calls == 1
    assert paper.calls == []


def test_autonomous_service_executes_ranked_candidates_sequentially() -> None:
    """Verify the service delegates each ranked candidate in order."""
    asyncio.run(_run_ranked_cycle_test())


async def _run_ranked_cycle_test() -> None:
    """Execute a mixed accepted/rejected candidate sequence."""
    candidates = (_signal("ETHUSDT"), _signal("BTCUSDT"))
    paper = FakePaperTradingService()
    service = AutonomousPaperExecutionService(
        discovery_service=FakeDiscoveryService(candidates=candidates),
        paper_trading_service=paper,
    )

    results = await service.execute(
        quote_asset="USDT",
        interval=Interval.M5,
        candle_limit=120,
        max_symbols=20,
        top_n=5,
        initial_balance=Decimal("10000"),
    )

    assert tuple(result.decision.signal for result in results) == candidates
    assert paper.calls == ["ETHUSDT", "BTCUSDT"]


def test_autonomous_service_executes_one_opportunity_once() -> None:
    """Verify one ranked candidate produces exactly one PAPER attempt."""
    asyncio.run(_run_single_candidate_test())


async def _run_single_candidate_test() -> None:
    """Execute one autonomous candidate."""
    candidate = _signal("BTCUSDT")
    paper = FakePaperTradingService()
    service = AutonomousPaperExecutionService(
        discovery_service=FakeDiscoveryService(candidates=(candidate,)),
        paper_trading_service=paper,
    )

    results = await service.execute(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=100,
        max_symbols=20,
        top_n=5,
    )

    assert len(results) == 1
    assert paper.calls == ["BTCUSDT"]


def test_autonomous_service_attempts_the_next_candidate_after_rejection() -> None:
    """Verify a rejected candidate does not prevent the next ranked attempt."""
    asyncio.run(_run_rejection_continuation_test())


async def _run_rejection_continuation_test() -> None:
    """Execute a rejection followed by a separate candidate result."""

    class MixedPaperTradingService(FakePaperTradingService):
        """Return a rejection then an approved PAPER result."""

        async def execute(
            self,
            *,
            signal: Signal,
            initial_balance: Decimal | None = None,
            interval: Interval | None = None,
        ) -> TradingResult:
            """Return deterministic candidate-specific outcomes."""
            del initial_balance, interval
            self.calls.append(signal.symbol)

            if len(self.calls) == 1:
                return _result(signal)

            decision = TradingDecision(
                should_execute=True,
                signal=signal,
                risk_result=None,
            )
            return TradingResult(executed=True, decision=decision, order=None)

    candidates = (_signal("BTCUSDT"), _signal("ETHUSDT"))
    paper = MixedPaperTradingService()
    service = AutonomousPaperExecutionService(
        discovery_service=FakeDiscoveryService(candidates=candidates),
        paper_trading_service=paper,
    )

    results = await service.execute(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=100,
        max_symbols=20,
        top_n=5,
    )

    assert [result.executed for result in results] == [False, True]
    assert paper.calls == ["BTCUSDT", "ETHUSDT"]


def test_autonomous_service_propagates_candidate_execution_failure() -> None:
    """Verify a candidate failure stops the cycle without hidden continuation."""
    asyncio.run(_run_execution_failure_test())


async def _run_execution_failure_test() -> None:
    """Run a cycle whose first PAPER candidate fails."""

    class FailingPaperService(FakePaperTradingService):
        """Fail one PAPER candidate execution."""

        async def execute(
            self,
            *,
            signal: Signal,
            initial_balance: Decimal | None = None,
            interval: Interval | None = None,
        ) -> TradingResult:
            """Raise the controlled candidate failure."""
            del signal, initial_balance, interval
            raise RuntimeError("paper persistence failed")

    service = AutonomousPaperExecutionService(
        discovery_service=FakeDiscoveryService(
            candidates=(_signal("BTCUSDT"), _signal("ETHUSDT")),
        ),
        paper_trading_service=FailingPaperService(),
    )

    with pytest.raises(RuntimeError, match="paper persistence failed"):
        await service.execute(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=100,
            max_symbols=20,
            top_n=5,
        )


def test_autonomous_service_propagates_cancellation_before_execution() -> None:
    """Verify cancellation stops discovery without candidate execution tasks."""
    asyncio.run(_run_cancellation_test())


async def _run_cancellation_test() -> None:
    """Cancel an autonomous cycle while discovery is waiting."""
    discovery = FakeDiscoveryService(candidates=(_signal("BTCUSDT"),), block=True)
    paper = FakePaperTradingService()
    service = AutonomousPaperExecutionService(
        discovery_service=discovery,
        paper_trading_service=paper,
    )
    task = asyncio.create_task(
        service.execute(
            quote_asset="USDT",
            interval=Interval.M15,
            candle_limit=100,
            max_symbols=20,
            top_n=5,
        )
    )
    await discovery.discovery_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert paper.calls == []
