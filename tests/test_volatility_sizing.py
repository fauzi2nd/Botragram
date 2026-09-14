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
from pathlib import Path

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


def test_dynamic_sizing_and_leverage_settings_validation() -> None:
    """Validate bounds for dynamic sizing and adaptive leverage settings."""
    with pytest.raises(ValueError, match="baseline_confidence must be between 0 and 1"):
        RiskSettings(baseline_confidence=Decimal("0"))

    with pytest.raises(ValueError, match="Confidence multipliers must be positive"):
        RiskSettings(min_confidence_multiplier=Decimal("0"))

    with pytest.raises(
        ValueError,
        match="min_confidence_multiplier cannot exceed max_confidence_multiplier",
    ):
        RiskSettings(
            min_confidence_multiplier=Decimal("1.8"),
            max_confidence_multiplier=Decimal("1.2"),
        )

    with pytest.raises(ValueError, match="Leverage bounds must be positive"):
        RiskSettings(min_leverage=0)

    with pytest.raises(ValueError, match="min_leverage cannot exceed max_leverage"):
        RiskSettings(min_leverage=30, max_leverage=20)


def test_dynamic_confidence_sizing_scaling() -> None:
    """Scale position sizing dynamically based on signal confidence."""
    settings = RiskSettings(
        dynamic_sizing_enabled=True,
        confidence_sizing_enabled=True,
        baseline_confidence=Decimal("0.70"),
        max_confidence_multiplier=Decimal("1.5"),
        min_confidence_multiplier=Decimal("0.8"),
        max_position_size_usdt=Decimal("10000"),
        risk_per_trade_pct=Decimal("0.002"),  # 20 USDT risk -> 1000 USDT base notional
        trend_stop_loss_pct=Decimal("0.02"),
    )
    engine = RiskEngine(settings=settings)

    # 1. Baseline confidence (0.70) -> multiplier = 1.0x -> 1000 USDT
    sig_base = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        confidence=Decimal("0.70"),
        strategy_name="trend",
        generated_at=_NOW,
    )
    res_base = engine.evaluate(signal=sig_base, account_balance=Decimal("10000"))
    assert res_base.position is not None
    assert res_base.position.notional == Decimal("1000")

    # 2. High confidence (0.91) -> multiplier = 0.91 / 0.70 = 1.30x -> 1300 USDT
    sig_high = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        confidence=Decimal("0.91"),
        strategy_name="trend",
        generated_at=_NOW,
    )
    res_high = engine.evaluate(signal=sig_high, account_balance=Decimal("10000"))
    assert res_high.position is not None
    assert res_high.position.notional == Decimal("1300")

    # 3. Low confidence (0.50) -> 0.50 / 0.70 = 0.71 -> clamped to min 0.8x -> 800 USDT
    sig_low = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        confidence=Decimal("0.50"),
        strategy_name="trend",
        generated_at=_NOW,
    )
    res_low = engine.evaluate(signal=sig_low, account_balance=Decimal("10000"))
    assert res_low.position is not None
    assert res_low.position.notional == Decimal("800")


def test_dynamic_adaptive_leverage() -> None:
    """Adapt leverage to ensure liquidation distance stays outside stop loss."""
    settings = RiskSettings(
        dynamic_leverage_enabled=True,
        min_leverage=5,
        max_leverage=25,
        risk_per_trade_pct=Decimal("0.002"),
        trend_stop_loss_pct=Decimal("0.02"),
        scalping_stop_loss_pct=Decimal("0.008"),  # 0.8% tight SL
    )
    engine = RiskEngine(settings=settings)

    # 1. Tight SL (0.8%): safe leverage = int(1 / ((0.008 / 0.70) + 0.012)) = 42
    # Clamped to 25x max leverage.
    # Static leverage=5 passed into evaluate is overridden by adaptive leverage.
    sig_scalp = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        confidence=Decimal("0.70"),
        strategy_name="ema_scalping",
        generated_at=_NOW,
    )
    res_scalp = engine.evaluate(
        signal=sig_scalp,
        account_balance=Decimal("10000"),
        leverage=5,
    )
    assert res_scalp.position is not None
    assert res_scalp.position.leverage == 25

    # 2. Wide SL (8%): safe leverage = int(1 / ((0.08 / 0.70) + 0.012)) = 7
    # Resolves to leverage = 7x.
    settings_wide = RiskSettings(
        dynamic_leverage_enabled=True,
        min_leverage=5,
        max_leverage=25,
        risk_per_trade_pct=Decimal("0.002"),
        trend_stop_loss_pct=Decimal("0.08"),
        trend_take_profit_pct=Decimal("0.16"),
    )
    engine_wide = RiskEngine(settings=settings_wide)
    sig_wide = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100.0"),
        confidence=Decimal("0.70"),
        strategy_name="ema_rsi",
        generated_at=_NOW,
    )
    res_wide = engine_wide.evaluate(
        signal=sig_wide,
        account_balance=Decimal("10000"),
        leverage=20,
    )
    assert res_wide.position is not None
    assert res_wide.position.leverage == 7


def test_settings_manager_loads_dynamic_sizing_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify SettingsManager parses dynamic sizing environment variables."""
    from botragram.app.environment_provider import EnvironmentProvider
    from botragram.app.settings_manager import SettingsManager

    monkeypatch.delenv("BOTRAGRAM_ENV_FILE", raising=False)
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    monkeypatch.setenv("DYNAMIC_SIZING_ENABLED", "true")
    monkeypatch.setenv("CONFIDENCE_SIZING_ENABLED", "true")
    monkeypatch.setenv("BASELINE_CONFIDENCE", "0.75")
    monkeypatch.setenv("MAX_CONFIDENCE_MULTIPLIER", "1.6")
    monkeypatch.setenv("DYNAMIC_LEVERAGE_ENABLED", "true")
    monkeypatch.setenv("MIN_LEVERAGE", "8")
    monkeypatch.setenv("MAX_LEVERAGE", "30")

    manager = SettingsManager(
        environment_provider=EnvironmentProvider(
            env_path=str(tmp_path / "missing.env"),
        )
    )
    risk_settings = manager.load_risk_settings()

    assert risk_settings.dynamic_sizing_enabled is True
    assert risk_settings.confidence_sizing_enabled is True
    assert risk_settings.baseline_confidence == Decimal("0.75")
    assert risk_settings.max_confidence_multiplier == Decimal("1.6")
    assert risk_settings.dynamic_leverage_enabled is True
    assert risk_settings.min_leverage == 8
    assert risk_settings.max_leverage == 30


def test_dynamic_leverage_runtime_override() -> None:
    """Verify runtime dynamic_leverage_enabled parameter overrides settings."""
    # Base setting: dynamic_leverage_enabled = False, default leverage = 5
    engine_fixed = RiskEngine(
        settings=RiskSettings(
            stop_loss_pct=Decimal("0.02"),
            take_profit_pct=Decimal("0.06"),
            leverage=5,
            dynamic_leverage_enabled=False,
            min_leverage=5,
            max_leverage=50,
        )
    )
    sig = _create_signal(price=Decimal("100"))

    # 1. Without dynamic override, uses static leverage 5
    res_default = engine_fixed.evaluate(
        signal=sig,
        account_balance=Decimal("10000"),
        leverage=5,
    )
    assert res_default.position is not None
    assert res_default.position.leverage == 5

    # 2. With dynamic_leverage_enabled=True override,
    # computes safe_lev = int(1 / ((0.02 / 0.70) + 0.012)) = 24
    res_override_adaptive = engine_fixed.evaluate(
        signal=sig,
        account_balance=Decimal("10000"),
        leverage=5,
        dynamic_leverage_enabled=True,
    )
    assert res_override_adaptive.position is not None
    assert res_override_adaptive.position.leverage == 24

    # 3. Base setting: dynamic_leverage_enabled = True,
    # but override is False -> uses fixed leverage
    engine_adaptive = RiskEngine(
        settings=RiskSettings(
            stop_loss_pct=Decimal("0.02"),
            take_profit_pct=Decimal("0.06"),
            leverage=5,
            dynamic_leverage_enabled=True,
            min_leverage=5,
            max_leverage=50,
        )
    )
    res_override_fixed = engine_adaptive.evaluate(
        signal=sig,
        account_balance=Decimal("10000"),
        leverage=8,
        dynamic_leverage_enabled=False,
    )
    assert res_override_fixed.position is not None
    assert res_override_fixed.position.leverage == 8
