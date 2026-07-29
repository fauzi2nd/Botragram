"""
Botragram

Description:
    Parameter validation utility functions.

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
# Utility Functions
# =============================================================================
def validate_positive_decimal(
    value: Decimal,
    name: str = "parameter",
) -> None:
    """Validate that decimal value is strictly positive.

    Args:
        value: Value to validate.
        name: Name of parameter for exception message.

    Raises:
        ValueError: If value is non-positive.
    """
    if value <= Decimal("0"):
        raise ValueError(f"{name} must be greater than zero, got {value}")


def validate_symbol(symbol: str) -> None:
    """Validate format of trading symbol string.

    Args:
        symbol: Symbol string (e.g. BTCUSDT).

    Raises:
        ValueError: If symbol string is empty or invalid.
    """
    if not symbol or not symbol.strip() or "/" in symbol:
        raise ValueError(f"Invalid trading symbol format: '{symbol}'")
