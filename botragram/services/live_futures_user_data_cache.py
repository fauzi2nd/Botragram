"""
Botragram

Description:
    Thread-safe local cache for Binance Futures private account events.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from botragram.models import (
    Account,
    FuturesUserDataAccountUpdate,
    FuturesUserDataEvent,
    FuturesUserDataOrderUpdate,
    FuturesUserDataPositionUpdate,
    Position,
)
from botragram.models.order import Order

__all__ = [
    "LiveFuturesUserDataCache",
    "LiveFuturesUserDataSnapshot",
]


_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_MAXIMUM_RECENT_ORDERS: Final[int] = 100


@dataclass(slots=True, kw_only=True, frozen=True)
class LiveFuturesUserDataSnapshot:
    """Immutable read-only view of cached private Futures account state."""

    balances: tuple[tuple[str, Decimal], ...]
    positions: tuple[Position, ...]
    position_updates: tuple[FuturesUserDataPositionUpdate, ...]
    recent_orders: tuple[Order, ...]


@dataclass(slots=True)
class LiveFuturesUserDataCache:
    """Cache account, position, and order events without exchange polling."""

    _balances: dict[str, Decimal] = field(
        default_factory=dict[str, Decimal], init=False
    )
    _positions: dict[str, Position] = field(
        default_factory=dict[str, Position], init=False
    )
    _position_updates: dict[str, FuturesUserDataPositionUpdate] = field(
        default_factory=dict[str, FuturesUserDataPositionUpdate], init=False
    )
    _recent_orders: deque[Order] = field(
        default_factory=lambda: deque(maxlen=_MAXIMUM_RECENT_ORDERS),
        init=False,
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def initialize(
        self,
        *,
        account: Account,
        positions: Sequence[Position],
    ) -> None:
        """Seed the cache from the authoritative REST startup snapshot."""
        async with self._lock:
            self._balances = {
                balance.asset.upper(): balance.free for balance in account.balances
            }
            self._positions = {
                position.symbol.upper(): position
                for position in positions
                if position.quantity != _DECIMAL_ZERO
            }
            self._position_updates = {
                position.symbol.upper(): FuturesUserDataPositionUpdate(
                    symbol=position.symbol,
                    quantity=position.quantity,
                    entry_price=position.entry_price,
                    unrealized_pnl=position.unrealized_pnl,
                )
                for position in positions
                if position.quantity != _DECIMAL_ZERO
            }
            self._recent_orders.clear()

    async def apply(self, *, event: FuturesUserDataEvent) -> None:
        """Apply one normalized private-stream event to the local cache."""
        async with self._lock:
            match event:
                case FuturesUserDataAccountUpdate():
                    for balance in event.balances:
                        self._balances[balance.asset.upper()] = balance.free
                    for position in event.positions:
                        normalized_symbol = position.symbol.upper()
                        if position.quantity == _DECIMAL_ZERO:
                            self._position_updates.pop(normalized_symbol, None)
                        else:
                            self._position_updates[normalized_symbol] = position
                case FuturesUserDataOrderUpdate():
                    self._recent_orders.append(event.order)

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return the latest streamed free balance for one asset."""
        normalized_asset = asset.strip().upper()
        if not normalized_asset:
            raise ValueError("Balance asset must not be empty")

        async with self._lock:
            return self._balances.get(normalized_asset, _DECIMAL_ZERO)

    async def get_snapshot(self) -> LiveFuturesUserDataSnapshot:
        """Return an immutable local snapshot without exchange I/O."""
        async with self._lock:
            return LiveFuturesUserDataSnapshot(
                balances=tuple(sorted(self._balances.items())),
                positions=tuple(self._positions.values()),
                position_updates=tuple(self._position_updates.values()),
                recent_orders=tuple(self._recent_orders),
            )
