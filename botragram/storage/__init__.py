"""
Botragram

Description:
    Storage implementations package initialization.

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
from botragram.storage.memory import (
    MemoryCandleRepository,
    MemoryOrderRepository,
    MemoryPositionRepository,
    MemorySignalRepository,
    MemoryTradeRepository,
)
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteOrderRepository,
    SQLitePositionRepository,
    SQLiteSignalRepository,
    SQLiteTradeRepository,
)

__all__ = [
    "MemoryCandleRepository",
    "MemoryOrderRepository",
    "MemoryPositionRepository",
    "MemorySignalRepository",
    "MemoryTradeRepository",
    "SQLiteCandleRepository",
    "SQLiteOrderRepository",
    "SQLitePositionRepository",
    "SQLiteSignalRepository",
    "SQLiteTradeRepository",
]
