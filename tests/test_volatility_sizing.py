"""
Botragram

Description:
    Regression tests for volatility-adjusted dynamic position sizing.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from datetime import UTC, datetime
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine import RiskEngine
from botragram.enums import SignalType
from botragram.models import Signal

_NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _create_signal(*, price: Decimal = Decimal("100.0")) -> Signal:
    return Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=price,
        confidence=Decimal("0.9"),
        strategy_name="trend",
        generated_at=_NOW,
    )


def test_volatility_sizing_settings_validation() -> None:
    """Validate configuration bounds for volatility-adjusted position sizing."""
    settings = RiskSettings(
        volatility_sizing_enabled=True,
        baseline_volatility_pct=Decimal("0.025"),
    )
    assert settings.volatility_sizing_enabled is True
    assert settings.baseline_volatility_pct == Decimal("0.025")

    with pytest.raises(ValueError, match="strictly between 0 and 1"):
        RiskSettings(
            volatility_sizing_enabled=True,
            baseline_volatility_pct=Decimal("0"),
        )


def test_volatility_sizing_disabled_by_default() -> None:
    """Verify that disabled volatility sizing retains standard risk sizing."""
    engine = RiskEngine(settings=RiskSettings(volatility_sizing_enabled=False))
    signal = _create_signal()

    result_without_vol = engine.evaluate(
        signal=signal,
        account_balance=Decimal("10000"),
    )
    result_with_vol = engine.evaluate(
        signal=signal,
        account_balance=Decimal("10000"),
        volatility_pct=Decimal("0.04"),
    )

    assert result_without_vol.approved is True
    assert result_with_vol.approved is True
    assert result_without_vol.position is not None
    assert result_with_vol.position is not None
    assert result_without_vol.position.notional == result_with_vol.position.notional


def test_volatility_sizing_dynamic_scaling() -> None:
    """Scale position sizing inversely with volatility relative to baseline."""
    # Baseline: 2% (0.02), unscaled notional = 1000 USDT
    engine_unconstrained = RiskEngine(
        settings=RiskSettings(
            volatility_sizing_enabled=True,
            baseline_volatility_pct=Decimal("0.02"),
            max_position_size_usdt=Decimal("10000"),
            risk_per_trade_pct=Decimal(
                "0.002"
            ),  # 20 USDT risk -> 10 units -> 1000 USDT notional
            trend_stop_loss_pct=Decimal("0.02"),
        )
    )
    signal = _create_signal(price=Decimal("100.0"))

    # 1. Normal volatility (0.02 == baseline 0.02): multiplier = 1.0 -> notional = 1000
    res_normal = engine_unconstrained.evaluate(
        signal=signal,
        account_balance=Decimal("10000"),
        volatility_pct=Decimal("0.02"),
    )
    assert res_normal.position is not None
    assert res_normal.position.notional == Decimal("1000")

    # 2. Elevated volatility (0.04 vs baseline 0.02): multiplier = 0.5x
    res_high_vol = engine_unconstrained.evaluate(
        signal=signal,
        account_balance=Decimal("10000"),
        volatility_pct=Decimal("0.04"),
    )
    assert res_high_vol.position is not None
    assert res_high_vol.position.notional == Decimal("500")

    # 3. Calmer volatility (0.01 vs baseline 0.02): multiplier = 1.5x -> notional = 1500
    res_low_vol = engine_unconstrained.evaluate(
        signal=signal,
        account_balance=Decimal("10000"),
        volatility_pct=Decimal("0.01"),
    )
    assert res_low_vol.position is not None
    assert res_low_vol.position.notional == Decimal("1500")

    # 4. Extremely high volatility (0.10): bounded by min clamp 0.5x -> notional = 500
    res_extreme_high = engine_unconstrained.evaluate(
        signal=signal,
        account_balance=Decimal("10000"),
        volatility_pct=Decimal("0.10"),
    )
    assert res_extreme_high.position is not None
    assert res_extreme_high.position.notional == Decimal("500")

    # 5. Extremely low volatility (0.005): bounded by max clamp 1.5x -> notional = 1500
    res_extreme_low = engine_unconstrained.evaluate(
        signal=signal,
        account_balance=Decimal("10000"),
        volatility_pct=Decimal("0.005"),
    )
    assert res_extreme_low.position is not None
    assert res_extreme_low.position.notional == Decimal("1500")


def test_volatility_sizing_invalid_input() -> None:
    """Reject non-positive or non-finite volatility values."""
    engine = RiskEngine(settings=RiskSettings(volatility_sizing_enabled=True))
    signal = _create_signal()

    with pytest.raises(ValueError, match="finite and positive"):
        engine.evaluate(
            signal=signal,
            account_balance=Decimal("1000"),
            volatility_pct=Decimal("0"),
        )
