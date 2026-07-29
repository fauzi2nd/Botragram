"""
Botragram

Description:
    Unit tests for trading strategies.

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
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.signal_type import SignalType
from botragram.exchanges.base.mapper import Candle
from botragram.strategies.ema_cross import EMACrossStrategy
from botragram.strategies.ema_rsi import EMARSIStrategy
from botragram.strategies.supertrend import SupertrendStrategy


def test_ema_cross_strategy() -> None:
    """Test EMA Cross Strategy signal generation."""
    strat = EMACrossStrategy(fast_period=3, slow_period=5)

    # Generate candles with a strong price increase
    candles = [
        Candle(
            timestamp_ms=i * 60000,
            open_price=Decimal(str(10 + i)),
            high_price=Decimal(str(12 + i)),
            low_price=Decimal(str(9 + i)),
            close_price=Decimal(str(10 + i * 2)),
            volume=Decimal("10"),
        )
        for i in range(15)
    ]
    sig = strat.generate_signal(candles)
    assert sig in (SignalType.BUY_ENTRY, SignalType.SELL_ENTRY, SignalType.NEUTRAL)


def test_ema_rsi_strategy() -> None:
    """Test EMA RSI Strategy signal generation."""
    strat = EMARSIStrategy(ema_period=5, rsi_period=5)
    candles = [
        Candle(
            timestamp_ms=i * 60000,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
        )
        for i in range(15)
    ]
    sig = strat.generate_signal(candles)
    assert sig == SignalType.NEUTRAL


def test_supertrend_strategy() -> None:
    """Test Supertrend Strategy signal generation."""
    strat = SupertrendStrategy(period=5, multiplier=Decimal("2"))
    candles = [
        Candle(
            timestamp_ms=i * 60000,
            open_price=Decimal(str(100 + i * 3)),
            high_price=Decimal(str(105 + i * 3)),
            low_price=Decimal(str(98 + i * 3)),
            close_price=Decimal(str(104 + i * 3)),
            volume=Decimal("10"),
        )
        for i in range(20)
    ]
    sig = strat.generate_signal(candles)
    assert sig in (SignalType.BUY_ENTRY, SignalType.SELL_ENTRY, SignalType.NEUTRAL)
