"""
Botragram

Description:
    Executable bid/ask market quote model.

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
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

__all__ = [
    "ExecutableQuote",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class ExecutableQuote:
    """Immutable exchange-provided bid/ask reference for a MARKET entry."""

    symbol: str
    bid_price: Decimal
    ask_price: Decimal
    timestamp: datetime

    def __post_init__(self) -> None:
        """Require exchange quote provenance to carry an aware timestamp."""
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("Executable quote timestamp must be timezone-aware")
