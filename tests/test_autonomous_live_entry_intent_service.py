"""TESTNET autonomous LIVE entry-intent authorization tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from botragram.config.risk_settings import RiskSettings
from botragram.engine import RiskEngine, TradingEngine
from botragram.enums import (
    AutonomousLiveEntryIntentStatus,
    ExchangeEnvironment,
    ExecutionPolicy,
    Interval,
    PositionSide,
    SignalType,
    StrategyType,
)
from botragram.models import (
    AutonomousLiveEntryAuthorization,
    Position,
    Signal,
    TradingDecision,
)
from botragram.services import AutonomousLiveEntryIntentService

_NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)
_BALANCE = Decimal("1000")


def _create_service() -> AutonomousLiveEntryIntentService:
    """Create the pure TESTNET authorization boundary."""
    return AutonomousLiveEntryIntentService(
        execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
        environment=ExchangeEnvironment.TESTNET,
    )


def _create_authorization() -> AutonomousLiveEntryAuthorization:
    """Create explicit TESTNET new-entry authorization."""
    return AutonomousLiveEntryAuthorization(
        environment=ExchangeEnvironment.TESTNET,
        explicit_opt_in=True,
    )


def _create_signal(
    *,
    symbol: str = "BTCUSDT",
    signal_type: SignalType = SignalType.BUY,
    confidence: Decimal = Decimal("0.8"),
) -> Signal:
    """Create a deterministic actionable strategy signal."""
    return Signal(
        symbol=symbol,
        signal_type=signal_type,
        price=Decimal("100"),
        confidence=confidence,
        strategy_name=StrategyType.EMA_CROSS.value,
        generated_at=_NOW,
    )


def _create_position(*, symbol: str) -> Position:
    """Create an active authoritative portfolio position."""
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


def _evaluate(
    *,
    signal: Signal,
    open_positions: tuple[Position, ...] = (),
) -> TradingDecision:
    """Evaluate a candidate through the existing portfolio/risk engine."""
    engine = TradingEngine(
        risk_engine=RiskEngine(
            settings=RiskSettings(max_open_positions=2),
        )
    )
    return engine.evaluate(
        signal=signal,
        account_balance=_BALANCE,
        has_open_position=False,
        open_positions=open_positions,
    )


def test_authorized_intent_is_immutable_and_has_no_submission_identity() -> None:
    """Produce only a typed transient intent after existing risk approval."""
    signal = _create_signal()
    result = _create_service().authorize(
        decision=_evaluate(signal=signal),
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        authorization=_create_authorization(),
    )

    assert result.status is AutonomousLiveEntryIntentStatus.AUTHORIZED
    assert result.intent is not None
    assert result.intent.symbol == "BTCUSDT"
    assert result.intent.side.value == "BUY"
    assert result.intent.interval is Interval.M15
    assert result.intent.strategy_type is StrategyType.EMA_CROSS
    assert result.intent.signal_generated_at is _NOW
    assert result.intent.quantity == Decimal("10")
    assert not hasattr(result.intent, "client_order_id")
    assert not hasattr(result.intent, "order_id")
    with pytest.raises(FrozenInstanceError):
        setattr(result.intent, "interval", Interval.M1)


def test_capability_absence_and_health_independent_boundary_return_no_intent() -> None:
    """Require explicit capability; no health or settings input can replace it."""
    result = _create_service().authorize(
        decision=_evaluate(signal=_create_signal()),
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        authorization=None,
    )

    assert result.status is AutonomousLiveEntryIntentStatus.AUTHORIZATION_REQUIRED
    assert result.intent is None


def test_existing_position_and_capacity_rejections_cannot_be_authorized() -> None:
    """Keep existing-position and portfolio capacity guards authoritative."""
    service = _create_service()
    authorization = _create_authorization()
    existing_symbol_result = service.authorize(
        decision=_evaluate(
            signal=_create_signal(),
            open_positions=(_create_position(symbol="BTCUSDT"),),
        ),
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        authorization=authorization,
    )
    capacity_result = service.authorize(
        decision=_evaluate(
            signal=_create_signal(symbol="SOLUSDT"),
            open_positions=(
                _create_position(symbol="BTCUSDT"),
                _create_position(symbol="ETHUSDT"),
            ),
        ),
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        authorization=authorization,
    )

    assert (
        existing_symbol_result.status is AutonomousLiveEntryIntentStatus.RISK_REJECTED
    )
    assert existing_symbol_result.intent is None
    assert capacity_result.status is AutonomousLiveEntryIntentStatus.RISK_REJECTED
    assert capacity_result.intent is None


def test_ranked_candidates_keep_the_existing_deterministic_sequence() -> None:
    """Preserve caller ranking without concurrent candidate work or reordering."""
    ranked_signals = (
        _create_signal(symbol="BTCUSDT", confidence=Decimal("0.9")),
        _create_signal(symbol="ETHUSDT", confidence=Decimal("0.9")),
        _create_signal(symbol="SOLUSDT", confidence=Decimal("0.8")),
    )
    results = _create_service().authorize_ranked(
        decisions=tuple(_evaluate(signal=signal) for signal in ranked_signals),
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
        authorization=_create_authorization(),
    )

    assert tuple(result.status for result in results) == (
        AutonomousLiveEntryIntentStatus.AUTHORIZED,
        AutonomousLiveEntryIntentStatus.AUTHORIZED,
        AutonomousLiveEntryIntentStatus.AUTHORIZED,
    )
    assert tuple(
        result.intent.symbol for result in results if result.intent is not None
    ) == (
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    )


def test_mainnet_boundary_cannot_be_constructed() -> None:
    """Reject MAINNET before any candidate can reach an intent boundary."""
    with pytest.raises(ValueError, match="TESTNET"):
        AutonomousLiveEntryIntentService(
            execution_policy=ExecutionPolicy.AUTONOMOUS_LIVE,
            environment=ExchangeEnvironment.MAINNET,
        )


def test_authorized_intent_rejects_conflicting_strategy_metadata() -> None:
    """Keep future protected-entry metadata aligned to its strategy signal."""
    with pytest.raises(ValueError, match="strategy must match"):
        _create_service().authorize(
            decision=_evaluate(signal=_create_signal()),
            interval=Interval.M15,
            strategy_type=StrategyType.EMA_SCALPING,
            authorization=_create_authorization(),
        )
