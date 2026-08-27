"""Deterministic autonomous LIVE candidate-continuation tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.enums import (
    AutonomousLiveEntryExecutionStatus,
    ExchangeEnvironment,
    Interval,
    OrderType,
    SignalType,
    StrategyType,
)
from botragram.exceptions import (
    LiveEntryPreflightError,
    LiveEntryRiskLimitError,
    LiveEntrySymbolReadinessError,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    AutonomousLiveEntryIntent,
    ExecutableQuote,
    LiveEntryRiskEvaluation,
    Order,
    PositionSize,
    RiskMetrics,
    RiskResult,
    Signal,
    TradingDecision,
)
from botragram.services import AutonomousLiveEntryExecutionService

_NOW = datetime(2026, 8, 27, tzinfo=UTC)


def _signal(symbol: str) -> Signal:
    return Signal(
        symbol=symbol,
        signal_type=SignalType.BUY,
        price=Decimal("10"),
        confidence=Decimal("0.9"),
        strategy_name=StrategyType.EMA_CROSS.value,
        generated_at=_NOW,
    )


def _risk_result() -> RiskResult:
    return RiskResult(
        approved=True,
        position=PositionSize(
            quantity=Decimal("1"),
            notional=Decimal("10"),
            leverage=1,
        ),
        metrics=RiskMetrics(
            entry_price=Decimal("10"),
            stop_loss=Decimal("9"),
            take_profit=Decimal("11"),
            risk_amount=Decimal("1"),
            reward_amount=Decimal("1"),
            risk_reward_ratio=Decimal("1"),
        ),
    )


def _risk(signal: Signal) -> LiveEntryRiskEvaluation:
    risk_result = _risk_result()
    return LiveEntryRiskEvaluation(
        decision=TradingDecision(
            should_execute=True,
            signal=signal,
            risk_result=risk_result,
        ),
        has_existing_position=False,
    )


@dataclass(slots=True)
class _RiskEvaluator:
    async def evaluate(
        self,
        *,
        signal: Signal,
        entry_price_override: Decimal | None = None,
    ) -> LiveEntryRiskEvaluation:
        del entry_price_override
        return _risk(signal)


@dataclass(slots=True)
class _Market:
    async def get_executable_quote(self, *, symbol: str) -> ExecutableQuote:
        return ExecutableQuote(
            symbol=symbol,
            bid_price=Decimal("10"),
            ask_price=Decimal("10"),
            timestamp=_NOW,
        )


@dataclass(slots=True)
class _Entry:
    errors: dict[str, Exception] = field(default_factory=dict[str, Exception])
    calls: list[str] = field(default_factory=list[str])

    async def execute(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        interval: Interval,
        order_type: OrderType,
        price: Decimal | None,
    ) -> Order:
        del risk_result, interval, order_type, price
        self.calls.append(signal.symbol)
        error = self.errors.get(signal.symbol)
        if error is not None:
            raise error
        raise AssertionError("Focused continuation test should not reach success")


def _intent(symbol: str) -> AutonomousLiveEntryIntent:
    return AutonomousLiveEntryIntent(
        signal=_signal(symbol),
        risk_result=_risk_result(),
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_CROSS,
    )


def _authorization() -> AutonomousLiveEntryAuthorization:
    return AutonomousLiveEntryAuthorization(
        environment=ExchangeEnvironment.TESTNET,
        explicit_opt_in=True,
    )


@pytest.mark.asyncio
async def test_safe_candidate_rejections_continue_to_later_symbols() -> None:
    entry = _Entry(
        errors={
            "BTCUSDT": LiveEntryRiskLimitError("notional canary rejected"),
            "ETHUSDT": LiveEntrySymbolReadinessError("isolated margin required"),
            "SOLUSDT": LiveEntryRiskLimitError("balance cannot size venue minimum"),
        }
    )
    service = AutonomousLiveEntryExecutionService(
        risk_evaluation_service=_RiskEvaluator(),
        market_service=_Market(),
        live_futures_entry_service=entry,
        environment=ExchangeEnvironment.TESTNET,
        utc_now=lambda: _NOW,
    )

    results = await service.execute_many(
        intents=tuple(_intent(symbol) for symbol in entry.errors),
        authorization=_authorization(),
    )

    assert entry.calls == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert tuple(result.status for result in results) == (
        AutonomousLiveEntryExecutionStatus.RISK_REJECTED,
        AutonomousLiveEntryExecutionStatus.SYMBOL_READINESS_REJECTED,
        AutonomousLiveEntryExecutionStatus.RISK_REJECTED,
    )


@pytest.mark.asyncio
async def test_ambiguous_preflight_failure_is_not_downgraded_to_safe_rejection() -> (
    None
):
    entry = _Entry(errors={"BTCUSDT": LiveEntryPreflightError("timeout")})
    service = AutonomousLiveEntryExecutionService(
        risk_evaluation_service=_RiskEvaluator(),
        market_service=_Market(),
        live_futures_entry_service=entry,
        environment=ExchangeEnvironment.TESTNET,
        utc_now=lambda: _NOW,
    )

    with pytest.raises(LiveEntryPreflightError, match="timeout"):
        await service.execute(
            intent=_intent("BTCUSDT"),
            authorization=_authorization(),
        )
