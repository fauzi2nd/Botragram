"""
Botragram

Description:
    Storage-neutral maintenance contract for candle retention.

Python:
    3.14+
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["CandleStorageOptimizer"]


class CandleStorageOptimizer(Protocol):
    """Optimize storage after a successful candle retention prune."""

    async def optimize_after_prune(self) -> None:
        """Run optional backend maintenance after deleting expired candles."""
        ...
