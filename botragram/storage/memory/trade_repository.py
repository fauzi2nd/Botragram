"""
Botragram

Description:
    In-memory executed trade repository implementation.

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
from botragram.enums import OrderSide
from botragram.models import Trade
from botragram.repositories import TradeRepository
from botragram.storage.base import BaseMemoryRepository

__all__ = [
    "MemoryTradeRepository",
]


# =============================================================================
# Type Aliases
# =============================================================================
type TradeKey = tuple[str, str]


# =============================================================================
# Repository Implementations
# =============================================================================
class MemoryTradeRepository(
    BaseMemoryRepository,
    TradeRepository,
):
    """Store executed trades in process memory."""

    __slots__ = ("_trades",)

    def __init__(self) -> None:
        """Initialize an empty trade repository."""
        super().__init__()

        self._trades: dict[TradeKey, Trade] = {}

    async def save(
        self,
        *,
        trade: Trade,
    ) -> None:
        """Persist or replace an executed trade."""
        key = self._create_key(trade)

        async with self._lock:
            self._trades[key] = trade

    async def save_many(
        self,
        *,
        trades: Sequence[Trade],
    ) -> None:
        """Persist or replace multiple executed trades."""
        records: dict[TradeKey, Trade] = {
            self._create_key(trade): trade for trade in trades
        }

        async with self._lock:
            self._trades.update(records)

    async def get_by_id(
        self,
        *,
        trade_id: str,
        symbol: str | None = None,
    ) -> Trade | None:
        """Return a trade by identifier."""
        normalized_trade_id = self._normalize_identifier(
            trade_id,
            label="Trade",
        )

        if symbol is not None:
            key: TradeKey = (
                self._normalize_symbol(symbol),
                normalized_trade_id,
            )

            async with self._lock:
                return self._trades.get(key)

        async with self._lock:
            matching_trade: Trade | None = None

            for trade in self._trades.values():
                if trade.trade_id != normalized_trade_id:
                    continue

                if matching_trade is not None:
                    raise RuntimeError(
                        f"Multiple trades use identifier {normalized_trade_id!r}"
                    )

                matching_trade = trade

        return matching_trade

    async def get_by_order_id(
        self,
        *,
        order_id: str,
        symbol: str | None = None,
    ) -> Sequence[Trade]:
        """Return all fills associated with an order."""
        normalized_order_id = self._normalize_identifier(
            order_id,
            label="Order",
        )
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            trades: list[Trade] = [
                trade
                for trade in self._trades.values()
                if (
                    trade.order_id == normalized_order_id
                    and (
                        normalized_symbol is None
                        or trade.symbol.upper() == normalized_symbol
                    )
                )
            ]

        trades.sort(key=lambda trade: trade.executed_at)

        return tuple(trades)

    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        side: OrderSide | None = None,
    ) -> Sequence[Trade]:
        """Return the latest executed trades."""
        self._validate_limit(
            limit,
            label="Trade",
        )

        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            trades: list[Trade] = [
                trade
                for trade in self._trades.values()
                if self._matches(
                    trade=trade,
                    symbol=normalized_symbol,
                    side=side,
                )
            ]

        trades.sort(key=lambda trade: trade.executed_at)

        return tuple(trades[-limit:])

    async def get_between(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        symbol: str | None = None,
        side: OrderSide | None = None,
    ) -> Sequence[Trade]:
        """Return trades executed within an inclusive datetime range."""
        self._validate_time_range(
            start_time=start_time,
            end_time=end_time,
            label="Trade",
        )

        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            trades: list[Trade] = [
                trade
                for trade in self._trades.values()
                if (
                    start_time <= trade.executed_at <= end_time
                    and self._matches(
                        trade=trade,
                        symbol=normalized_symbol,
                        side=side,
                    )
                )
            ]

        trades.sort(key=lambda trade: trade.executed_at)

        return tuple(trades)

    async def delete_before(
        self,
        *,
        before: datetime,
        symbol: str | None = None,
    ) -> int:
        """Delete trades older than a datetime boundary."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            keys_to_delete: tuple[TradeKey, ...] = tuple(
                key
                for key, trade in self._trades.items()
                if (
                    trade.executed_at < before
                    and (
                        normalized_symbol is None
                        or trade.symbol.upper() == normalized_symbol
                    )
                )
            )

            for key in keys_to_delete:
                del self._trades[key]

        return len(keys_to_delete)

    async def count(
        self,
        *,
        symbol: str | None = None,
        side: OrderSide | None = None,
    ) -> int:
        """Count stored executed trades."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        async with self._lock:
            return sum(
                1
                for trade in self._trades.values()
                if self._matches(
                    trade=trade,
                    symbol=normalized_symbol,
                    side=side,
                )
            )

    @classmethod
    def _create_key(
        cls,
        trade: Trade,
    ) -> TradeKey:
        """Create a unique in-memory trade key."""
        return (
            cls._normalize_symbol(trade.symbol),
            cls._normalize_identifier(
                trade.trade_id,
                label="Trade",
            ),
        )

    @staticmethod
    def _matches(
        *,
        trade: Trade,
        symbol: str | None,
        side: OrderSide | None,
    ) -> bool:
        """Return whether a trade matches optional filters."""
        return (symbol is None or trade.symbol.upper() == symbol) and (
            side is None or trade.side is side
        )
