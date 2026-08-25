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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from botragram.enums import LiveFuturesUserDataStatus, PositionSide
from botragram.models import (
    Account,
    FuturesUserDataAccountUpdate,
    FuturesUserDataAlgoUpdate,
    FuturesUserDataEvent,
    FuturesUserDataOrderUpdate,
    FuturesUserDataPositionUpdate,
    FuturesUserDataStreamConnected,
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

    status: LiveFuturesUserDataStatus
    last_event_at: datetime | None
    last_snapshot_at: datetime | None
    balances: tuple[tuple[str, Decimal], ...]
    positions: tuple[Position, ...]
    position_updates: tuple[FuturesUserDataPositionUpdate, ...]
    recent_orders: tuple[Order, ...]
    recent_algo_updates: tuple[FuturesUserDataAlgoUpdate, ...] = ()


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
    _recent_algo_updates: deque[FuturesUserDataAlgoUpdate] = field(
        default_factory=lambda: deque(maxlen=_MAXIMUM_RECENT_ORDERS),
        init=False,
    )
    _status: LiveFuturesUserDataStatus = field(
        default=LiveFuturesUserDataStatus.STARTING,
        init=False,
    )
    _last_event_at: datetime | None = field(default=None, init=False)
    _last_snapshot_at: datetime | None = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def initialize(
        self,
        *,
        account: Account,
        positions: Sequence[Position],
        clear_recent_orders: bool,
    ) -> None:
        """Seed the cache from one authoritative REST snapshot."""
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
                    quantity=(
                        position.quantity
                        if position.side is PositionSide.LONG
                        else -position.quantity
                    ),
                    entry_price=position.entry_price,
                    unrealized_pnl=position.unrealized_pnl,
                )
                for position in positions
                if position.quantity != _DECIMAL_ZERO
            }
            if clear_recent_orders:
                self._recent_orders.clear()
                self._recent_algo_updates.clear()
            self._last_snapshot_at = datetime.now(UTC)
            self._status = LiveFuturesUserDataStatus.READY

    async def mark_resyncing(self) -> None:
        """Mark the last cached state as being refreshed after a disconnect."""
        await self._set_status(status=LiveFuturesUserDataStatus.RESYNCING)

    async def mark_stale(self) -> None:
        """Mark the cached state stale when authoritative resync fails."""
        await self._set_status(status=LiveFuturesUserDataStatus.STALE)

    async def apply(self, *, event: FuturesUserDataEvent) -> None:
        """Apply one normalized private-stream event to the local cache."""
        async with self._lock:
            match event:
                case FuturesUserDataStreamConnected():
                    return
                case FuturesUserDataAlgoUpdate():
                    self._recent_algo_updates.append(event)
                case FuturesUserDataAccountUpdate():
                    for balance in event.balances:
                        self._balances[balance.asset.upper()] = balance.free
                    for position in event.positions:
                        self._apply_position_update(
                            position=position, observed_at=event.observed_at
                        )
                case FuturesUserDataOrderUpdate():
                    self._recent_orders.append(event.order)
            self._last_event_at = event.observed_at
            self._status = LiveFuturesUserDataStatus.READY

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
                status=self._status,
                last_event_at=self._last_event_at,
                last_snapshot_at=self._last_snapshot_at,
                balances=tuple(sorted(self._balances.items())),
                positions=tuple(self._positions.values()),
                position_updates=tuple(self._position_updates.values()),
                recent_orders=tuple(self._recent_orders),
                recent_algo_updates=tuple(self._recent_algo_updates),
            )

    def _apply_position_update(
        self,
        *,
        position: FuturesUserDataPositionUpdate,
        observed_at: datetime,
    ) -> None:
        """Keep both position views synchronized with one account update."""
        normalized_symbol = position.symbol.upper()
        if position.quantity == _DECIMAL_ZERO:
            self._position_updates.pop(normalized_symbol, None)
            self._positions.pop(normalized_symbol, None)
            return

        self._position_updates[normalized_symbol] = position
        existing_position = self._positions.get(normalized_symbol)
        quantity = abs(position.quantity)
        side = (
            PositionSide.LONG
            if position.quantity > _DECIMAL_ZERO
            else PositionSide.SHORT
        )
        if existing_position is None:
            self._positions[normalized_symbol] = Position(
                symbol=position.symbol,
                side=side,
                quantity=quantity,
                entry_price=position.entry_price,
                current_price=position.entry_price,
                unrealized_pnl=position.unrealized_pnl,
                leverage=1,
                opened_at=observed_at,
                updated_at=observed_at,
            )
            return

        self._positions[normalized_symbol] = replace(
            existing_position,
            side=side,
            quantity=quantity,
            entry_price=position.entry_price,
            unrealized_pnl=position.unrealized_pnl,
            updated_at=observed_at,
        )

    async def _set_status(self, *, status: LiveFuturesUserDataStatus) -> None:
        """Set the observable cache freshness state under the async lock."""
        async with self._lock:
            self._status = status
