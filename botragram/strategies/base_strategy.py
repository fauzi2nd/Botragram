"""
Botragram

Description:
    Base trading strategy interface.

Python:
    3.14+
"""

from __future__ import annotations


class BaseStrategy:
    """Base contract for trading strategies."""

    async def generate_signal(self) -> str:
        """Generate a signal placeholder."""
        return "hold"
