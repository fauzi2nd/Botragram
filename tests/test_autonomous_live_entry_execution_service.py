"""TESTNET autonomous protected-entry execution adapter tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from botragram.app.runtime_control import TradingRuntimeControl
from botragram.config.risk_settings import RiskSettings
from botragram.engine import RiskEngine, TradingEngine
from botragram.enums import (
    AutonomousLiveEntryExecutionStatus,
    ExchangeEnvironment,
    Interval,
    MarketType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    SignalType,
    StrategyType,
    SubmissionAttemptStatus,
)
from botragram.exceptions import ExchangeOrderRejectedError, LiveSubmissionBlockedError
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveEntryIntent,
    Order,
    Position,
    RiskResult,
    Signal,
    SubmissionAttempt,
)
from botragram.repositories import SubmissionAttemptRepository
from botragram.services import (
    AutonomousLiveEntryExecutionService,
    LiveEntryRiskEvaluationService,
    LiveFuturesEntryService,
)

_NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)


def _create_entry_calls() -> list[tuple[str, Decimal, Interval, OrderType]]:
    """Create an explicitly typed protected-entry call collection."""
    return []


def _create_attempts() -> list[SubmissionAttempt]:
    """Create an explicitly typed durable-attempt collection."""
    return []


@dataclass
class _FakeAccountService:
    """Supply deterministic authoritative balances."""

    balances: list[Decimal]
    calls: int = 0

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return the next configured balance."""
        assert asset == "USDT"
        value = self.balances[min(self.calls, len(self.balances) - 1)]
        self.calls += 1
        return value


@dataclass
class _FakePositionService:
    """Supply deterministic authoritative position snapshots."""

    portfolios: list[tuple[Position, ...]]
    calls: int = 0

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Return the next synchronized portfolio."""
        assert synchronize
        value = self.portfolios[min(self.calls, len(self.portfolios) - 1)]
        self.calls += 1
        return value


@dataclass
class _FakeProtectedEntryService:
    """Record protected-entry delegation without an exchange dependency."""

    error: Exception | None = None
    calls: list[tuple[str, Decimal, Interval, OrderType]] = field(
        default_factory=_create_entry_calls
    )

    async def execute(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        interval: Interval,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        """Record the exact fresh risk result delegated to protected entry."""
        assert price is None
        self.calls.append(
            (signal.symbol, risk_result.position.quantity, interval, order_type)
        )
        if self.error is not None:
            raise self.error

        return Order(
            order_id=f"order-{len(self.calls)}",
            symbol=signal.symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            quantity=risk_result.position.quantity,
            executed_quantity=risk_result.position.quantity,
            created_at=_NOW,
            updated_at=_NOW,
        )


@dataclass
class _RecordingAttemptRepository(SubmissionAttemptRepository):
    """Record the durable protected-entry lifecycle without persistence I/O."""

    events: list[str]
    attempts: list[SubmissionAttempt] = field(default_factory=_create_attempts)

    async def save(self, *, attempt: SubmissionAttempt) -> None:
        """Record each durable lifecycle transition."""
        self.events.append(f"attempt:{attempt.status.value}")
        self.attempts.append(attempt)

    async def resolve_no_exposure(
        self,
        *,
        symbol: str,
        attempt: SubmissionAttempt,
    ) -> None:
        """Record the terminal no-exposure transition without changing behavior."""
        del symbol
        self.events.append(f"attempt:{attempt.status.value}")
        self.attempts.append(attempt)

    async def get_by_client_order_id(
        self, *, client_order_id: str
    ) -> SubmissionAttempt | None:
        """Return no prior attempt for this focused successful path."""
        del client_order_id
        return None

    async def get_unresolved(self) -> Sequence[SubmissionAttempt]:
        """Leave the successful entry path unblocked."""
        self.events.append("attempt:check")
        return ()

    async def get_incomplete(self) -> Sequence[SubmissionAttempt]:
        """Satisfy the complete repository contract."""
        return ()


@dataclass
class _RecordingLivePositionService:
    """Supply fresh portfolio and post-entry authoritative position state."""

    events: list[str]
    position: Position

    async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
        """Return the empty authoritative pre-entry portfolio."""
        assert synchronize
        self.events.append("portfolio:sync")
        return ()

    async def get(self, *, symbol: str, synchronize: bool) -> Position | None:
        """Return the authoritative filled position after the entry POST."""
        assert symbol == self.position.symbol
        assert synchronize
        self.events.append("position:sync")
        return self.position

    async def save(self, *, position: Position) -> None:
        """Record durable actual-position persistence."""
        assert position.quantity == self.position.quantity
        self.events.append("position:save")


@dataclass
class _RecordingOrderService:
    """Record exactly one simulated exchange mutation."""

    events: list[str]

    async def normalize_futures_market_quantity(
        self, *, symbol: str, quantity: Decimal
    ) -> Decimal:
        """Return the test's already-valid quantity."""
        del symbol
        return quantity

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
        client_order_id: str | None = None,
    ) -> Order:
        """Return one filled order with the durable client identity."""
        assert price is None
        assert client_order_id is not None
        self.events.append("order:post")
        return Order(
            order_id="order-1",
            symbol=signal.symbol,
            side=OrderSide.BUY,
            order_type=order_type,
            status=OrderStatus.FILLED,
            quantity=risk_result.position.quantity,
            executed_quantity=risk_result.position.quantity,
            created_at=_NOW,
            updated_at=_NOW,
            client_order_id=client_order_id,
        )

    async def get_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """The successful direct path never needs reconciliation."""
        raise AssertionError(f"Unexpected reconciliation: {symbol}:{client_order_id}")


@dataclass
class _RecordingProtectionService:
    """Record required STOP/TP verification after position persistence."""

    events: list[str]

    async def ensure(self, *, position: Position) -> Position:
        """Record verified protection and retain the authoritative position."""
        self.events.append("protection:ensure")
        return position


def _create_signal(*, symbol: str = "BTCUSDT") -> Signal:
    """Create one deterministic LONG candidate signal."""
    return Signal(
        symbol=symbol,
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_CROSS.value,
        generated_at=_NOW,
    )


def _create_intent(*, symbol: str = "BTCUSDT") -> AutonomousLiveEntryIntent:
    """Create a decision-time intent with deliberately larger P0 sizing."""
    signal = _create_signal(symbol=symbol)
    decision_risk = RiskEngine(settings=RiskSettings()).evaluate(
        signal=signal,
        account_balance=Decimal("1000"),
    )
    return AutonomousLiveEntryIntent(
        signal=signal,
        risk_result=decision_risk,
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
    )


def _create_position(*, symbol: str) -> Position:
    """Create one authoritative active position."""
    return Position(
        symbol=symbol,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )


def _create_authorization() -> AutonomousLiveEntryAuthorization:
    """Create the explicit TESTNET new-entry capability."""
    return AutonomousLiveEntryAuthorization(
        environment=ExchangeEnvironment.TESTNET,
        explicit_opt_in=True,
    )


def _create_service(
    *,
    account_service: _FakeAccountService,
    position_service: _FakePositionService,
    protected_entry_service: _FakeProtectedEntryService,
    max_open_positions: int = 2,
) -> AutonomousLiveEntryExecutionService:
    """Create the adapter around canonical fresh-risk dependencies."""
    return AutonomousLiveEntryExecutionService(
        risk_evaluation_service=LiveEntryRiskEvaluationService(
            account_service=account_service,
            position_service=position_service,
            trading_engine=TradingEngine(
                risk_engine=RiskEngine(
                    settings=RiskSettings(max_open_positions=max_open_positions),
                )
            ),
            balance_asset="usdt",
        ),
        live_futures_entry_service=protected_entry_service,
        environment=ExchangeEnvironment.TESTNET,
    )


def test_authorization_is_required_before_authoritative_revalidation() -> None:
    """Intent possession alone must not start reads, PREPARED, or submission."""
    accounts = _FakeAccountService(balances=[Decimal("500")])
    positions = _FakePositionService(portfolios=[()])
    protected_entry = _FakeProtectedEntryService()

    result = asyncio.run(
        _create_service(
            account_service=accounts,
            position_service=positions,
            protected_entry_service=protected_entry,
        ).execute(
            intent=_create_intent(),
            authorization=None,
        )
    )

    assert result.status is AutonomousLiveEntryExecutionStatus.AUTHORIZATION_REJECTED
    assert accounts.calls == 0
    assert positions.calls == 0
    assert protected_entry.calls == []


def test_fresh_balance_replaces_stale_intent_risk_result() -> None:
    """Delegate fresh P1 sizing, never the P0 quantity embedded in the intent."""
    accounts = _FakeAccountService(balances=[Decimal("500")])
    positions = _FakePositionService(portfolios=[()])
    protected_entry = _FakeProtectedEntryService()
    intent = _create_intent()
    result = asyncio.run(
        _create_service(
            account_service=accounts,
            position_service=positions,
            protected_entry_service=protected_entry,
        ).execute(
            intent=intent,
            authorization=_create_authorization(),
        )
    )

    assert result.status is AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
    assert intent.quantity == Decimal("10")
    assert protected_entry.calls == [
        ("BTCUSDT", Decimal("5"), Interval.M15, OrderType.MARKET),
    ]
    assert result.decision is not None
    assert result.decision.risk_result is not None
    assert result.decision.risk_result.position.quantity == Decimal("5")


def test_existing_position_rejects_before_protected_entry() -> None:
    """Reject a stale same-symbol intent before PREPARED or POST can occur."""
    protected_entry = _FakeProtectedEntryService()
    result = asyncio.run(
        _create_service(
            account_service=_FakeAccountService(balances=[Decimal("500")]),
            position_service=_FakePositionService(
                portfolios=[(_create_position(symbol="BTCUSDT"),)]
            ),
            protected_entry_service=protected_entry,
        ).execute(
            intent=_create_intent(),
            authorization=_create_authorization(),
        )
    )

    assert result.status is AutonomousLiveEntryExecutionStatus.EXISTING_POSITION
    assert protected_entry.calls == []


def test_batch_revalidates_capacity_after_each_completed_entry() -> None:
    """Prevent a P0 ETH intent from consuming capacity after BTC fills."""
    protected_entry = _FakeProtectedEntryService()
    service = _create_service(
        account_service=_FakeAccountService(balances=[Decimal("500")]),
        position_service=_FakePositionService(
            portfolios=[(), (_create_position(symbol="BTCUSDT"),)]
        ),
        protected_entry_service=protected_entry,
        max_open_positions=1,
    )
    results = asyncio.run(
        service.execute_many(
            intents=(
                _create_intent(symbol="BTCUSDT"),
                _create_intent(symbol="ETHUSDT"),
            ),
            authorization=_create_authorization(),
        )
    )

    assert tuple(result.status for result in results) == (
        AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED,
        AutonomousLiveEntryExecutionStatus.RISK_REJECTED,
    )
    assert protected_entry.calls == [
        ("BTCUSDT", Decimal("5"), Interval.M15, OrderType.MARKET),
    ]


def test_submission_block_and_unsafe_execution_stop_later_intents() -> None:
    """Stop the batch after global blocking or an uncertain mutation outcome."""
    protected_entry = _FakeProtectedEntryService(
        error=LiveSubmissionBlockedError("incomplete"),
    )
    service = _create_service(
        account_service=_FakeAccountService(balances=[Decimal("500")]),
        position_service=_FakePositionService(portfolios=[()]),
        protected_entry_service=protected_entry,
    )
    results = asyncio.run(
        service.execute_many(
            intents=(_create_intent(), _create_intent(symbol="ETHUSDT")),
            authorization=_create_authorization(),
        )
    )

    assert tuple(result.status for result in results) == (
        AutonomousLiveEntryExecutionStatus.SUBMISSION_BLOCKED,
    )
    assert len(protected_entry.calls) == 1


def test_unsafe_protected_entry_stops_later_intents() -> None:
    """Stop after a protection or reconciliation failure leaves state uncertain."""
    protected_entry = _FakeProtectedEntryService(error=RuntimeError("unsafe"))
    service = _create_service(
        account_service=_FakeAccountService(balances=[Decimal("500")]),
        position_service=_FakePositionService(portfolios=[()]),
        protected_entry_service=protected_entry,
    )

    results = asyncio.run(
        service.execute_many(
            intents=(_create_intent(), _create_intent(symbol="ETHUSDT")),
            authorization=_create_authorization(),
        )
    )

    assert tuple(result.status for result in results) == (
        AutonomousLiveEntryExecutionStatus.EXECUTION_UNSAFE,
    )
    assert len(protected_entry.calls) == 1


def test_known_exchange_rejection_is_typed_without_retry() -> None:
    """Keep a definitive protected-entry rejection distinct from uncertainty."""
    protected_entry = _FakeProtectedEntryService(
        error=ExchangeOrderRejectedError("rejected"),
    )
    result = asyncio.run(
        _create_service(
            account_service=_FakeAccountService(balances=[Decimal("500")]),
            position_service=_FakePositionService(portfolios=[()]),
            protected_entry_service=protected_entry,
        ).execute(
            intent=_create_intent(),
            authorization=_create_authorization(),
        )
    )

    assert result.status is AutonomousLiveEntryExecutionStatus.EXCHANGE_REJECTED
    assert len(protected_entry.calls) == 1


def test_cancellation_during_authoritative_revalidation_propagates() -> None:
    """Do not turn cancellation before the protected boundary into rejection."""
    asyncio.run(_run_cancellation_test())


def test_adapter_delegates_full_prepared_to_protected_completion_order() -> None:
    """Retain the existing durable protected-entry lifecycle without duplication."""
    events: list[str] = []
    actual_position = _create_position(symbol="BTCUSDT")
    attempts = _RecordingAttemptRepository(events=events)
    positions = _RecordingLivePositionService(events=events, position=actual_position)
    live_entry = LiveFuturesEntryService(
        market_type=MarketType.FUTURES,
        order_service=_RecordingOrderService(events=events),
        position_service=positions,
        protection_service=_RecordingProtectionService(events=events),
        runtime_control=TradingRuntimeControl(),
        submission_attempt_repository=attempts,
    )
    service = AutonomousLiveEntryExecutionService(
        risk_evaluation_service=LiveEntryRiskEvaluationService(
            account_service=_FakeAccountService(balances=[Decimal("500")]),
            position_service=positions,
            trading_engine=TradingEngine(
                risk_engine=RiskEngine(settings=RiskSettings())
            ),
            balance_asset="USDT",
        ),
        live_futures_entry_service=live_entry,
        environment=ExchangeEnvironment.TESTNET,
    )

    result = asyncio.run(
        service.execute(
            intent=_create_intent(),
            authorization=_create_authorization(),
        )
    )

    assert result.status is AutonomousLiveEntryExecutionStatus.EXECUTED_AND_PROTECTED
    assert events == [
        "portfolio:sync",
        "attempt:check",
        "attempt:prepared",
        "order:post",
        "attempt:acknowledged",
        "position:sync",
        "position:save",
        "protection:ensure",
        "attempt:completed",
    ]
    assert [attempt.status for attempt in attempts.attempts] == [
        SubmissionAttemptStatus.PREPARED,
        SubmissionAttemptStatus.ACKNOWLEDGED,
        SubmissionAttemptStatus.COMPLETED,
    ]


async def _run_cancellation_test() -> None:
    """Cancel a blocked authoritative portfolio read before entry delegation."""
    started = asyncio.Event()
    release = asyncio.Event()

    @dataclass
    class BlockingPositionService:
        """Block the pre-mutation portfolio synchronization."""

        async def get_all(self, *, synchronize: bool = False) -> Sequence[Position]:
            """Wait until test cancellation interrupts the authoritative read."""
            assert synchronize
            started.set()
            await release.wait()
            return ()

    protected_entry = _FakeProtectedEntryService()
    service = AutonomousLiveEntryExecutionService(
        risk_evaluation_service=LiveEntryRiskEvaluationService(
            account_service=_FakeAccountService(balances=[Decimal("500")]),
            position_service=BlockingPositionService(),
            trading_engine=TradingEngine(
                risk_engine=RiskEngine(settings=RiskSettings())
            ),
            balance_asset="USDT",
        ),
        live_futures_entry_service=protected_entry,
        environment=ExchangeEnvironment.TESTNET,
    )
    task = asyncio.create_task(
        service.execute(
            intent=_create_intent(),
            authorization=_create_authorization(),
        )
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert protected_entry.calls == []
