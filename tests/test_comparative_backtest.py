"""
Botragram

Description:
    Tests for comparative backtesting comparing baseline vs trailing stop &
    volatility sizing.

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

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.enums import Interval, MarketType, PositionSide, SignalType, StrategyType
from botragram.models import (
    BacktestRequest,
    BacktestTrade,
    Candle,
    Signal,
)
from botragram.services.comparative_backtest_service import (
    ComparativeBacktestService,
    calculate_sharpe_ratio,
)
from botragram.strategies.base import BaseStrategy

_START = datetime(2026, 1, 1, tzinfo=UTC)


class TrendPullbackStrategy(BaseStrategy):
    """Simple test strategy that generates a BUY signal on candle 3."""

    __slots__ = ()

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.EMA_CROSS

    @property
    def minimum_candles(self) -> int:
        return 3

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        last = candles[-1]
        if len(candles) == 3:
            return Signal(
                symbol=last.symbol,
                signal_type=SignalType.BUY,
                price=last.close_price,
                confidence=Decimal("0.85"),
                strategy_name="trend_pullback",
                generated_at=last.close_time,
                reason="entry_signal",
            )

        return Signal(
            symbol=last.symbol,
            signal_type=SignalType.HOLD,
            price=last.close_price,
            confidence=Decimal("0.5"),
            strategy_name="trend_pullback",
            generated_at=last.close_time,
        )


def _build_test_candles() -> list[Candle]:
    """Generate a realistic price progression: entry, rally, sharp pullback."""
    prices = [
        (100.0, 100.5, 99.5, 100.0),
        (100.0, 100.8, 99.8, 100.2),
        (100.2, 101.0, 100.0, 100.5),
        (100.5, 103.5, 100.3, 102.0),
        (102.0, 105.0, 101.8, 104.0),
        (104.0, 104.2, 100.5, 101.0),
        (101.0, 101.2, 93.5, 94.0),
    ]
    candles: list[Candle] = []
    current_time = _START
    for open_p, high_p, low_p, close_p in prices:
        close_time = current_time + timedelta(minutes=15)
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=Interval.M15,
                open_time=current_time,
                close_time=close_time,
                open_price=Decimal(str(open_p)),
                high_price=Decimal(str(high_p)),
                low_price=Decimal(str(low_p)),
                close_price=Decimal(str(close_p)),
                volume=Decimal("100"),
            )
        )
        current_time = close_time
    return candles


def test_calculate_sharpe_ratio_edge_cases() -> None:
    """Verify Sharpe ratio handling of 0 or 1 trade and zero variance."""
    assert calculate_sharpe_ratio([]) == Decimal("0")

    single_trade = BacktestTrade(
        side=PositionSide.LONG,
        entry_time=_START,
        exit_time=_START + timedelta(hours=1),
        entry_price=Decimal("100"),
        exit_price=Decimal("105"),
        quantity=Decimal("1"),
        fees=Decimal("0.1"),
        realized_pnl=Decimal("4.9"),
        reason="TP",
    )
    assert calculate_sharpe_ratio([single_trade]) == Decimal("0")

    second_trade = BacktestTrade(
        side=PositionSide.LONG,
        entry_time=_START + timedelta(hours=2),
        exit_time=_START + timedelta(hours=3),
        entry_price=Decimal("100"),
        exit_price=Decimal("102"),
        quantity=Decimal("1"),
        fees=Decimal("0.1"),
        realized_pnl=Decimal("1.9"),
        reason="TP",
    )
    sharpe = calculate_sharpe_ratio([single_trade, second_trade])
    assert sharpe > Decimal("0")


@pytest.mark.asyncio
async def test_comparative_backtest_trailing_stop_protection() -> None:
    """Verify that Enhanced run with Trailing Stop locks profit before pullback."""
    strategy = TrendPullbackStrategy()
    risk_settings = RiskSettings(
        max_position_size_usdt=Decimal("500"),
        risk_per_trade_pct=Decimal("0.05"),
        stop_loss_pct=Decimal("0.05"),
        take_profit_pct=Decimal("0.20"),
        ema_cross_stop_loss_pct=Decimal("0.05"),
        ema_cross_take_profit_pct=Decimal("0.20"),
        leverage=1,
    )
    service = ComparativeBacktestService(
        strategy=strategy,
        base_risk_settings=risk_settings,
    )

    candles = _build_test_candles()
    request = BacktestRequest(
        symbol="BTCUSDT",
        interval=Interval.M15,
        start_time=candles[0].open_time,
        end_time=candles[-1].close_time,
        strategy_type=StrategyType.EMA_CROSS,
        market_type=MarketType.SPOT,
        initial_balance=Decimal("1000"),
    )

    result = await service.run(
        request=request,
        candles=candles,
        trailing_stop_trigger_pct=Decimal("0.015"),
        trailing_stop_distance_pct=Decimal("0.008"),
    )

    # Baseline hits stop loss at 95 (loss)
    # Enhanced locks trailing stop at ~104.16 during rally (profit)
    assert result.baseline_result.metrics.net_pnl < Decimal("0")
    assert result.enhanced_result.metrics.net_pnl > Decimal("0")
    assert result.pnl_delta_usdt > Decimal("0")
    assert "Comparative Backtest" in result.summary_report
    assert "Enhanced (Trailing+Vol)" in result.summary_report
