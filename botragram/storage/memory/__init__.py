"""
Botragram

Description:
    In-memory storage package initialization.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.storage.memory.candle_repository import (
    MemoryCandleRepository,
)

__all__ = [
    "MemoryCandleRepository",
]
