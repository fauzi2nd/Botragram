"""
Botragram

Description:
    Regression tests for RiskEngine Botragram Origin invariants.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from datetime import datetime, timezone
from decimal import Decimal

# =============================================================================
# Third Party
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine.risk_engine import RiskEngine
from botragram.enums import SignalType, StrategyType
from botragram.models import Signal


# =============================================================================
# Helpers
# =============================================================================
def _make_origin_signal(
    *,
    signal_type: SignalType = SignalType.BUY,
    price: Decimal = Decimal("100.0"),
    stop_loss: Decimal | None = Decimal("98.0"),
    take_profit: Decimal | None = Decimal("103.0"),
    confidence: Decimal = Decimal("0.85"),
) -> Signal:
    return Signal(
        symbol="BTCUSDT",
        signal_type=signal_type,
        price=price,
        confidence=confidence,
        strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
        generated_at=datetime.now(timezone.utc),
        stop_loss=stop_loss,
        take_profit=take_profit,
        reason="Botragram Origin: bullish_pinbar",
    )


# =============================================================================
# Invariant Tests
# =============================================================================
def test_origin_valid_signal_approved_with_canonical_exits() -> None:
    """Valid Origin BUY and SELL signals preserve canonical SL/TP without truncation."""
    engine = RiskEngine(
        settings=RiskSettings(
            origin_stop_loss_pct=Decimal("0.05"),
        )
    )

    # BUY: entry=100, SL=98 (dist=2), TP=103 (dist=3, RR=1.5)
    buy_sig = _make_origin_signal(
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        stop_loss=Decimal("98.0"),
        take_profit=Decimal("103.0"),
    )
    buy_result = engine.evaluate(signal=buy_sig, account_balance=Decimal("10000"))
    assert buy_result.approved
    assert buy_result.metrics.stop_loss == Decimal("98.0")
    assert buy_result.metrics.take_profit == Decimal("103.0")
    assert buy_result.metrics.risk_reward_ratio == Decimal("1.5")

    # SELL: entry=100, SL=102 (dist=2), TP=97 (dist=3, RR=1.5)
    sell_sig = _make_origin_signal(
        signal_type=SignalType.SELL,
        price=Decimal("100.0"),
        stop_loss=Decimal("102.0"),
        take_profit=Decimal("97.0"),
    )
    sell_result = engine.evaluate(signal=sell_sig, account_balance=Decimal("10000"))
    assert sell_result.approved
    assert sell_result.metrics.stop_loss == Decimal("102.0")
    assert sell_result.metrics.take_profit == Decimal("97.0")
    assert sell_result.metrics.risk_reward_ratio == Decimal("1.5")


@pytest.mark.parametrize(
    "sl_value",
    [Decimal("0"), Decimal("-1.0"), Decimal("nan")],
)
def test_origin_rejects_non_positive_or_non_finite_sl(sl_value: Decimal) -> None:
    """Origin signal with non-positive or non-finite SL is rejected fail-closed."""
    engine = RiskEngine(settings=RiskSettings())
    sig = _make_origin_signal(stop_loss=sl_value)
    result = engine.evaluate(signal=sig, account_balance=Decimal("10000"))
    assert not result.approved
    assert "Explicit stop-loss must be finite and positive" in result.reason


@pytest.mark.parametrize(
    "tp_value",
    [Decimal("0"), Decimal("-1.0"), Decimal("nan")],
)
def test_origin_rejects_non_positive_or_non_finite_tp(tp_value: Decimal) -> None:
    """Origin signal with non-positive or non-finite TP is rejected fail-closed."""
    engine = RiskEngine(settings=RiskSettings())
    sig = _make_origin_signal(take_profit=tp_value)
    result = engine.evaluate(signal=sig, account_balance=Decimal("10000"))
    assert not result.approved
    assert "Explicit take-profit must be finite and positive" in result.reason


def test_origin_rejects_wrong_side_sl() -> None:
    """BUY SL >= entry and SELL SL <= entry are rejected."""
    engine = RiskEngine(settings=RiskSettings())

    # BUY with SL above entry
    sig_buy_sl_above = _make_origin_signal(
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        stop_loss=Decimal("101.0"),
        take_profit=Decimal("105.0"),
    )
    res = engine.evaluate(signal=sig_buy_sl_above, account_balance=Decimal("10000"))
    assert not res.approved
    assert "Explicit buy stop-loss must be below entry price" in res.reason

    # SELL with SL below entry
    sig_sell_sl_below = _make_origin_signal(
        signal_type=SignalType.SELL,
        price=Decimal("100.0"),
        stop_loss=Decimal("99.0"),
        take_profit=Decimal("95.0"),
    )
    res = engine.evaluate(signal=sig_sell_sl_below, account_balance=Decimal("10000"))
    assert not res.approved
    assert "Explicit sell stop-loss must be above entry price" in res.reason


def test_origin_rejects_wrong_side_tp() -> None:
    """BUY TP <= entry and SELL TP >= entry are rejected."""
    engine = RiskEngine(settings=RiskSettings())

    # BUY with TP below entry
    sig_buy_tp_below = _make_origin_signal(
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        stop_loss=Decimal("98.0"),
        take_profit=Decimal("99.0"),
    )
    res = engine.evaluate(signal=sig_buy_tp_below, account_balance=Decimal("10000"))
    assert not res.approved
    assert "Explicit buy take-profit must be above entry price" in res.reason

    # SELL with TP above entry
    sig_sell_tp_above = _make_origin_signal(
        signal_type=SignalType.SELL,
        price=Decimal("100.0"),
        stop_loss=Decimal("102.0"),
        take_profit=Decimal("101.0"),
    )
    res = engine.evaluate(signal=sig_sell_tp_above, account_balance=Decimal("10000"))
    assert not res.approved
    assert "Explicit sell take-profit must be below entry price" in res.reason


def test_origin_rejects_zero_sl_or_tp_distance() -> None:
    """SL == entry or TP == entry are rejected."""
    engine = RiskEngine(settings=RiskSettings())

    # BUY with SL == price
    sig_zero_sl = _make_origin_signal(
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        stop_loss=Decimal("100.0"),
        take_profit=Decimal("105.0"),
    )
    res = engine.evaluate(signal=sig_zero_sl, account_balance=Decimal("10000"))
    assert not res.approved
    assert "Explicit buy stop-loss must be below entry price" in res.reason

    # BUY with TP == price
    sig_zero_tp = _make_origin_signal(
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        stop_loss=Decimal("98.0"),
        take_profit=Decimal("100.0"),
    )
    res = engine.evaluate(signal=sig_zero_tp, account_balance=Decimal("10000"))
    assert not res.approved
    assert "Explicit buy take-profit must be above entry price" in res.reason


def test_origin_rejects_inverted_rr_relationship() -> None:
    """Origin signal with TP distance < SL distance (RR < 1.0R) must be rejected."""
    engine = RiskEngine(
        settings=RiskSettings(
            origin_stop_loss_pct=Decimal("0.05"),
        )
    )

    # BUY: SL distance = 2.0 (entry 100, SL 98), TP distance = 1.0 (TP 101)
    sig_buy_inverted = _make_origin_signal(
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        stop_loss=Decimal("98.0"),
        take_profit=Decimal("101.0"),
    )
    res_buy = engine.evaluate(signal=sig_buy_inverted, account_balance=Decimal("10000"))
    assert not res_buy.approved
    assert "Origin risk-reward ratio cannot be less than 1.0R" in res_buy.reason

    # SELL: SL distance = 2.0 (entry 100, SL 102), TP distance = 1.0 (TP 99)
    sig_sell_inverted = _make_origin_signal(
        signal_type=SignalType.SELL,
        price=Decimal("100.0"),
        stop_loss=Decimal("102.0"),
        take_profit=Decimal("99.0"),
    )
    res_sell = engine.evaluate(
        signal=sig_sell_inverted, account_balance=Decimal("10000")
    )
    assert not res_sell.approved
    assert "Origin risk-reward ratio cannot be less than 1.0R" in res_sell.reason


def test_origin_rejects_excessive_sl_distance() -> None:
    """Origin signal exceeding configured maximum SL risk ceiling must be rejected."""
    engine = RiskEngine(
        settings=RiskSettings(
            origin_stop_loss_pct=Decimal("0.02"),  # 2% max SL
        )
    )

    # BUY: entry=100, SL=97 (3% distance > 2% max), TP=106 (6% dist, RR=2.0)
    sig_excessive_sl = _make_origin_signal(
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        stop_loss=Decimal("97.0"),
        take_profit=Decimal("106.0"),
    )
    res = engine.evaluate(signal=sig_excessive_sl, account_balance=Decimal("10000"))
    assert not res.approved
    assert "Origin stop-loss distance exceeds maximum risk ceiling" in res.reason
