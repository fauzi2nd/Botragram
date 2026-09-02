"""
Botragram

Description:
    Formatting helper functions for UI and messaging.

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

__all__ = [
    "format_currency",
    "format_percentage",
    "format_price",
]


# =============================================================================
# Utility Functions
# =============================================================================
def format_currency(
    amount: Decimal,
    symbol: str = "USDT",
    decimals: int = 2,
    *,
    group_thousands: bool = False,
) -> str:
    """Format decimal amount as currency display string.

    Args:
        amount: Amount to format.
        symbol: Currency symbol or code.
        decimals: Decimal precision count.
        group_thousands: Whether to include thousands separators.

    Returns:
        Formatted currency string.
    """
    separator = "," if group_thousands else ""
    formatted_amount = f"{amount:{separator}.{decimals}f}"
    return f"{formatted_amount} {symbol}"


def format_percentage(
    value: Decimal,
    decimals: int = 2,
    *,
    group_thousands: bool = False,
) -> str:
    """Format decimal value as percentage display string.

    Args:
        value: Percentage value (e.g. 0.052 for 5.2%).
        decimals: Decimal precision count.
        group_thousands: Whether to include thousands separators.

    Returns:
        Formatted percentage string with sign.
    """
    pct = value * Decimal("100")
    sign = "+" if pct > Decimal("0") else ""
    return f"{sign}{pct:.{decimals}f}%"


def format_price(
    price: Decimal,
    symbol: str | None = None,
    *,
    max_decimals: int = 8,
    min_decimals: int = 2,
    group_thousands: bool = False,
) -> str:
    """Format decimal price preserving precision for small and large values.

    Args:
        price: Price amount to format.
        symbol: Optional currency symbol or code (e.g. 'USDT').
        max_decimals: Maximum decimal places to display.
        min_decimals: Minimum decimal places to display for normal numbers.
        group_thousands: Whether to format thousands separators for integer part.

    Returns:
        Formatted price string.
    """
    raw = f"{price:f}"
    if "." in raw:
        integer_part, frac_part = raw.split(".", 1)
        frac_trimmed = frac_part[:max_decimals].rstrip("0")
        if len(frac_trimmed) < min_decimals:
            frac_trimmed = frac_trimmed.ljust(min_decimals, "0")
        if group_thousands and integer_part.lstrip("-").isdigit():
            int_val = int(integer_part)
            formatted_int = f"{int_val:,}"
        else:
            formatted_int = integer_part
        formatted_price = (
            f"{formatted_int}.{frac_trimmed}" if frac_trimmed else formatted_int
        )
    else:
        if group_thousands and raw.lstrip("-").isdigit():
            int_val = int(raw)
            formatted_int = f"{int_val:,}"
        else:
            formatted_int = raw
        if min_decimals > 0:
            formatted_price = f"{formatted_int}.{'0' * min_decimals}"
        else:
            formatted_price = formatted_int

    if symbol:
        return f"{formatted_price} {symbol}"
    return formatted_price
