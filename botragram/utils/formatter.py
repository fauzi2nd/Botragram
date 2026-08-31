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
