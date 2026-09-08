"""
Botragram

Description:
    Unit tests for multi-timeframe (MTF) trend evaluation and filtering.

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
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.indicators.trend.mtf_trend_filter import (
    TrendDirection,
    evaluate_mtf_trend,
)
from botragram.models import Candle

_BASE_TIME = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def _make_candles(
    prices: list[Decimal],
    interval: Interval = Interval.H1,
) -> list[Candle]:
    candles: list[Candle] = []
    for i, p in enumerate(prices):
        t = _BASE_TIME + timedelta(hours=i)
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=interval,
                open_time=t,
                close_time=t + timedelta(hours=1),
                open_price=p,
                high_price=p + Decimal("1"),
                low_price=p - Decimal("1"),
                close_price=p,
                volume=Decimal("100"),
            )
        )
    return candles


def test_evaluate_mtf_trend_empty() -> None:
    """Verify empty candle sequence yields neutral trend result."""
    result = evaluate_mtf_trend([])
    assert result.direction is TrendDirection.NEUTRAL
    assert result.ema_value is None
    assert result.is_aligned_with_buy is True
    assert result.is_aligned_with_sell is True


def test_evaluate_mtf_trend_insufficient_candles() -> None:
    """Verify fewer candles than ema_period yields neutral result."""
    prices = [Decimal("100") + Decimal(i) for i in range(10)]
    candles = _make_candles(prices)
    result = evaluate_mtf_trend(candles, ema_period=20)
    assert result.direction is TrendDirection.NEUTRAL
    assert result.ema_value is None
    assert result.current_close == Decimal("109")


def test_evaluate_mtf_trend_bullish() -> None:
    """Verify prices trending upwards produce bullish MTF alignment."""
    # 30 candles rising sharply from 100 to 160
    prices = [Decimal("100") + Decimal(i * 2) for i in range(30)]
    candles = _make_candles(prices)
    result = evaluate_mtf_trend(candles, ema_period=10)
    assert result.direction is TrendDirection.BULLISH
    assert result.ema_value is not None
    assert result.current_close > result.ema_value
    assert result.is_aligned_with_buy is True
    assert result.is_aligned_with_sell is False


def test_evaluate_mtf_trend_bearish() -> None:
    """Verify prices trending downwards produce bearish MTF alignment."""
    # 30 candles falling from 200 to 140
    prices = [Decimal("200") - Decimal(i * 2) for i in range(30)]
    candles = _make_candles(prices)
    result = evaluate_mtf_trend(candles, ema_period=10)
    assert result.direction is TrendDirection.BEARISH
    assert result.ema_value is not None
    assert result.current_close < result.ema_value
    assert result.is_aligned_with_buy is False
    assert result.is_aligned_with_sell is True
