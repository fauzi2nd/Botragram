"""
Botragram

Description:
    Unit tests for auto-adaptive timeframe scaling and PIER global overrides.

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
from unittest.mock import AsyncMock, create_autospec

# =============================================================================
# Third Party Imports
# =============================================================================
import pytest

from botragram.app.environment_provider import EnvironmentProvider
from botragram.app.settings_manager import SettingsManager

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.constants.env import ENV_PIER_TRAILING_SWING_TIMEFRAME
from botragram.engine import PositionExitEngine, RiskEngine
from botragram.enums import (
    Interval,
    PositionExitAction,
    PositionSide,
    SignalType,
    StrategyType,
    TradeMode,
    TrailingMode,
)
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Candle, Position, Signal, Ticker
from botragram.repositories import CandleRepository, PositionRepository
from botragram.services.position_protection_manager import (
    PositionProtectionManager,
    resolve_adaptive_trailing_timeframe,
)
from botragram.strategies.base import (
    resolve_effective_distance_pct,
    resolve_effective_natr_bounds,
    resolve_timeframe_scale_factor,
)
from botragram.strategies.price_action.pinbar_engulfing_ema_rsi import (
    resolve_adaptive_htf_interval,
)


# =============================================================================
# Tests
# =============================================================================
def test_resolve_timeframe_scale_factor() -> None:
    """Test volatility scaling factor calculated from square root of time."""
    assert resolve_timeframe_scale_factor(None) == Decimal("1.0")
    assert resolve_timeframe_scale_factor(Interval.M15) == Decimal("1.0")

    # 5m = 300s -> sqrt(300 / 900) = sqrt(1/3) ~= 0.577350
    scale_5m = resolve_timeframe_scale_factor(Interval.M5)
    assert scale_5m == Decimal("0.577350")

    # 1m = 60s -> sqrt(60 / 900) ~= 0.258199
    scale_1m = resolve_timeframe_scale_factor(Interval.M1)
    assert scale_1m == Decimal("0.258199")

    # 1h = 3600s -> sqrt(3600 / 900) = 2.0
    scale_1h = resolve_timeframe_scale_factor(Interval.H1)
    assert scale_1h == Decimal("2.000000")

    # 4h = 14400s -> sqrt(14400 / 900) = 4.0
    scale_4h = resolve_timeframe_scale_factor(Interval.H4)
    assert scale_4h == Decimal("4.000000")


def test_resolve_effective_natr_bounds_timeframe_scaling() -> None:
    """Test NATR threshold auto-adapts according to timeframe."""
    base_min = Decimal("0.0020")
    base_max = Decimal("0.0400")

    # 15m baseline
    eff_min_15m, eff_max_15m = resolve_effective_natr_bounds(
        "BTCUSDT", base_min, base_max, interval=Interval.M15
    )
    assert eff_min_15m == base_min
    assert eff_max_15m == base_max

    # 5m auto-adapted
    eff_min_5m, eff_max_5m = resolve_effective_natr_bounds(
        "BTCUSDT", base_min, base_max, interval=Interval.M5
    )
    assert eff_min_5m < base_min
    assert eff_min_5m == base_min * Decimal("0.577350")
    assert eff_max_5m is not None
    assert eff_max_5m == base_max * Decimal("0.577350")

    # 1h auto-adapted
    eff_min_1h, eff_max_1h = resolve_effective_natr_bounds(
        "BTCUSDT", base_min, base_max, interval=Interval.H1
    )
    assert eff_min_1h == base_min * Decimal("2.000000")
    assert eff_max_1h == base_max * Decimal("2.000000")


def test_resolve_effective_distance_pct_timeframe_scaling() -> None:
    """Test SL and trend distance percentages auto-adapt with timeframe."""
    base_sl = Decimal("0.0080")
    base_trend = Decimal("0.0010")

    # 5m
    eff_sl_5m, eff_trend_5m = resolve_effective_distance_pct(
        "BTCUSDT", base_sl, base_trend, interval=Interval.M5
    )
    assert eff_sl_5m == base_sl * Decimal("0.577350")
    assert eff_trend_5m == base_trend * Decimal("0.577350")

    # 1h
    eff_sl_1h, eff_trend_1h = resolve_effective_distance_pct(
        "BTCUSDT", base_sl, base_trend, interval=Interval.H1
    )
    assert eff_sl_1h == base_sl * Decimal("2.000000")
    assert eff_trend_1h == base_trend * Decimal("2.000000")


def test_resolve_adaptive_htf_interval() -> None:
    """Test higher-timeframe interval resolution for multi-TF structural target."""
    assert resolve_adaptive_htf_interval(None) is Interval.H1
    assert resolve_adaptive_htf_interval(Interval.M1) is Interval.M5
    assert resolve_adaptive_htf_interval(Interval.M5) is Interval.M15
    assert resolve_adaptive_htf_interval(Interval.M15) is Interval.H1
    assert resolve_adaptive_htf_interval(Interval.H1) is Interval.H4
    assert resolve_adaptive_htf_interval(Interval.H4) is Interval.D1


def test_resolve_adaptive_trailing_timeframe() -> None:
    """Test lower-timeframe swing resolution for trailing stop."""
    assert resolve_adaptive_trailing_timeframe(None) is Interval.M5
    assert resolve_adaptive_trailing_timeframe(Interval.M1) is Interval.M1
    assert resolve_adaptive_trailing_timeframe(Interval.M5) is Interval.M3
    assert resolve_adaptive_trailing_timeframe(Interval.M15) is Interval.M5
    assert resolve_adaptive_trailing_timeframe(Interval.H1) is Interval.M15


def test_risk_engine_pier_overrides() -> None:
    """Test RiskEngine respects PIER-specific leverage, size, and risk overrides."""
    settings = RiskSettings(
        leverage=2,
        max_position_size_usdt=Decimal("500"),
        risk_per_trade_pct=Decimal("0.01"),
        pier_leverage=10,
        pier_max_position_size_usdt=Decimal("2000"),
        pier_risk_per_trade_pct=Decimal("0.05"),
    )
    engine = RiskEngine(settings=settings)

    now = datetime.now(UTC)
    pier_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        confidence=Decimal("0.80"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=now,
    )
    other_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        confidence=Decimal("0.80"),
        strategy_name=StrategyType.QUAD_CONFLUENCE.value,
        generated_at=now,
    )

    balance = Decimal("10000")
    # For PIER: risk is 5% of 10000 = 500 USDT. Risk per unit = 5 -> qty = 100.
    # But pier_max_position_size_usdt = 2000 -> capped at 2000 / 100 = 20.
    # Leverage is 10.
    pier_result = engine.evaluate(signal=pier_signal, account_balance=balance)
    assert pier_result.approved
    assert pier_result.position.leverage == 10
    assert pier_result.position.quantity == Decimal("20")

    # For other strategy: risk is 1% of 10000 = 100 USDT. Risk per unit = 5.
    # But max_position_size_usdt = 500 -> capped at 500 / 100 = 5.
    # Leverage is 2.
    other_result = engine.evaluate(signal=other_signal, account_balance=balance)
    assert other_result.approved
    assert other_result.position.leverage == 2
    assert other_result.position.quantity == Decimal("5")


@pytest.mark.asyncio
async def test_position_protection_manager_pier_overrides() -> None:
    """Test PositionProtectionManager respects PIER overrides and adaptive TF."""
    mock_pos_repo = create_autospec(PositionRepository, instance=True)
    mock_candle_repo = create_autospec(CandleRepository, instance=True)
    mock_client = create_autospec(BaseExchangeClient, instance=True)

    now = datetime.now(UTC)
    candles = [
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M3,
            open_time=now,
            close_time=now,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("98"),
            close_price=Decimal("103"),
            volume=Decimal("10"),
        )
        for _ in range(30)
    ]
    mock_candle_repo.get_latest = AsyncMock(return_value=candles)

    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=mock_pos_repo,
        exchange_client=mock_client,
        candle_repository=mock_candle_repo,
        trailing_mode=TrailingMode.STEPPED,
        pier_trailing_mode=TrailingMode.SWING_PIVOT,
        pier_trailing_swing_window=4,
        pier_trailing_buffer_pct=Decimal("0.0010"),
    )

    pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100"),
        current_price=Decimal("106"),
        unrealized_pnl=Decimal("6"),
        leverage=5,
        opened_at=now,
        updated_at=now,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        interval=Interval.M5,
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    mock_pos_repo.get_by_symbol = AsyncMock(return_value=pos)
    mock_pos_repo.update = AsyncMock()

    ticker = Ticker(
        symbol="BTCUSDT",
        bid_price=Decimal("106"),
        ask_price=Decimal("106"),
        last_price=Decimal("106"),
        timestamp=now,
    )

    await manager.on_market_tick(ticker=ticker)

    # Should have queried 3m candles (adaptive trailing TF for 5m position)
    mock_candle_repo.get_latest.assert_awaited()
    call_kwargs = mock_candle_repo.get_latest.call_args.kwargs
    assert call_kwargs["interval"] is Interval.M3
    assert call_kwargs["limit"] == 50


def test_position_exit_engine_pier_overrides() -> None:
    """Test PositionExitEngine respects PIER early exit overrides."""
    engine = PositionExitEngine(
        enabled=False,
        pier_enabled=True,
        pier_min_confidence=0.80,
    )
    now = datetime.now(UTC)
    pier_pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100"),
        current_price=Decimal("98"),
        unrealized_pnl=Decimal("-2"),
        leverage=5,
        opened_at=now,
        updated_at=now,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
    )
    other_pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100"),
        current_price=Decimal("98"),
        unrealized_pnl=Decimal("-2"),
        leverage=5,
        opened_at=now,
        updated_at=now,
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        strategy_type=StrategyType.QUAD_CONFLUENCE,
    )
    opp_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("98"),
        confidence=Decimal("0.85"),
        strategy_name="pinbar_engulfing_ema_rsi",
        generated_at=now,
    )

    # Non-PIER is skipped because global enabled=False
    other_decision = engine.evaluate(
        position=other_pos,
        candles=[],
        strategy_signal=opp_signal,
    )
    assert other_decision.action is PositionExitAction.HOLD
    assert "disabled" in other_decision.reason

    # PIER is evaluated because pier_enabled=True
    pier_decision = engine.evaluate(
        position=pier_pos,
        candles=[],
        strategy_signal=opp_signal,
    )
    assert pier_decision.action is PositionExitAction.EARLY_CUT_LOSS


def test_environment_provider_defensive_comment_ignoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify EnvironmentProvider treats values starting with # as empty."""
    monkeypatch.setenv(
        ENV_PIER_TRAILING_SWING_TIMEFRAME,
        "# Override swing timeframe (kosong = auto-adaptive)",
    )
    provider = EnvironmentProvider()
    assert provider.get_pier_trailing_swing_timeframe() == ""

    # SettingsManager parses empty string as None
    sm = SettingsManager(environment_provider=provider)
    risk_settings = sm.load_risk_settings()
    assert risk_settings.pier_trailing_swing_timeframe is None
