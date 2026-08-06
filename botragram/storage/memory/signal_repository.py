"""
Botragram

Description:
    In-memory trading signal repository implementation.

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
from collections.abc import Sequence
from datetime import datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import SignalType
from botragram.models import Signal
from botragram.repositories import SignalRepository
from botragram.storage.base import BaseMemoryRepository

__all__ = [
    "MemorySignalRepository",
]


# =============================================================================
# Type Aliases
# =============================================================================
type SignalKey = tuple[
    str,
    str,
    datetime,
]


# =============================================================================
# Repository Implementations
# =============================================================================
class MemorySignalRepository(
    BaseMemoryRepository,
    SignalRepository,
):
    """Store generated trading signals in process memory."""

    __slots__ = ("_signals",)

    def __init__(self) -> None:
        """Initialize an empty signal repository."""
        super().__init__()

        self._signals: dict[SignalKey, Signal] = {}

    async def save(
        self,
        *,
        signal: Signal,
    ) -> None:
        """Persist or replace a trading signal."""
        key = self._create_key(signal)

        async with self._lock:
            self._signals[key] = signal

    async def save_many(
        self,
        *,
        signals: Sequence[Signal],
    ) -> None:
        """Persist or replace multiple trading signals."""
        records: dict[SignalKey, Signal] = {
            self._create_key(signal): signal for signal in signals
        }

        async with self._lock:
            self._signals.update(records)

    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> Sequence[Signal]:
        """Return the latest generated signals."""
        self._validate_limit(
            limit,
            label="Signal",
        )

        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )
        normalized_strategy_name = (
            self._normalize_strategy_name(strategy_name)
            if strategy_name is not None
            else None
        )

        async with self._lock:
            signals: list[Signal] = [
                signal
                for signal in self._signals.values()
                if self._matches(
                    signal=signal,
                    symbol=normalized_symbol,
                    signal_type=signal_type,
                    strategy_name=normalized_strategy_name,
                )
            ]

        signals.sort(key=lambda signal: signal.generated_at)

        return tuple(signals[-limit:])

    async def get_between(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> Sequence[Signal]:
        """Return signals generated within an inclusive datetime range."""
        self._validate_time_range(
            start_time=start_time,
            end_time=end_time,
            label="Signal",
        )

        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )
        normalized_strategy_name = (
            self._normalize_strategy_name(strategy_name)
            if strategy_name is not None
            else None
        )

        async with self._lock:
            signals: list[Signal] = [
                signal
                for signal in self._signals.values()
                if (
                    start_time <= signal.generated_at <= end_time
                    and self._matches(
                        signal=signal,
                        symbol=normalized_symbol,
                        signal_type=signal_type,
                        strategy_name=normalized_strategy_name,
                    )
                )
            ]

        signals.sort(key=lambda signal: signal.generated_at)

        return tuple(signals)

    async def get_latest_for_symbol(
        self,
        *,
        symbol: str,
        strategy_name: str | None = None,
    ) -> Signal | None:
        """Return the latest signal for a trading symbol."""
        normalized_symbol = self._normalize_symbol(symbol)
        normalized_strategy_name = (
            self._normalize_strategy_name(strategy_name)
            if strategy_name is not None
            else None
        )

        async with self._lock:
            latest_signal: Signal | None = None

            for signal in self._signals.values():
                if not self._matches(
                    signal=signal,
                    symbol=normalized_symbol,
                    signal_type=None,
                    strategy_name=normalized_strategy_name,
                ):
                    continue

                if (
                    latest_signal is None
                    or signal.generated_at > latest_signal.generated_at
                ):
                    latest_signal = signal

        return latest_signal

    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        """Delete signals older than a datetime boundary."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            keys_to_delete: tuple[SignalKey, ...] = tuple(
                key
                for key, signal in self._signals.items()
                if (
                    signal.generated_at < before
                    and (
                        normalized_symbol is None
                        or signal.symbol.upper() == normalized_symbol
                    )
                )
            )

            for key in keys_to_delete:
                del self._signals[key]

        return len(keys_to_delete)

    async def count(
        self,
        *,
        symbol: str | None = None,
        signal_type: SignalType | None = None,
        strategy_name: str | None = None,
    ) -> int:
        """Count stored trading signals."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )
        normalized_strategy_name = (
            self._normalize_strategy_name(strategy_name)
            if strategy_name is not None
            else None
        )

        async with self._lock:
            return sum(
                1
                for signal in self._signals.values()
                if self._matches(
                    signal=signal,
                    symbol=normalized_symbol,
                    signal_type=signal_type,
                    strategy_name=normalized_strategy_name,
                )
            )

    @classmethod
    def _create_key(
        cls,
        signal: Signal,
    ) -> SignalKey:
        """Create a unique in-memory signal key."""
        return (
            cls._normalize_symbol(signal.symbol),
            cls._normalize_strategy_name(signal.strategy_name),
            signal.generated_at,
        )

    @staticmethod
    def _matches(
        *,
        signal: Signal,
        symbol: str | None,
        signal_type: SignalType | None,
        strategy_name: str | None,
    ) -> bool:
        """Return whether a signal matches optional filters."""
        return (
            (symbol is None or signal.symbol.upper() == symbol)
            and (signal_type is None or signal.signal_type is signal_type)
            and (strategy_name is None or signal.strategy_name == strategy_name)
        )

    @staticmethod
    def _normalize_strategy_name(
        strategy_name: str,
    ) -> str:
        """Normalize and validate a strategy name."""
        normalized_strategy_name = strategy_name.strip()

        if not normalized_strategy_name:
            raise ValueError("Strategy name must not be empty")

        return normalized_strategy_name
