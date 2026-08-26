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
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from random import SystemRandom
from time import monotonic
from typing import Final, Protocol

from botragram.app.connectivity import is_transient_connectivity_error
from botragram.enums import LiveFuturesUserDataStatus
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
from botragram.utils.retry import CappedExponentialBackoff

__all__ = [
    "LiveFuturesUserDataService",
]


_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_RECONNECT_DELAY_SECONDS: Final[float] = 1.0
_MAXIMUM_RECONNECT_DELAY_SECONDS: Final[float] = 60.0
_RECONNECT_JITTER_RATIO: Final[float] = 0.2
_OUTAGE_HEARTBEAT_SECONDS: Final[float] = 60.0


def _random_fraction() -> float:
    """Return isolated retry jitter for the private stream owner."""
    return SystemRandom().random()


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
    maximum_reconnect_delay_seconds: float = _MAXIMUM_RECONNECT_DELAY_SECONDS
    reconnect_jitter_ratio: float = _RECONNECT_JITTER_RATIO
    random_source: Callable[[], float] = field(
        default=_random_fraction,
        repr=False,
    )
    clock: Callable[[], float] = field(default=monotonic, repr=False)
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
    _status: LiveFuturesUserDataStatus = field(
        default=LiveFuturesUserDataStatus.STARTING,
        init=False,
        repr=False,
    )
    _outage_started_monotonic: float | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _last_outage_log_monotonic: float | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _next_retry_seconds: float = field(default=0.0, init=False, repr=False)
    _reconnect_backoff: CappedExponentialBackoff | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate bounded reconnect behavior."""
        if self.reconnect_delay_seconds < 0:
            raise ValueError("User Data Stream reconnect delay must not be negative")
        if self.maximum_reconnect_delay_seconds <= 0:
            raise ValueError(
                "Maximum User Data Stream reconnect delay must be positive"
            )
        if (
            self.reconnect_delay_seconds > 0
            and self.maximum_reconnect_delay_seconds < self.reconnect_delay_seconds
        ):
            raise ValueError("Maximum reconnect delay must cover the initial delay")
        if self.reconnect_delay_seconds > 0:
            self._reconnect_backoff = CappedExponentialBackoff(
                initial_delay_seconds=self.reconnect_delay_seconds,
                maximum_delay_seconds=self.maximum_reconnect_delay_seconds,
                jitter_ratio=self.reconnect_jitter_ratio,
                random_source=self.random_source,
            )
        if self.equity_observer is not None:
            normalized_asset = (self.equity_asset or "").strip().upper()
            if not normalized_asset:
                raise ValueError("LIVE equity observer requires a collateral asset")
            self.equity_asset = normalized_asset

    @property
    def status(self) -> LiveFuturesUserDataStatus:
        """Return current private-stream freshness for synchronous health checks."""
        return self._status

    @property
    def outage_duration_seconds(self) -> float:
        """Return current private-stream outage duration without exchange I/O."""
        started = self._outage_started_monotonic
        return 0.0 if started is None else max(0.0, self.clock() - started)

    @property
    def next_retry_seconds(self) -> float:
        """Return the most recently scheduled reconnect delay."""
        return self._next_retry_seconds

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
        reconnect_attempt = 0
        while not self._closed:
            try:
                async for event in self.event_stream.stream_events():
                    if isinstance(event, FuturesUserDataStreamConnected):
                        await self._synchronize_after_connection()
                        reconnect_attempt = 0
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
                is_transient = is_transient_connectivity_error(error)
                if not self._initial_snapshot_complete and not is_transient:
                    await self.cache.mark_stale()
                    self._status = LiveFuturesUserDataStatus.STALE
                    self._fail_initialization(error=error)
                    return

                reconnect_attempt += 1
                await self.cache.mark_resyncing()
                self._status = LiveFuturesUserDataStatus.RESYNCING
                self._next_retry_seconds = self._get_reconnect_delay(
                    attempt=reconnect_attempt
                )
                self._record_outage(error=error, attempt=reconnect_attempt)

            if self._closed:
                return
            await asyncio.sleep(self._next_retry_seconds)

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
        self._status = LiveFuturesUserDataStatus.READY
        self._record_connectivity_recovered()
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

    def _get_reconnect_delay(self, *, attempt: int) -> float:
        """Return one capped reconnect delay while retaining zero-delay tests."""
        backoff = self._reconnect_backoff
        return 0.0 if backoff is None else backoff.get_delay(attempt=attempt)

    def _record_outage(self, *, error: Exception, attempt: int) -> None:
        """Log outage transitions and bounded heartbeats without stack-trace spam."""
        now = self.clock()
        if self._outage_started_monotonic is None:
            self._outage_started_monotonic = now
            self._last_outage_log_monotonic = now
            _LOGGER.warning(
                "Binance Futures User Data Stream unavailable; retrying: "
                "error_type=%s attempt=%d next_retry_seconds=%.3f",
                type(error).__name__,
                attempt,
                self._next_retry_seconds,
            )
            return

        last_log = self._last_outage_log_monotonic
        if last_log is not None and now - last_log < _OUTAGE_HEARTBEAT_SECONDS:
            return
        self._last_outage_log_monotonic = now
        _LOGGER.warning(
            "Binance Futures User Data Stream outage heartbeat: "
            "outage_seconds=%.1f attempt=%d next_retry_seconds=%.3f",
            max(0.0, now - self._outage_started_monotonic),
            attempt,
            self._next_retry_seconds,
        )

    def _record_connectivity_recovered(self) -> None:
        """Clear private-stream outage telemetry after authoritative REST reseed."""
        started = self._outage_started_monotonic
        if started is not None:
            _LOGGER.info(
                "Binance Futures User Data Stream recovered after REST resync: "
                "outage_seconds=%.1f",
                max(0.0, self.clock() - started),
            )
        self._outage_started_monotonic = None
        self._last_outage_log_monotonic = None
        self._next_retry_seconds = 0.0
