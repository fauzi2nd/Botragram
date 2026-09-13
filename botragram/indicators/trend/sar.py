"""
Botragram

Description:
    Parabolic SAR (Stop and Reverse) indicator.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

__all__ = [
    "ParabolicSARResult",
    "calculate_parabolic_sar",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DEFAULT_AF_START: Final[Decimal] = Decimal("0.02")
_DEFAULT_AF_STEP: Final[Decimal] = Decimal("0.02")
_DEFAULT_AF_MAX: Final[Decimal] = Decimal("0.20")


# =============================================================================
# Result Models
# =============================================================================
@dataclass(
    slots=True,
    frozen=True,
)
class ParabolicSARResult:
    """Calculated Parabolic SAR values and trend states."""

    sar_values: tuple[Decimal, ...]
    is_bullish: tuple[bool, ...]


# =============================================================================
# Indicator Functions
# =============================================================================
def calculate_parabolic_sar(
    highs: Sequence[Decimal],
    lows: Sequence[Decimal],
    *,
    af_start: Decimal = _DEFAULT_AF_START,
    af_step: Decimal = _DEFAULT_AF_STEP,
    af_max: Decimal = _DEFAULT_AF_MAX,
) -> ParabolicSARResult:
    """Calculate Wilder's Parabolic SAR deterministically using Decimal arithmetic.

    Args:
        highs: Sequence of high prices.
        lows: Sequence of low prices.
        af_start: Initial acceleration factor (default 0.02).
        af_step: Acceleration factor increment step (default 0.02).
        af_max: Maximum acceleration factor ceiling (default 0.20).

    Returns:
        ParabolicSARResult with tuple of SAR values and boolean trend indicators.

    Raises:
        ValueError: If highs and lows length mismatch or parameters are invalid.
    """
    if len(highs) != len(lows):
        raise ValueError(
            f"Highs count ({len(highs)}) does not match lows count ({len(lows)})"
        )
    if af_start <= _DECIMAL_ZERO or af_step <= _DECIMAL_ZERO or af_max < af_start:
        raise ValueError("Invalid acceleration factor parameters for Parabolic SAR")

    count = len(highs)
    if count == 0:
        return ParabolicSARResult(sar_values=(), is_bullish=())

    if count == 1:
        return ParabolicSARResult(
            sar_values=(lows[0],),
            is_bullish=(True,),
        )

    # Initial trend determination between bar 0 and bar 1
    is_bull = highs[1] >= highs[0]
    if is_bull:
        sar = min(lows[0], lows[1])
        ep = max(highs[0], highs[1])
    else:
        sar = max(highs[0], highs[1])
        ep = min(lows[0], lows[1])

    af = af_start

    sar_values: list[Decimal] = [sar]
    is_bullish: list[bool] = [is_bull]

    for i in range(1, count):
        next_sar = sar + (af * (ep - sar))

        if is_bull:
            bound = min(lows[i - 1], lows[i - 2]) if i >= 2 else lows[i - 1]
            if next_sar > bound:
                next_sar = bound

            if lows[i] < next_sar:
                # Reversal to bearish
                is_bull = False
                sar = ep
                ep = lows[i]
                af = af_start
            else:
                sar = next_sar
                if highs[i] > ep:
                    ep = highs[i]
                    af = min(af + af_step, af_max)
        else:
            bound = max(highs[i - 1], highs[i - 2]) if i >= 2 else highs[i - 1]
            if next_sar < bound:
                next_sar = bound

            if highs[i] > next_sar:
                # Reversal to bullish
                is_bull = True
                sar = ep
                ep = highs[i]
                af = af_start
            else:
                sar = next_sar
                if lows[i] < ep:
                    ep = lows[i]
                    af = min(af + af_step, af_max)

        sar_values.append(sar)
        is_bullish.append(is_bull)

    return ParabolicSARResult(
        sar_values=tuple(sar_values),
        is_bullish=tuple(is_bullish),
    )
