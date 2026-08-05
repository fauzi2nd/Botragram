"""
Botragram

Description:
    Trading signal repository interface.

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
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import SignalType
from botragram.models import Signal

__all__ = [
    "SignalRepository",
]


# =============================================================================
# Abstract Repositories
# =============================================================================
class SignalRepository(ABC):
    """Abstract persistence interface for generated trading signals."""

    __slots__ = ()

    @abstractmethod
    async def save(
        self,
        *,
        signal: Signal,
    ) -> None:
        """Persist a trading signal.

        Args:
            signal: Trading signal to persist.
        """

    @abstractmethod
    async def save_many(
        self,
        *,
        signals: Sequence[Signal],
    ) -> None:
        """Persist multiple trading signals.

        Args:
            signals: Trading signals to persist.
        """

    @abstractmethod
    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> Sequence[Signal]:
        """Return the latest generated signals.

        Args:
            limit: Maximum number of signals to return.
            symbol: Optional trading symbol filter.
            signal_type: Optional signal type filter.
            strategy_name: Optional strategy-name filter.

        Returns:
            Matching signals ordered from oldest to newest.
        """

    @abstractmethod
    async def get_between(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> Sequence[Signal]:
        """Return signals generated within a datetime range.

        Args:
            start_time: Inclusive generation-time boundary.
            end_time: Inclusive generation-time boundary.
            symbol: Optional trading symbol filter.
            signal_type: Optional signal type filter.
            strategy_name: Optional strategy-name filter.

        Returns:
            Matching signals ordered from oldest to newest.
        """

    @abstractmethod
    async def get_latest_for_symbol(
        self,
        *,
        symbol: str,
        strategy_name: str | None = None,
    ) -> Signal | None:
        """Return the latest signal for a trading symbol.

        Args:
            symbol: Trading pair symbol.
            strategy_name: Optional strategy-name filter.

        Returns:
            Latest matching signal, or None when none exists.
        """

    @abstractmethod
    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        """Delete signals older than a datetime boundary.

        Args:
            before: Exclusive deletion boundary.
            symbol: Optional trading symbol filter.

        Returns:
            Number of deleted signal records.
        """

    @abstractmethod
    async def count(
        self,
        *,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> int:
        """Count stored trading signals.

        Args:
            symbol: Optional trading symbol filter.
            signal_type: Optional signal type filter.
            strategy_name: Optional strategy-name filter.

        Returns:
            Number of matching signal records.
        """
