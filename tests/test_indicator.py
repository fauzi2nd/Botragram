"""
Botragram

Description:
    Unit tests for technical indicators.

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
from botragram.exchanges.base.mapper import Candle
from botragram.indicators.atr import calculate_atr
from botragram.indicators.ema import calculate_ema
from botragram.indicators.macd import calculate_macd
from botragram.indicators.rsi import calculate_rsi
from botragram.indicators.sma import calculate_sma
from botragram.indicators.supertrend import calculate_supertrend


def test_sma_calculation() -> None:
    """Test SMA calculation."""
    prices = [Decimal(x) for x in ["10", "20", "30", "40", "50"]]
    sma = calculate_sma(prices, period=3)
    assert len(sma) == 3
    assert sma[0] == Decimal("20")  # (10+20+30)/3
    assert sma[1] == Decimal("30")  # (20+30+40)/3
    assert sma[2] == Decimal("40")  # (30+40+50)/3


def test_ema_calculation() -> None:
    """Test EMA calculation."""
    prices = [Decimal(x) for x in ["10", "12", "14", "16", "18", "20"]]
    ema = calculate_ema(prices, period=3)
    assert len(ema) == 4  # 1 initial SMA + 3 EMA steps
    assert ema[0] == Decimal("12")


def test_rsi_calculation() -> None:
    """Test RSI calculation."""
    prices = [Decimal(x) for x in range(100, 120)]
    rsi = calculate_rsi(prices, period=14)
    assert len(rsi) > 0
    assert rsi[-1] == Decimal("100")  # Monotonically increasing prices


def test_macd_calculation() -> None:
    """Test MACD calculation."""
    prices = [Decimal(x) for x in range(10, 50)]
    results = calculate_macd(prices, fast_period=5, slow_period=10, signal_period=3)
    assert len(results) > 0


def test_atr_and_supertrend() -> None:
    """Test ATR and Supertrend calculation with mock candles."""
    candles = [
        Candle(
            timestamp_ms=i * 60000,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("102"),
            volume=Decimal("10"),
        )
        for i in range(20)
    ]
    atr = calculate_atr(candles, period=5)
    assert len(atr) > 0

    st = calculate_supertrend(candles, period=5, multiplier=Decimal("2"))
    assert len(st) > 0
