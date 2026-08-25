"""
Botragram

Description:
    Lifecycle owner for the cached Binance Futures User Data Stream.

Python:
    3.14+
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Protocol

from botragram.models import (
    Account,
    FuturesUserDataAccountUpdate,
    FuturesUserDataEvent,
    FuturesUserDataStreamConnected,
    Position,
)
from botragram.services.live_futures_user_data_cache import (
    LiveFuturesUserDataCache,
    LiveFuturesUserDataSnapshot,
)

__all__ = [
    "LiveFuturesUserDataService",
]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_RECONNECT_DELAY_SECONDS: Final[float] = 1.0


class FuturesUserDataSnapshotProvider(Protocol):
    """Provide authoritative snapshots used at startup and reconnect."""

    async def get_account(self) -> Account:
        """Return the authoritative Futures account snapshot."""
        ...

    async def get_positions(self, *, symbol: str | None = None) -> Sequence[Position]:
        """Return the authoritative Futures position snapshot."""
        ...


class FuturesUserDataEventStream(Protocol):
    """Yield normalized private Futures account events and close cleanly."""

    def stream_events(self) -> AsyncIterator[FuturesUserDataEvent]:
        """Open one private stream session and yield its events."""
        ...

    async def close(self) -> None:
        """Close private stream resources idempotently."""
        ...


class FuturesEquityObserver(Protocol):
    """Persist a newly observed authoritative Futures account equity."""

    async def observe(self, *, equity: Decimal) -> Decimal:
        """Record equity and return the durable high-water value."""
        ...


@dataclass(slots=True)
class LiveFuturesUserDataService:
    """Maintain a REST-seeded, WebSocket-updated private Futures cache."""

    snapshot_provider: FuturesUserDataSnapshotProvider
    event_stream: FuturesUserDataEventStream
    cache: LiveFuturesUserDataCache = field(default_factory=LiveFuturesUserDataCache)
    reconnect_delay_seconds: float = _RECONNECT_DELAY_SECONDS
    equity_asset: str | None = None
    equity_observer: FuturesEquityObserver | None = None
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _initialization: asyncio.Future[None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _initial_snapshot_complete: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate bounded reconnect behavior."""
        if self.reconnect_delay_seconds < 0:
            raise ValueError("User Data Stream reconnect delay must not be negative")
        if self.equity_observer is not None:
            normalized_asset = (self.equity_asset or "").strip().upper()
            if not normalized_asset:
                raise ValueError("LIVE equity observer requires a collateral asset")
            self.equity_asset = normalized_asset

    async def start(self) -> None:
        """Open the stream, seed REST state, then consume buffered events."""
        if self._closed:
            raise RuntimeError("User Data Stream service is closed")
        if self._task is not None:
            return
        initialization = asyncio.get_running_loop().create_future()
        self._initialization = initialization
        self._task = asyncio.create_task(
            self._consume_forever(),
            name="botragram-futures-user-data",
        )
        try:
            await initialization
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """Stop consumption and close the owned stream idempotently."""
        self._closed = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.event_stream.close()

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return the latest streamed balance for TerminalMonitor compatibility."""
        return await self.cache.get_free_balance(asset=asset)

    async def get_equity(self, *, asset: str) -> Decimal:
        """Return fresh realtime Futures equity without REST polling."""
        return await self.cache.get_equity(asset=asset)

    async def get_snapshot(self) -> LiveFuturesUserDataSnapshot:
        """Return cache freshness and account state without exchange I/O."""
        return await self.cache.get_snapshot()

    async def _consume_forever(self) -> None:
        """Reconnect after interruption with socket-first REST synchronization."""
        while not self._closed:
            try:
                async for event in self.event_stream.stream_events():
                    if isinstance(event, FuturesUserDataStreamConnected):
                        await self._synchronize_after_connection()
                        continue
                    await self.cache.apply(event=event)
                    if isinstance(event, FuturesUserDataAccountUpdate):
                        await self._observe_current_equity()
                if self._closed:
                    return
                raise RuntimeError("Binance Futures User Data Stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._fail_initialization(error=error)
                _LOGGER.exception(
                    "Binance Futures User Data Stream interrupted; reconnecting"
                )

            if self._closed:
                return
            await self.cache.mark_resyncing()
            await asyncio.sleep(self.reconnect_delay_seconds)

    async def _synchronize_after_connection(self) -> None:
        """Seed a connected socket before the buffered events are consumed."""
        try:
            await self._refresh_snapshot(
                clear_recent_orders=not self._initial_snapshot_complete,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self.cache.mark_stale()
            self._fail_initialization(error=error)
            raise
        await self._observe_current_equity()
        self._initial_snapshot_complete = True
        initialization = self._initialization
        if initialization is not None and not initialization.done():
            initialization.set_result(None)

    def _fail_initialization(self, *, error: Exception) -> None:
        """Fail startup promptly instead of leaving an unseeded cache running."""
        initialization = self._initialization
        if initialization is not None and not initialization.done():
            initialization.set_exception(error)

    async def _observe_current_equity(self) -> None:
        """Persist a fresh private-stream equity observation when enabled."""
        observer = self.equity_observer
        asset = self.equity_asset
        if observer is None or asset is None:
            return
        try:
            await observer.observe(equity=await self.cache.get_equity(asset=asset))
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Unable to persist LIVE Futures equity high-water mark")

    async def _refresh_snapshot(self, *, clear_recent_orders: bool) -> None:
        """Refresh only after startup or loss of private-stream continuity."""
        account = await self.snapshot_provider.get_account()
        positions = await self.snapshot_provider.get_positions()
        await self.cache.initialize(
            account=account,
            positions=positions,
            clear_recent_orders=clear_recent_orders,
        )
