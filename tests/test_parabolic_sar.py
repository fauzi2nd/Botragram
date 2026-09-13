"""
Botragram

Description:
    Unit tests for Parabolic SAR indicator.

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
from botragram.indicators.trend.sar import (
    ParabolicSARResult,
    calculate_parabolic_sar,
)


def _to_decimal(values: tuple[float, ...]) -> tuple[Decimal, ...]:
    return tuple(Decimal(str(v)) for v in values)


def test_parabolic_sar_trending_bullish_and_bearish() -> None:
    """Test Parabolic SAR over a multi-bar cycle with trend reversal."""
    highs = _to_decimal((10.0, 11.0, 12.0, 13.0, 12.0, 11.0, 10.0))
    lows = _to_decimal((9.0, 10.0, 11.0, 11.5, 10.5, 9.5, 8.5))

    result = calculate_parabolic_sar(highs, lows)

    assert isinstance(result, ParabolicSARResult)
    assert len(result.sar_values) == len(highs)
    assert len(result.is_bullish) == len(highs)

    # First bars should be bullish
    assert result.is_bullish[1] is True
    assert result.sar_values[1] <= lows[1]

    # Later bars flip to bearish as price drops
    assert result.is_bullish[-1] is False
    assert result.sar_values[-1] >= highs[-1]


def test_parabolic_sar_empty_and_single_candle() -> None:
    """Handle empty and single candle sequences safely."""
    empty_res = calculate_parabolic_sar((), ())
    assert empty_res.sar_values == ()
    assert empty_res.is_bullish == ()

    single_high = (Decimal("100"),)
    single_low = (Decimal("90"),)
    single_res = calculate_parabolic_sar(single_high, single_low)
    assert single_res.sar_values == (Decimal("90"),)
    assert single_res.is_bullish == (True,)


def test_parabolic_sar_validation_errors() -> None:
    """Raise ValueError when sequences mismatch or parameters are invalid."""
    with pytest.raises(ValueError, match="does not match lows count"):
        calculate_parabolic_sar((Decimal("10"),), (Decimal("10"), Decimal("20")))

    highs = _to_decimal((10.0, 11.0))
    lows = _to_decimal((9.0, 10.0))

    with pytest.raises(ValueError, match="Invalid acceleration factor"):
        calculate_parabolic_sar(highs, lows, af_start=Decimal("-0.01"))

    with pytest.raises(ValueError, match="Invalid acceleration factor"):
        calculate_parabolic_sar(
            highs, lows, af_start=Decimal("0.25"), af_max=Decimal("0.20")
        )
