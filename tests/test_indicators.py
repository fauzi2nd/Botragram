"""
Botragram

Description:
    Deterministic technical indicator tests.

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
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.indicators import (
    calculate_adx,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_choch_fvg,
    calculate_ema,
    calculate_ichimoku,
    calculate_macd,
    calculate_obv,
    calculate_psar,
    calculate_rsi,
    calculate_sma,
    calculate_supertrend,
    calculate_vwap,
)


# =============================================================================
# Test Helpers
# =============================================================================
def _decimal_series(
    *values: int | str,
) -> tuple[Decimal, ...]:
    """Build a Decimal tuple for concise indicator fixtures."""
    return tuple(Decimal(value) for value in values)


def _trending_prices(
    *,
    length: int,
) -> tuple[tuple[Decimal, ...], tuple[Decimal, ...], tuple[Decimal, ...]]:
    """Build a deterministic upward price series."""
    closes = tuple(Decimal(index) for index in range(1, length + 1))
    highs = tuple(close + Decimal("1") for close in closes)
    lows = tuple(close - Decimal("1") for close in closes)

    return highs, lows, closes


# =============================================================================
# Moving Average and Momentum Tests
# =============================================================================
def test_sma_calculates_rolling_arithmetic_means() -> None:
    """Verify SMA output starts with the first complete window."""
    result = calculate_sma(
        _decimal_series(1, 2, 3, 4),
        period=2,
    )

    assert result == _decimal_series("1.5", "2.5", "3.5")


def test_ema_uses_initial_sma_then_exponential_smoothing() -> None:
    """Verify EMA initialization and subsequent smoothing."""
    result = calculate_ema(
        _decimal_series(1, 2, 3, 4),
        period=3,
    )

    assert result == _decimal_series(2, 3)


def test_rsi_handles_gain_only_and_balanced_movement() -> None:
    """Verify Wilder RSI handles zero loss without division errors."""
    result = calculate_rsi(
        _decimal_series(1, 2, 3, 2),
        period=2,
    )

    assert result == _decimal_series(100, 50)


def test_macd_aligns_line_signal_and_histogram() -> None:
    """Verify MACD result components share one output alignment."""
    result = calculate_macd(
        _decimal_series(1, 2, 3, 4, 5, 6),
        fast_period=2,
        slow_period=3,
        signal_period=2,
    )

    assert result.macd == _decimal_series("0.5", "0.5", "0.5")
    assert result.signal == _decimal_series("0.5", "0.5", "0.5")
    assert result.histogram == _decimal_series(0, 0, 0)


# =============================================================================
# Volatility and Volume Tests
# =============================================================================
def test_atr_uses_true_range_and_wilder_smoothing() -> None:
    """Verify ATR values are aligned from the first complete period."""
    result = calculate_atr(
        _decimal_series(2, 3, 4),
        _decimal_series(0, 1, 2),
        _decimal_series(1, 2, 3),
        period=2,
    )

    assert result == _decimal_series(2, 2)


def test_bollinger_bands_collapse_for_constant_prices() -> None:
    """Verify zero variance produces identical upper, middle, and lower bands."""
    result = calculate_bollinger_bands(
        _decimal_series(5, 5, 5, 5),
        period=3,
    )

    expected = _decimal_series(5, 5)
    assert result.upper == expected
    assert result.middle == expected
    assert result.lower == expected


def test_obv_tracks_price_direction_and_ignores_unchanged_close() -> None:
    """Verify OBV adds, subtracts, or preserves volume by price direction."""
    result = calculate_obv(
        _decimal_series(10, 11, 10, 10),
        _decimal_series(1, 2, 3, 4),
    )

    assert result == _decimal_series(0, 2, -1, -1)


def test_vwap_uses_cumulative_price_volume() -> None:
    """Verify cumulative VWAP weights later values by volume."""
    result = calculate_vwap(
        _decimal_series(10, 20),
        _decimal_series(10, 20),
        _decimal_series(10, 20),
        _decimal_series(1, 3),
    )

    assert result == _decimal_series(10, "17.5")


def test_vwap_handles_zero_cumulative_volume_gracefully() -> None:
    """Verify VWAP falls back to typical price when volume is zero."""
    zero_volume_result = calculate_vwap(
        _decimal_series(10, 20),
        _decimal_series(10, 20),
        _decimal_series(10, 20),
        _decimal_series(0, 0),
    )
    assert zero_volume_result == _decimal_series(10, 20)

    initial_zero_result = calculate_vwap(
        _decimal_series(10, 20),
        _decimal_series(10, 20),
        _decimal_series(10, 20),
        _decimal_series(0, 5),
    )
    assert initial_zero_result == _decimal_series(10, 20)


# =============================================================================
# Trend and Overlap Tests
# =============================================================================
def test_adx_returns_aligned_directional_components() -> None:
    """Verify ADX and directional indicators are aligned and bounded."""
    highs, lows, closes = _trending_prices(length=8)
    result = calculate_adx(
        highs,
        lows,
        closes,
        period=3,
    )

    assert len(result.adx) == len(result.plus_di) == len(result.minus_di)
    assert result.adx
    assert all(Decimal("0") <= value <= Decimal("100") for value in result.adx)
    assert all(value > Decimal("0") for value in result.plus_di)
    assert all(value == Decimal("0") for value in result.minus_di)


def test_ichimoku_aligns_all_components() -> None:
    """Verify Ichimoku result components begin at the leading-span period."""
    highs, lows, closes = _trending_prices(length=7)
    result = calculate_ichimoku(
        highs,
        lows,
        closes,
        conversion_period=2,
        base_period=3,
        leading_span_period=4,
    )

    expected_length = len(closes) - 4 + 1
    assert len(result.conversion_line) == expected_length
    assert len(result.base_line) == expected_length
    assert len(result.leading_span_a) == expected_length
    assert len(result.leading_span_b) == expected_length
    assert len(result.lagging_span) == expected_length


def test_psar_and_supertrend_preserve_output_alignment() -> None:
    """Verify trend indicators pair every value with a direction flag."""
    highs, lows, closes = _trending_prices(length=6)
    psar = calculate_psar(highs, lows)
    supertrend = calculate_supertrend(
        highs,
        lows,
        closes,
        period=3,
        multiplier=Decimal("2"),
    )

    assert len(psar.values) == len(psar.is_uptrend) == len(closes)
    assert len(supertrend.values) == len(supertrend.is_uptrend) == 4
    assert all(psar.is_uptrend)
    assert all(supertrend.is_uptrend)


# =============================================================================
# Validation Tests
# =============================================================================
@pytest.mark.parametrize(
    "period",
    (0, -1),
)
def test_moving_averages_reject_non_positive_periods(period: int) -> None:
    """Verify moving-average periods must be positive."""
    values = _decimal_series(1, 2, 3)

    with pytest.raises(ValueError, match="period must be greater than zero"):
        calculate_sma(values, period=period)

    with pytest.raises(ValueError, match="period must be greater than zero"):
        calculate_ema(values, period=period)


def test_indicators_reject_misaligned_or_invalid_input() -> None:
    """Verify public indicator boundaries reject unsafe input."""
    atr_highs = _decimal_series(2, 3)
    atr_lows = _decimal_series(1)
    atr_closes = _decimal_series(1, 2)

    with pytest.raises(ValueError, match="equal lengths"):
        calculate_atr(
            atr_highs,
            atr_lows,
            atr_closes,
            period=1,
        )

    obv_closes = _decimal_series(1, 2)
    invalid_volumes = _decimal_series(1, -1)

    with pytest.raises(ValueError, match="must not be negative"):
        calculate_obv(
            obv_closes,
            invalid_volumes,
        )

    vwap_prices = _decimal_series(1)
    negative_volume = _decimal_series(-1)

    with pytest.raises(ValueError, match="must not be negative"):
        calculate_vwap(
            vwap_prices,
            vwap_prices,
            vwap_prices,
            negative_volume,
        )

    macd_values = _decimal_series(1, 2, 3)

    with pytest.raises(ValueError, match="fast period must be less"):
        calculate_macd(
            macd_values,
            fast_period=3,
            slow_period=2,
            signal_period=1,
        )


def test_calculate_choch_fvg_bullish_and_bearish() -> None:
    """Verify CHoCH and FVG calculations detect structure shifts."""
    # 25 bars: baseline ranging
    n = 25
    highs = [Decimal("100") for _ in range(n)]
    lows = [Decimal("90") for _ in range(n)]
    closes = [Decimal("95") for _ in range(n)]
    opens = [Decimal("94") for _ in range(n)]
    volumes = [Decimal("1000") for _ in range(n)]

    # Make a swing low at bar 10: low = 80
    lows[10] = Decimal("80")
    # Make a swing high at bar 12: high = 110
    highs[12] = Decimal("110")

    # Bar 23: Bullish displacement breakout above swing high 110
    opens[23] = Decimal("95")
    closes[23] = Decimal("115")
    highs[23] = Decimal("116")
    lows[23] = Decimal("94")
    volumes[23] = Decimal("3000")

    # Bar 24 (latest): Pullback / retest
    opens[24] = Decimal("115")
    closes[24] = Decimal("112")
    highs[24] = Decimal("115")
    lows[24] = Decimal("111")
    volumes[24] = Decimal("1500")

    result = calculate_choch_fvg(
        high_prices=tuple(highs),
        low_prices=tuple(lows),
        close_prices=tuple(closes),
        open_prices=tuple(opens),
        volumes=tuple(volumes),
        swing_window=3,
        volume_period=10,
    )

    assert result.has_bullish_choch
    assert result.confidence >= Decimal("0.70")
    assert result.last_swing_high == Decimal("110")


def test_calculate_choch_fvg_min_gap_ratio_filter() -> None:
    """Verify microscopic FVG gaps below min_gap_ratio are filtered out."""
    # 25 bars: baseline flat at 100
    n = 25
    highs = [Decimal("100.0") for _ in range(n)]
    lows = [Decimal("98.0") for _ in range(n)]
    closes = [Decimal("99.0") for _ in range(n)]
    opens = [Decimal("99.0") for _ in range(n)]
    volumes = [Decimal("1000") for _ in range(n)]

    # Form a tiny gap at bar 20: low[20] = 100.05 > high[18] = 100.0
    # (gap = 0.05 / 100 = 0.05%)
    highs[18] = Decimal("100.0")
    opens[19] = Decimal("100.02")
    closes[19] = Decimal("100.04")
    highs[19] = Decimal("100.06")
    lows[19] = Decimal("100.01")
    for k in range(20, n):
        lows[k] = Decimal("100.05")
        highs[k] = Decimal("100.10")
        opens[k] = Decimal("100.07")
        closes[k] = Decimal("100.08")

    # With default min_gap_ratio = 0.15% (0.0015), the 0.05% gap should be ignored
    result_filtered = calculate_choch_fvg(
        high_prices=tuple(highs),
        low_prices=tuple(lows),
        close_prices=tuple(closes),
        open_prices=tuple(opens),
        volumes=tuple(volumes),
        swing_window=3,
        volume_period=10,
        min_gap_ratio=Decimal("0.0015"),
    )
    assert not result_filtered.bullish_fvg_active

    # With min_gap_ratio = 0.0, the tiny gap should be detected
    result_unfiltered = calculate_choch_fvg(
        high_prices=tuple(highs),
        low_prices=tuple(lows),
        close_prices=tuple(closes),
        open_prices=tuple(opens),
        volumes=tuple(volumes),
        swing_window=3,
        volume_period=10,
        min_gap_ratio=Decimal("0.0"),
    )
    assert result_unfiltered.bullish_fvg_active

    # Negative min_gap_ratio must raise ValueError
    with pytest.raises(ValueError, match="Minimum gap ratio"):
        calculate_choch_fvg(
            high_prices=tuple(highs),
            low_prices=tuple(lows),
            close_prices=tuple(closes),
            open_prices=tuple(opens),
            volumes=tuple(volumes),
            swing_window=3,
            volume_period=10,
            min_gap_ratio=Decimal("-0.01"),
        )
