"""
Trading Bot

Module:
    core.constants

Description:
    Shared constants used throughout the trading bot.

Python:
    3.14
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal

__all__ = [
    "DEFAULT_ENCODING",
    "DEFAULT_TIMEZONE",
    "ZERO",
    "ONE",
    "HUNDRED",
]

# =============================================================================
# General
# =============================================================================

DEFAULT_ENCODING = "utf-8"

DEFAULT_TIMEZONE = UTC

# =============================================================================
# Decimal
# =============================================================================

ZERO = Decimal("0")

ONE = Decimal("1")

HUNDRED = Decimal("100")