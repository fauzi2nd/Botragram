"""Regression tests for the final per-trade risk budget boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.config.risk_settings import RiskSettings
from botragram.engine.risk.risk_engine import RiskEngine
from botragram.enums import SignalType, StrategyType
from botragram.models import Signal

__all__: list[str] = []


def _signal(
    *, strategy_name: str = "trend", stop_loss: Decimal = Decimal("90")
) -> Signal:
    """Create a buy signal with an explicit protective stop."""
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        stop_loss=stop_loss,
        confidence=Decimal("0.91"),
        strategy_name=strategy_name,
        generated_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("slot_sizing_enabled", [False, True])
def test_final_size_never_exceeds_risk_budget(slot_sizing_enabled: bool) -> None:
    """Multiplier and slot allocation cannot raise the final stop risk."""
    settings = RiskSettings(
        risk_per_trade_pct=Decimal("0.02"),
        max_position_size_usdt=Decimal("10000"),
        slot_sizing_enabled=slot_sizing_enabled,
        dynamic_sizing_enabled=True,
        confidence_sizing_enabled=True,
        baseline_confidence=Decimal("0.70"),
        leverage=5,
        stop_loss_pct=Decimal("0.10"),
        take_profit_pct=Decimal("0.20"),
        trend_stop_loss_pct=Decimal("0.10"),
        trend_take_profit_pct=Decimal("0.20"),
    )
    result = RiskEngine(settings=settings).evaluate(
        signal=_signal(),
        account_balance=Decimal("1000"),
        remaining_slots=1 if slot_sizing_enabled else None,
    )
    assert result.approved
    assert result.position is not None
    assert result.metrics.risk_amount <= Decimal("20")
    assert result.position.notional <= Decimal("200")


def test_minimum_notional_cannot_override_risk_budget() -> None:
    """Reject a trade if its minimum order would breach the risk budget."""
    settings = RiskSettings(
        risk_per_trade_pct=Decimal("0.01"),
        slot_sizing_enabled=True,
        min_order_notional_usdt=Decimal("5"),
        stop_loss_pct=Decimal("0.10"),
        take_profit_pct=Decimal("0.20"),
        trend_stop_loss_pct=Decimal("0.10"),
        trend_take_profit_pct=Decimal("0.20"),
    )
    result = RiskEngine(settings=settings).evaluate(
        signal=_signal(),
        account_balance=Decimal("10"),
        remaining_slots=1,
    )
    assert not result.approved
    assert result.reason is not None
    assert "minimum order notional" in result.reason.lower()


def test_pier_override_is_the_effective_hard_budget() -> None:
    """PIER's smaller override must bound slot sizing too."""
    settings = RiskSettings(
        risk_per_trade_pct=Decimal("0.10"),
        pier_risk_per_trade_pct=Decimal("0.01"),
        pier_max_position_size_usdt=Decimal("10000"),
        slot_sizing_enabled=True,
        leverage=5,
        pier_stop_loss_pct=Decimal("0.10"),
        pier_take_profit_pct=Decimal("0.20"),
    )
    result = RiskEngine(settings=settings).evaluate(
        signal=_signal(strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value),
        account_balance=Decimal("1000"),
        remaining_slots=1,
    )
    assert result.approved
    assert result.metrics.risk_amount <= Decimal("10")


def test_repeating_decimal_quantity_stays_within_budget() -> None:
    """Risk rounding must not exceed the budget by a tiny decimal fraction."""
    settings = RiskSettings(
        risk_per_trade_pct=Decimal("0.02"),
        max_position_size_usdt=Decimal("1000"),
        trend_stop_loss_pct=Decimal("0.03"),
        trend_take_profit_pct=Decimal("0.06"),
    )
    result = RiskEngine(settings=settings).evaluate(
        signal=_signal(stop_loss=Decimal("97")),
        account_balance=Decimal("100"),
    )
    assert result.approved
    assert result.position is not None
    assert result.metrics.risk_amount <= Decimal("2")
    assert result.position.notional == result.position.quantity * Decimal("100")


def test_final_rounding_cannot_exceed_notional_ceiling() -> None:
    """Quantity division cannot round a capped notional back above its limit."""
    settings = RiskSettings(
        max_position_size_usdt=Decimal("5"),
        min_order_notional_usdt=Decimal("1"),
        risk_per_trade_pct=Decimal("0.50"),
        trend_stop_loss_pct=Decimal("0.10"),
        trend_take_profit_pct=Decimal("0.20"),
    )
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("3"),
        stop_loss=Decimal("2.9"),
        confidence=Decimal("0.8"),
        strategy_name="trend",
        generated_at=datetime.now(UTC),
    )
    result = RiskEngine(settings=settings).evaluate(
        signal=signal,
        account_balance=Decimal("100"),
    )
    assert result.approved
    assert result.position is not None
    assert result.position.notional <= Decimal("5")
    assert result.position.notional == result.position.quantity * signal.price
