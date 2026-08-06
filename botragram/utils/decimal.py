"""
Botragram

Description:
    High-precision decimal utilities for trading calculations.

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
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal


# =============================================================================
# Private Helper Functions
# =============================================================================
def _get_precision(decimal_val: Decimal) -> int:
    """Get number of decimal places for a Decimal value.

    Args:
        decimal_val: Decimal value to inspect.

    Returns:
        Number of decimal places as integer.
    """
    exponent = decimal_val.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < 0:
        return abs(exponent)
    return 0


# =============================================================================
# Public Utility Functions
# =============================================================================
def to_decimal(value: int | float | str | Decimal) -> Decimal:
    """Convert input value to high-precision Decimal.

    Args:
        value: Input value as int, float, str, or Decimal.

    Returns:
        Decimal representation of value.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_step_size(
    quantity: Decimal,
    step_size: Decimal,
) -> Decimal:
    """Round quantity down to match exchange step size precision.

    Args:
        quantity: Raw order quantity.
        step_size: Exchange minimum step size increment.

    Returns:
        Rounded Decimal quantity compliant with step size.
    """
    if step_size <= Decimal("0"):
        return quantity
    precision = _get_precision(step_size)
    quotient = (quantity / step_size).quantize(Decimal("1"), rounding=ROUND_DOWN)
    rounded = quotient * step_size
    return rounded.quantize(Decimal(f"1e-{precision}"), rounding=ROUND_DOWN)


def round_price_precision(
    price: Decimal,
    tick_size: Decimal,
) -> Decimal:
    """Round price to match exchange tick size precision.

    Args:
        price: Raw order price.
        tick_size: Exchange tick size increment.

    Returns:
        Rounded Decimal price compliant with tick size.
    """
    if tick_size <= Decimal("0"):
        return price
    precision = _get_precision(tick_size)
    quotient = (price / tick_size).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    rounded = quotient * tick_size
    return rounded.quantize(Decimal(f"1e-{precision}"), rounding=ROUND_HALF_UP)
