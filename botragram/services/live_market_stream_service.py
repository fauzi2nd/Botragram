"""
Botragram

Description:
    Independent lifecycle ownership for live market ticker streams.

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
import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from time import monotonic
from typing import Final, Protocol, runtime_checkable

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import LiveMarketStreamLifecycleStatus
from botragram.models import (
    LiveMarketStreamIdentity,
    LiveMarketStreamState,
    LiveRuntimePositionContext,
    Ticker,
)

__all__ = [
    "LiveMarketStreamService",
    "MarketTickListener",
    "MarketTickerSeedProvider",
    "MarketTickerStreamProvider",
    "RuntimeStreamTelemetryRecorder",
]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


# =============================================================================
# Protocols
# =============================================================================
@runtime_checkable
class MarketTickerSeedProvider(Protocol):
    """Provide on-demand latest ticker snapshots for initial stream readiness."""

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return the latest ticker for a trading symbol."""
        ...


class MarketTickerStreamProvider(Protocol):
    """Provide ticker stream subscriptions through the market boundary."""

    def stream_ticker(self, *, symbol: str) -> AsyncIterator[Ticker]:
        """Yield normalized ticker updates for a symbol."""
        ...

    async def unsubscribe(self, *, symbol: str) -> None:
        """Stop active subscriptions for a symbol."""
        ...


class RuntimeStreamTelemetryRecorder(Protocol):
    """Record legacy singular stream telemetry during the compatibility phase."""

    def set_stream_enabled(self, enabled: bool) -> bool:
        """Set whether one legacy stream subscription is active."""
        ...

    def record_stream_tick(self, *, price: Decimal) -> None:
        """Record one validated legacy stream tick."""
        ...


class MarketTickListener(Protocol):
    """Consume validated market ticks without owning stream lifecycle."""

    async def on_market_tick(self, *, ticker: Ticker) -> None:
        """Process one normalized ticker event."""
        ...


# =============================================================================
# Internal Models
# =============================================================================
@dataclass(slots=True)
class _OwnedLiveMarketStream:
    """Keep mutable resources private to one stream owner."""

    first_tick_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    lifecycle_status: LiveMarketStreamLifecycleStatus = (
        LiveMarketStreamLifecycleStatus.NOT_STARTED
    )
    event_count: int = 0
    last_price: Decimal | None = None
    last_event_monotonic: float | None = None
    failure_type: str | None = None


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True)
class LiveMarketStreamService:
    """Own independent ticker streams without activating the trading runtime."""

    market_service: MarketTickerStreamProvider
    runtime_control: RuntimeStreamTelemetryRecorder | None = None
    tick_listeners: tuple[MarketTickListener, ...] = ()
    _owned_streams: dict[LiveMarketStreamIdentity, _OwnedLiveMarketStream] = field(
        default_factory=dict[LiveMarketStreamIdentity, _OwnedLiveMarketStream],
        init=False,
        repr=False,
    )

    @property
    def stream_states(self) -> tuple[LiveMarketStreamState, ...]:
        """Return immutable stream snapshots in deterministic identity order."""
        return tuple(
            self._to_stream_state(identity=identity, owned_stream=owned_stream)
            for identity, owned_stream in self._ordered_owned_streams()
        )

    def get_stream_state(
        self,
        *,
        identity: LiveMarketStreamIdentity,
    ) -> LiveMarketStreamState | None:
        """Return one immutable stream snapshot when the identity is owned.

        Args:
            identity: The stream identity to inspect.

        Returns:
            The stream snapshot, or ``None`` after it has been stopped.
        """
        owned_stream = self._owned_streams.get(identity)

        if owned_stream is None:
            return None

        return self._to_stream_state(
            identity=identity,
            owned_stream=owned_stream,
        )

    async def start(
        self,
        *,
        context: LiveRuntimePositionContext,
    ) -> LiveMarketStreamIdentity:
        """Start one ticker stream unless its identity is already owned.

        Repeated starts are intentionally idempotent.  The original stream
        remains the sole owner until an explicit ``stop`` releases it.

        Args:
            context: The recovered runtime context requiring ticker updates.

        Returns:
            The identity of the existing or newly started stream.
        """
        identity = LiveMarketStreamIdentity.from_runtime_context(context=context)

        if identity in self._owned_streams:
            return identity

        owned_stream = _OwnedLiveMarketStream(
            lifecycle_status=LiveMarketStreamLifecycleStatus.STARTING,
        )
        self._owned_streams[identity] = owned_stream
        owned_stream.task = asyncio.create_task(
            self._consume_stream(identity=identity, owned_stream=owned_stream),
            name=(f"live-market-stream:{identity.symbol}:{identity.interval.value}"),
        )
        self._update_legacy_stream_enabled()
        return identity

    async def wait_for_first_tick(
        self,
        *,
        identity: LiveMarketStreamIdentity,
        timeout_seconds: float,
    ) -> bool:
        """Wait for one stream's first valid ticker event.

        Args:
            identity: The stream identity whose readiness is required.
            timeout_seconds: Positive maximum wait duration.

        Returns:
            Whether this stream received a valid first ticker before timeout.

        Raises:
            ValueError: If the timeout is invalid or the stream is unknown.
            asyncio.CancelledError: If the caller cancels the wait.
        """
        if timeout_seconds <= 0:
            raise ValueError("First-tick timeout must be greater than zero")

        owned_stream = self._require_owned_stream(identity=identity)

        if owned_stream.first_tick_event.is_set():
            return True

        task = owned_stream.task
        if task is None or task.done():
            return False

        first_tick_task = asyncio.create_task(owned_stream.first_tick_event.wait())

        try:
            async with asyncio.timeout(timeout_seconds):
                await asyncio.wait(
                    (first_tick_task, task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
        except TimeoutError:
            if isinstance(self.market_service, MarketTickerSeedProvider):
                try:
                    seed_ticker = await self.market_service.get_ticker(
                        symbol=identity.symbol
                    )
                    if (
                        seed_ticker.last_price > 0
                        and not owned_stream.first_tick_event.is_set()
                    ):
                        owned_stream.last_price = seed_ticker.last_price
                        owned_stream.last_event_monotonic = monotonic()
                        owned_stream.first_tick_event.set()
                        return True
                except Exception:
                    pass
            return owned_stream.first_tick_event.is_set()
        finally:
            if not first_tick_task.done():
                first_tick_task.cancel()
                await asyncio.gather(first_tick_task, return_exceptions=True)

        return owned_stream.first_tick_event.is_set()

    async def stop(self, *, identity: LiveMarketStreamIdentity) -> bool:
        """Stop one owned ticker stream without affecting other identities.

        Args:
            identity: The owned stream identity to stop.

        Returns:
            Whether an owned stream was stopped. Unknown identities are
            intentionally idempotent and return ``False``.
        """
        owned_stream = self._owned_streams.get(identity)

        if owned_stream is None:
            return False

        owned_stream.lifecycle_status = LiveMarketStreamLifecycleStatus.STOPPING
        task = owned_stream.task

        if task is not None and not task.done():
            task.cancel()

        try:
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
        finally:
            try:
                await self.market_service.unsubscribe(symbol=identity.symbol)
            finally:
                self._owned_streams.pop(identity, None)
                self._update_legacy_stream_enabled()

        return True

    async def stop_all(self) -> None:
        """Stop all owned streams in deterministic identity order."""
        identities = tuple(identity for identity, _ in self._ordered_owned_streams())
        first_failure: Exception | None = None

        for identity in identities:
            try:
                await self.stop(identity=identity)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _LOGGER.exception(
                    "Live market stream stop failed: symbol=%s interval=%s",
                    identity.symbol,
                    identity.interval.value,
                )
                if first_failure is None:
                    first_failure = error

        if first_failure is not None:
            raise first_failure

    async def _consume_stream(
        self,
        *,
        identity: LiveMarketStreamIdentity,
        owned_stream: _OwnedLiveMarketStream,
    ) -> None:
        """Consume ticker updates and isolate one stream's failure state."""
        owned_stream.lifecycle_status = LiveMarketStreamLifecycleStatus.RUNNING

        try:
            if isinstance(self.market_service, MarketTickerSeedProvider):
                try:
                    seed_ticker = await self.market_service.get_ticker(
                        symbol=identity.symbol
                    )
                    if (
                        seed_ticker.last_price > 0
                        and not owned_stream.first_tick_event.is_set()
                    ):
                        owned_stream.last_price = seed_ticker.last_price
                        owned_stream.last_event_monotonic = monotonic()
                        owned_stream.first_tick_event.set()
                except Exception:
                    pass

            async for ticker in self.market_service.stream_ticker(
                symbol=identity.symbol
            ):
                if ticker.last_price <= 0:
                    raise ValueError("Stream ticker price must be greater than zero")

                owned_stream.event_count += 1
                owned_stream.last_price = ticker.last_price
                owned_stream.last_event_monotonic = monotonic()
                owned_stream.first_tick_event.set()
                self._record_legacy_tick(price=ticker.last_price)
                await self._notify_tick_listeners(ticker=ticker, identity=identity)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            owned_stream.lifecycle_status = LiveMarketStreamLifecycleStatus.FAILED
            owned_stream.failure_type = type(error).__name__
            _LOGGER.exception(
                "Live market stream failed: symbol=%s interval=%s",
                identity.symbol,
                identity.interval.value,
            )
        else:
            owned_stream.lifecycle_status = LiveMarketStreamLifecycleStatus.FAILED
            owned_stream.failure_type = "StreamEnded"
            _LOGGER.error(
                "Live market stream ended unexpectedly: symbol=%s interval=%s",
                identity.symbol,
                identity.interval.value,
            )
        finally:
            self._update_legacy_stream_enabled()

    def _ordered_owned_streams(
        self,
    ) -> tuple[tuple[LiveMarketStreamIdentity, _OwnedLiveMarketStream], ...]:
        """Return private stream records in deterministic identity order."""
        return tuple(
            sorted(
                self._owned_streams.items(),
                key=lambda item: (item[0].symbol, item[0].interval.value),
            )
        )

    def _require_owned_stream(
        self,
        *,
        identity: LiveMarketStreamIdentity,
    ) -> _OwnedLiveMarketStream:
        """Return an owned stream or reject an unknown identity explicitly."""
        owned_stream = self._owned_streams.get(identity)

        if owned_stream is None:
            raise ValueError(
                "Cannot wait for first tick of an unknown live market stream: "
                f"{identity.symbol}:{identity.interval.value}"
            )

        return owned_stream

    def _update_legacy_stream_enabled(self) -> None:
        """Mirror ownership only when singular telemetry remains unambiguous."""
        runtime_control = self.runtime_control

        if runtime_control is None:
            return

        owned_streams = tuple(self._owned_streams.values())
        is_single_active_stream = len(owned_streams) == 1 and owned_streams[
            0
        ].lifecycle_status in {
            LiveMarketStreamLifecycleStatus.STARTING,
            LiveMarketStreamLifecycleStatus.RUNNING,
        }
        runtime_control.set_stream_enabled(is_single_active_stream)

    def _record_legacy_tick(self, *, price: Decimal) -> None:
        """Mirror a tick once only while exactly one stream is owned."""
        runtime_control = self.runtime_control

        if runtime_control is None or len(self._owned_streams) != 1:
            return

        runtime_control.record_stream_tick(price=price)

    async def _notify_tick_listeners(
        self,
        *,
        ticker: Ticker,
        identity: LiveMarketStreamIdentity,
    ) -> None:
        """Deliver one tick once to existing listeners without owning their state."""
        for listener in self.tick_listeners:
            try:
                await listener.on_market_tick(ticker=ticker)
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception(
                    "Live market stream listener failed: symbol=%s interval=%s "
                    "listener=%s",
                    identity.symbol,
                    identity.interval.value,
                    type(listener).__name__,
                )

    @staticmethod
    def _to_stream_state(
        *,
        identity: LiveMarketStreamIdentity,
        owned_stream: _OwnedLiveMarketStream,
    ) -> LiveMarketStreamState:
        """Build a public immutable snapshot from private mutable ownership."""
        return LiveMarketStreamState(
            identity=identity,
            lifecycle_status=owned_stream.lifecycle_status,
            first_tick_received=owned_stream.first_tick_event.is_set(),
            event_count=owned_stream.event_count,
            last_price=owned_stream.last_price,
            last_event_monotonic=owned_stream.last_event_monotonic,
            failure_type=owned_stream.failure_type,
        )
