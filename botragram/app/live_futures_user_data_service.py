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

from botragram.models import Account, FuturesUserDataEvent, Position
from botragram.services.live_futures_user_data_cache import LiveFuturesUserDataCache

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


@dataclass(slots=True)
class LiveFuturesUserDataService:
    """Maintain a REST-seeded, WebSocket-updated private Futures cache."""

    snapshot_provider: FuturesUserDataSnapshotProvider
    event_stream: FuturesUserDataEventStream
    cache: LiveFuturesUserDataCache = field(default_factory=LiveFuturesUserDataCache)
    reconnect_delay_seconds: float = _RECONNECT_DELAY_SECONDS
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        """Validate bounded reconnect behavior."""
        if self.reconnect_delay_seconds < 0:
            raise ValueError("User Data Stream reconnect delay must not be negative")

    async def start(self) -> None:
        """Capture the initial REST state, then begin private event consumption."""
        if self._closed:
            raise RuntimeError("User Data Stream service is closed")
        if self._task is not None:
            return
        await self._refresh_snapshot()
        self._task = asyncio.create_task(
            self._consume_forever(),
            name="botragram-futures-user-data",
        )

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

    async def _consume_forever(self) -> None:
        """Reconnect after stream interruption and resynchronize with REST."""
        while not self._closed:
            try:
                async for event in self.event_stream.stream_events():
                    await self.cache.apply(event=event)
                if self._closed:
                    return
                raise RuntimeError("Binance Futures User Data Stream ended")
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception(
                    "Binance Futures User Data Stream interrupted; resynchronizing"
                )

            if self._closed:
                return
            try:
                await self._refresh_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception(
                    "Binance Futures User Data Stream REST resynchronization failed"
                )
            await asyncio.sleep(self.reconnect_delay_seconds)

    async def _refresh_snapshot(self) -> None:
        """Refresh only after startup or loss of private-stream continuity."""
        account = await self.snapshot_provider.get_account()
        positions = await self.snapshot_provider.get_positions()
        await self.cache.initialize(account=account, positions=positions)
