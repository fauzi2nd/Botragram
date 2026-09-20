"""
Botragram

Description:
    Stepped stop loss configuration and runtime behavior tests.

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
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import SettingsManager
from botragram.app.environment_provider import EnvironmentProvider
from botragram.config.risk_settings import RiskSettings
from botragram.engine import RiskEngine
from botragram.engine.backtest_engine import BacktestEngine
from botragram.enums import (
    Interval,
    MarketType,
    PositionSide,
    SignalType,
    StrategyType,
    TradeMode,
)
from botragram.models import BacktestRequest, Candle, Position, Signal, Ticker
from botragram.services.position_protection_manager import (
    PositionProtectionManager,
)
from botragram.storage.memory import MemoryPositionRepository
from botragram.strategies.base import BaseStrategy

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 8, 7, tzinfo=UTC)


# =============================================================================
# Test Doubles
# =============================================================================
class BuyThenHoldStrategy(BaseStrategy):
    """Open once and hold so candle protection controls the exit."""

    __slots__ = ()

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.EMA_SCALPING

    @property
    def minimum_candles(self) -> int:
        return 1

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        self.validate_candles(candles=candles)
        candle = candles[-1]
        return Signal(
            symbol=candle.symbol,
            signal_type=(SignalType.BUY if len(candles) == 1 else SignalType.HOLD),
            price=candle.close_price,
            confidence=Decimal("1"),
            strategy_name=self.strategy_type.value,
            generated_at=candle.close_time,
            reason="Deterministic test signal",
        )


def _create_candle(
    *,
    minute: int,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
) -> Candle:
    start = _NOW + timedelta(minutes=minute)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M1,
        open_time=start,
        close_time=start + timedelta(minutes=1),
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
        volume=Decimal("10.0"),
    )


# =============================================================================
# Test Cases
# =============================================================================
def test_default_stepped_stop_risk_settings() -> None:
    """Verify default values for stepped stop in RiskSettings."""
    settings = RiskSettings()
    assert settings.stepped_stop_enabled is True
    assert settings.stepped_stop_thresholds == (
        Decimal("0.30"),
        Decimal("0.45"),
        Decimal("0.60"),
        Decimal("0.75"),
        Decimal("0.90"),
    )
    assert settings.stepped_stop_locked_lag == Decimal("0.20")
    assert settings.breakeven_roi_threshold == Decimal("0.30")
    assert settings.breakeven_fee_buffer == Decimal("0.0016")


def test_stepped_stop_settings_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """SettingsManager correctly parses stepped stop environment variables."""
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    monkeypatch.setenv("STEPPED_STOP_ENABLED", "false")
    monkeypatch.setenv("STEPPED_STOP_THRESHOLDS", "0.25,0.50,0.75")
    monkeypatch.setenv("STEPPED_STOP_LOCKED_LAG", "0.15")
    monkeypatch.setenv("BREAKEVEN_FEE_BUFFER", "0.0025")
    monkeypatch.setenv("BREAKEVEN_ROI_THRESHOLD", "0.40")

    env_file = tmp_path / "test.env"
    env_file.write_text("", encoding="utf-8")

    settings_manager = SettingsManager(
        environment_provider=EnvironmentProvider(env_path=str(env_file))
    )
    risk = settings_manager.load_risk_settings()

    assert risk.stepped_stop_enabled is False
    assert risk.stepped_stop_thresholds == (
        Decimal("0.25"),
        Decimal("0.50"),
        Decimal("0.75"),
    )
    assert risk.stepped_stop_locked_lag == Decimal("0.15")
    assert risk.breakeven_fee_buffer == Decimal("0.0025")
    assert risk.breakeven_roi_threshold == Decimal("0.40")


def test_stepped_stop_validation_errors() -> None:
    """Verify validation constraints on stepped stop parameters."""
    # Empty thresholds
    with pytest.raises(ValueError, match="cannot be empty"):
        RiskSettings(stepped_stop_thresholds=())

    # Not strictly increasing
    with pytest.raises(ValueError, match="strictly increasing"):
        RiskSettings(stepped_stop_thresholds=(Decimal("0.30"), Decimal("0.20")))

    # Threshold out of range
    with pytest.raises(ValueError, match="strictly between 0 and 1"):
        RiskSettings(stepped_stop_thresholds=(Decimal("1.20"),))

    # Locked lag >= first threshold
    with pytest.raises(ValueError, match="stepped_stop_locked_lag"):
        RiskSettings(
            stepped_stop_thresholds=(Decimal("0.20"), Decimal("0.50")),
            stepped_stop_locked_lag=Decimal("0.20"),
        )

    # Negative locked lag
    with pytest.raises(ValueError, match="stepped_stop_locked_lag"):
        RiskSettings(stepped_stop_locked_lag=Decimal("-0.05"))

    # Breakeven fee buffer >= 0.05
    with pytest.raises(ValueError, match="breakeven_fee_buffer"):
        RiskSettings(breakeven_fee_buffer=Decimal("0.06"))

    # Negative fee buffer
    with pytest.raises(ValueError, match="breakeven_fee_buffer"):
        RiskSettings(breakeven_fee_buffer=Decimal("-0.001"))


def test_risk_engine_custom_thresholds_and_lag() -> None:
    """RiskEngine stepped stop methods respect custom thresholds and lag."""
    custom_thresholds = (Decimal("0.25"), Decimal("0.50"), Decimal("0.75"))
    custom_lag = Decimal("0.15")
    custom_fee_buffer = Decimal("0.002")

    # Below first threshold
    assert (
        RiskEngine.resolve_protection_step(
            progress=Decimal("0.20"),
            thresholds=custom_thresholds,
        )
        == 0
    )

    # At first threshold (0.25) -> Step 2
    assert (
        RiskEngine.resolve_protection_step(
            progress=Decimal("0.25"),
            thresholds=custom_thresholds,
        )
        == 2
    )

    # At second threshold (0.50) -> Step 3
    assert (
        RiskEngine.resolve_protection_step(
            progress=Decimal("0.55"),
            thresholds=custom_thresholds,
        )
        == 3
    )

    # Stop loss calculation for LONG
    # entry 100, tp 120 (tp_distance = 20)
    # Step 2: locked_progress = 0.25 - 0.15 = 0.10
    # nominal_distance = 20 * 0.10 = 2.0
    # fee_buffer_distance = 100 * 0.002 = 0.20
    # locked_distance = max(0.20, 2.0) = 2.0 -> SL = 102.0
    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("106.0"),
        unrealized_pnl=Decimal("6.0"),
        leverage=1,
        take_profit=Decimal("120.0"),
        stop_loss=Decimal("95.0"),
        protection_step=0,
        opened_at=_NOW,
        updated_at=_NOW,
    )

    stop_price = RiskEngine.calculate_stepped_stop_loss(
        position=position,
        step=2,
        thresholds=custom_thresholds,
        locked_lag=custom_lag,
        breakeven_fee_buffer=custom_fee_buffer,
    )
    assert stop_price == Decimal("102.0")


@pytest.mark.asyncio
async def test_position_protection_manager_disabled() -> None:
    """When stepped_stop_enabled is False, stop loss is not moved by stepped stop."""
    repository = MemoryPositionRepository()
    exchange_client = AsyncMock()

    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("100.0"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        take_profit=Decimal("120.0"),
        stop_loss=Decimal("95.0"),
        protection_step=0,
        opened_at=_NOW,
        updated_at=_NOW,
    )
    await repository.save(position=position)

    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=repository,
        exchange_client=exchange_client,
        stepped_stop_enabled=False,
    )

    # Market tick reaches 110.0 (50% TP progress, well above step 2 & 3)
    ticker = Ticker(
        symbol="BTCUSDT",
        bid_price=Decimal("109.9"),
        ask_price=Decimal("110.1"),
        last_price=Decimal("110.0"),
        timestamp=_NOW,
    )
    await manager.on_market_tick(ticker=ticker)

    # Position in repo must remain unchanged
    updated = await repository.get_by_symbol(symbol="BTCUSDT")
    assert updated is not None
    assert updated.protection_step == 0
    assert updated.stop_loss == Decimal("95.0")


@pytest.mark.asyncio
async def test_position_protection_manager_custom_config() -> None:
    """PositionProtectionManager respects custom stepped stop configuration."""
    repository = MemoryPositionRepository()
    exchange_client = AsyncMock()

    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("100.0"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        take_profit=Decimal("120.0"),
        stop_loss=Decimal("95.0"),
        protection_step=0,
        opened_at=_NOW,
        updated_at=_NOW,
    )
    await repository.save(position=position)

    # Custom thresholds: 0.20 triggers step 2 with 0.10 lag -> locks 10% (SL 102)
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=repository,
        exchange_client=exchange_client,
        stepped_stop_enabled=True,
        stepped_stop_thresholds=(Decimal("0.20"), Decimal("0.50")),
        stepped_stop_locked_lag=Decimal("0.10"),
        breakeven_roi_threshold=Decimal("0.50"),
    )

    # Ticker at 104.5 (22.5% TP progress -> triggers Step 2 at 0.20)
    ticker = Ticker(
        symbol="BTCUSDT",
        bid_price=Decimal("104.4"),
        ask_price=Decimal("104.6"),
        last_price=Decimal("104.5"),
        timestamp=_NOW,
    )
    await manager.on_market_tick(ticker=ticker)

    updated = await repository.get_by_symbol(symbol="BTCUSDT")
    assert updated is not None
    assert updated.protection_step == 2
    assert updated.stop_loss == Decimal("102.0")


@pytest.mark.asyncio
async def test_backtest_engine_stepped_stop_disabled() -> None:
    """BacktestEngine respects stepped_stop_enabled=False."""
    # When stepped_stop_enabled is False, 30% ROI does NOT arm breakeven or stepped SL+
    risk = RiskSettings(
        leverage=20,
        scalping_stop_loss_pct=Decimal("0.02"),
        scalping_take_profit_pct=Decimal("0.06"),
        stepped_stop_enabled=False,
    )
    engine = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=risk,
    )

    candles = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="100.2",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="100",
            # 1.6% move * 20 leverage = 32% ROI (exceeds 30% BE threshold)
            high_price="101.6",
            low_price="100",
            close_price="101.5",
        ),
        _create_candle(
            minute=2,
            open_price="100.4",
            high_price="100.5",
            # Triggers BE stop (~100.16) if stepped_stop were enabled
            low_price="100.2",
            close_price="100.3",
        ),
    )

    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_NOW,
        end_time=_NOW + timedelta(minutes=3),
        initial_balance=Decimal("100"),
    )

    result = await engine.run(request=request, candles=candles)

    # Position is NOT stopped out at breakeven because stepped stop is disabled.
    # It remains open until closed by the finalizer at the end of the backtest.
    assert len(result.trades) == 1
    assert result.trades[0].reason == "End of backtest range"


@pytest.mark.asyncio
async def test_backtest_engine_stepped_stop_enabled() -> None:
    """BacktestEngine arms breakeven stop when stepped_stop_enabled=True."""
    risk = RiskSettings(
        leverage=20,
        scalping_stop_loss_pct=Decimal("0.02"),
        scalping_take_profit_pct=Decimal("0.06"),
        stepped_stop_enabled=True,
    )
    engine = BacktestEngine(
        strategy=BuyThenHoldStrategy(),
        risk_settings=risk,
    )

    candles = (
        _create_candle(
            minute=0,
            open_price="100",
            high_price="100.2",
            low_price="99.9",
            close_price="100",
        ),
        _create_candle(
            minute=1,
            open_price="100",
            # 1.6% move * 20 leverage = 32% ROI (exceeds 30% BE threshold)
            high_price="101.6",
            low_price="100",
            close_price="101.5",
        ),
        _create_candle(
            minute=2,
            open_price="100.4",
            high_price="100.5",
            # Hits BE stop (~100.16) on candle 2 pullback
            low_price="100.1",
            close_price="100.3",
        ),
    )

    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M1,
        strategy_type=StrategyType.EMA_SCALPING,
        market_type=MarketType.FUTURES,
        start_time=_NOW,
        end_time=_NOW + timedelta(minutes=3),
        initial_balance=Decimal("100"),
    )

    result = await engine.run(request=request, candles=candles)

    assert len(result.trades) == 1
    assert result.trades[0].reason == "Paper stop-loss triggered"
    assert result.trades[0].exit_price >= Decimal("100.09")
