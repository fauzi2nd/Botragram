"""Focused independent LIVE market-stream ownership tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import FrozenInstanceError, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from botragram.enums import Interval, LiveMarketStreamLifecycleStatus, StrategyType
from botragram.models import (
    LiveMarketStreamIdentity,
    LiveRuntimePositionContext,
    Ticker,
)
from botragram.services.live_market_stream_service import LiveMarketStreamService
from botragram.services.live_protection_monitoring_service import (
    LiveProtectionMonitoringService,
    PositionProtectionTickHandler,
)


@dataclass(slots=True)
class FakeMarketTickerStreamProvider:
    """Provide deterministic event-driven ticker streams for lifecycle tests."""

    _queues: dict[str, asyncio.Queue[Ticker | Exception]] = field(
        default_factory=dict[str, asyncio.Queue[Ticker | Exception]],
    )
    _started: dict[str, asyncio.Event] = field(default_factory=dict[str, asyncio.Event])
    _failed: dict[str, asyncio.Event] = field(default_factory=dict[str, asyncio.Event])
    stream_calls: list[str] = field(default_factory=list[str])
    stream_closed: list[str] = field(default_factory=list[str])
    unsubscribe_calls: list[str] = field(default_factory=list[str])
    unsubscribe_failures: set[str] = field(default_factory=set[str])

    async def stream_ticker(self, *, symbol: str) -> AsyncIterator[Ticker]:
        """Yield queued tickers until cancellation or an injected failure."""
        self.stream_calls.append(symbol)
        self._started_event(symbol=symbol).set()

        try:
            while True:
                item = await self._queue(symbol=symbol).get()
                if isinstance(item, Exception):
                    self._failed_event(symbol=symbol).set()
                    raise item
                yield item
        finally:
            self.stream_closed.append(symbol)

    async def unsubscribe(self, *, symbol: str) -> None:
        """Record deterministic unsubscription ownership."""
        self.unsubscribe_calls.append(symbol)
        if symbol in self.unsubscribe_failures:
            raise RuntimeError(f"test unsubscribe failure for {symbol}")

    async def wait_started(self, *, symbol: str) -> None:
        """Wait until a stream consumer has subscribed."""
        await self._started_event(symbol=symbol).wait()

    async def wait_failed(self, *, symbol: str) -> None:
        """Wait until an injected stream failure has been consumed."""
        await self._failed_event(symbol=symbol).wait()

    def publish(self, *, symbol: str, price: Decimal) -> None:
        """Deliver one ticker to exactly one owned stream."""
        self._queue(symbol=symbol).put_nowait(_ticker(symbol=symbol, price=price))

    def fail(self, *, symbol: str) -> None:
        """Inject one deterministic consumer failure for a stream."""
        self._queue(symbol=symbol).put_nowait(RuntimeError("test stream failure"))

    def _queue(self, *, symbol: str) -> asyncio.Queue[Ticker | Exception]:
        """Return one symbol's private event queue."""
        return self._queues.setdefault(symbol, asyncio.Queue())

    def _started_event(self, *, symbol: str) -> asyncio.Event:
        """Return one symbol's subscription event."""
        return self._started.setdefault(symbol, asyncio.Event())

    def _failed_event(self, *, symbol: str) -> asyncio.Event:
        """Return one symbol's failure event."""
        return self._failed.setdefault(symbol, asyncio.Event())


@dataclass(slots=True)
class FakeLegacyStreamTelemetry:
    """Capture compatibility telemetry without choosing a multi-stream identity."""

    enabled: bool = False
    prices: list[Decimal] = field(default_factory=list[Decimal])

    def set_stream_enabled(self, enabled: bool) -> bool:
        """Record whether singular compatibility telemetry is active."""
        changed = self.enabled is not enabled
        self.enabled = enabled
        return changed

    def record_stream_tick(self, *, price: Decimal) -> None:
        """Record one singular compatibility ticker price."""
        self.prices.append(price)


@dataclass(slots=True)
class RecordingProtectionManager:
    """Count exactly the market ticks routed to one protection context."""

    tick_count: int = 0

    async def on_market_tick(self, *, ticker: Ticker) -> None:
        """Record one routed protection tick."""
        del ticker
        self.tick_count += 1


@dataclass(slots=True)
class RecordingProtectionManagerFactory:
    """Build independent observable managers for the production owner boundary."""

    managers: dict[str, RecordingProtectionManager] = field(
        default_factory=dict[str, RecordingProtectionManager],
    )

    def __call__(
        self,
        context: LiveRuntimePositionContext,
    ) -> PositionProtectionTickHandler:
        """Create a manager for one normalized runtime context."""
        manager = RecordingProtectionManager()
        self.managers[context.symbol] = manager
        return manager


def _context(
    *, symbol: str, interval: Interval = Interval.M15
) -> LiveRuntimePositionContext:
    """Build a valid recovered runtime context for one ticker stream."""
    return LiveRuntimePositionContext(
        symbol=symbol,
        interval=interval,
        strategy_type=StrategyType.EMA_CROSS,
    )


def _ticker(*, symbol: str, price: Decimal) -> Ticker:
    """Build one normalized ticker event."""
    return Ticker(
        symbol=symbol,
        bid_price=price - Decimal("1"),
        ask_price=price + Decimal("1"),
        last_price=price,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_stream_identity_is_normalized_hashable_and_interval_specific() -> None:
    """Verify identity is an immutable subscription key, not position selection."""
    btc_m15 = LiveMarketStreamIdentity(symbol=" btcusdt ", interval=Interval.M15)
    same_btc_m15 = LiveMarketStreamIdentity(symbol="BTCUSDT", interval=Interval.M15)

    assert btc_m15.symbol == "BTCUSDT"
    assert btc_m15.interval is Interval.M15
    assert btc_m15 == same_btc_m15
    assert hash(btc_m15) == hash(same_btc_m15)
    assert btc_m15 != LiveMarketStreamIdentity(symbol="BTCUSDT", interval=Interval.H1)
    assert btc_m15 != LiveMarketStreamIdentity(symbol="ETHUSDT", interval=Interval.M15)


def test_stream_state_is_immutable_and_hides_owner_resources() -> None:
    """Verify callers receive only immutable observational stream snapshots."""
    asyncio.run(_run_state_immutability_test())


async def _run_state_immutability_test() -> None:
    """Start a stream and inspect the public snapshot boundary."""
    provider = FakeMarketTickerStreamProvider()
    service = LiveMarketStreamService(market_service=provider)
    identity = await service.start(context=_context(symbol="BTCUSDT"))
    await provider.wait_started(symbol="BTCUSDT")
    state = service.get_stream_state(identity=identity)

    assert state is not None
    with pytest.raises(FrozenInstanceError):
        state.__setattr__("event_count", 5)
    assert not hasattr(state, "task")
    assert not hasattr(state, "first_tick_event")

    await service.stop_all()


def test_start_one_and_duplicate_start_use_one_subscription() -> None:
    """Verify duplicate start is idempotent and retains one owned task."""
    asyncio.run(_run_start_one_and_duplicate_start_test())


def test_one_production_protection_listener_routes_each_tick_once() -> None:
    """Verify telemetry and the monitor owner each receive one BTC tick once."""
    asyncio.run(_run_single_protection_listener_test())


async def _run_single_protection_listener_test() -> None:
    """Run a singular stream through the monitor ownership listener boundary."""
    provider = FakeMarketTickerStreamProvider()
    telemetry = FakeLegacyStreamTelemetry()
    factory = RecordingProtectionManagerFactory()
    monitoring_service = LiveProtectionMonitoringService(manager_factory=factory)
    context = _context(symbol="BTCUSDT")
    assert monitoring_service.register(context=context)
    service = LiveMarketStreamService(
        market_service=provider,
        runtime_control=telemetry,
        tick_listeners=(monitoring_service,),
    )

    await service.start(context=context)
    await provider.wait_started(symbol="BTCUSDT")
    provider.publish(symbol="BTCUSDT", price=Decimal("65000"))
    identity = LiveMarketStreamIdentity.from_runtime_context(context=context)
    assert await service.wait_for_first_tick(identity=identity, timeout_seconds=0.1)

    assert telemetry.prices == [Decimal("65000")]
    assert factory.managers["BTCUSDT"].tick_count == 1

    await service.stop_all()


async def _run_start_one_and_duplicate_start_test() -> None:
    """Start BTC twice without creating another subscription."""
    provider = FakeMarketTickerStreamProvider()
    service = LiveMarketStreamService(market_service=provider)
    context = _context(symbol="BTCUSDT")
    identity = await service.start(context=context)
    await provider.wait_started(symbol="BTCUSDT")

    assert await service.start(context=context) == identity
    assert provider.stream_calls == ["BTCUSDT"]
    assert service.stream_states[0].lifecycle_status is (
        LiveMarketStreamLifecycleStatus.RUNNING
    )
    assert not service.stream_states[0].first_tick_received

    await service.stop_all()


def test_two_streams_keep_tick_state_and_first_tick_readiness_isolated() -> None:
    """Verify BTC and ETH telemetry never cross stream identity boundaries."""
    asyncio.run(_run_two_stream_isolation_test())


async def _run_two_stream_isolation_test() -> None:
    """Deliver ticks to BTC then ETH through separate owned streams."""
    provider = FakeMarketTickerStreamProvider()
    service = LiveMarketStreamService(market_service=provider)
    btc = await service.start(context=_context(symbol="BTCUSDT"))
    eth = await service.start(context=_context(symbol="ETHUSDT", interval=Interval.H1))
    await provider.wait_started(symbol="BTCUSDT")
    await provider.wait_started(symbol="ETHUSDT")

    assert tuple(state.identity for state in service.stream_states) == (btc, eth)
    provider.publish(symbol="BTCUSDT", price=Decimal("101"))
    assert await service.wait_for_first_tick(identity=btc, timeout_seconds=1.0)

    btc_state = service.get_stream_state(identity=btc)
    eth_state = service.get_stream_state(identity=eth)
    assert btc_state is not None and eth_state is not None
    assert btc_state.first_tick_received
    assert btc_state.event_count == 1
    assert btc_state.last_price == Decimal("101")
    assert not eth_state.first_tick_received
    assert eth_state.event_count == 0
    assert eth_state.last_price is None

    provider.publish(symbol="ETHUSDT", price=Decimal("202"))
    assert await service.wait_for_first_tick(identity=eth, timeout_seconds=1.0)
    eth_state = service.get_stream_state(identity=eth)
    assert eth_state is not None
    assert eth_state.last_price == Decimal("202")

    await service.stop_all()


def test_multiple_streams_do_not_write_ambiguous_legacy_telemetry() -> None:
    """Verify BTC and ETH stay per-stream without a singular telemetry fallback."""
    asyncio.run(_run_multi_stream_telemetry_test())


async def _run_multi_stream_telemetry_test() -> None:
    """Publish distinct BTC and ETH ticks under multi-stream ownership."""
    provider = FakeMarketTickerStreamProvider()
    legacy_telemetry = FakeLegacyStreamTelemetry()
    service = LiveMarketStreamService(
        market_service=provider,
        runtime_control=legacy_telemetry,
    )
    btc = await service.start(context=_context(symbol="BTCUSDT"))
    eth = await service.start(context=_context(symbol="ETHUSDT"))
    await provider.wait_started(symbol="BTCUSDT")
    await provider.wait_started(symbol="ETHUSDT")

    provider.publish(symbol="BTCUSDT", price=Decimal("101"))
    provider.publish(symbol="ETHUSDT", price=Decimal("202"))
    assert await service.wait_for_first_tick(identity=btc, timeout_seconds=1.0)
    assert await service.wait_for_first_tick(identity=eth, timeout_seconds=1.0)

    btc_state = service.get_stream_state(identity=btc)
    eth_state = service.get_stream_state(identity=eth)
    assert btc_state is not None and eth_state is not None
    assert btc_state.last_price == Decimal("101")
    assert eth_state.last_price == Decimal("202")
    assert not legacy_telemetry.enabled
    assert legacy_telemetry.prices == []

    await service.stop_all()


def test_first_tick_wait_is_identity_specific_and_cancellation_propagates() -> None:
    """Verify ETH cannot satisfy BTC readiness and wait cancellation is preserved."""
    asyncio.run(_run_first_tick_wait_test())


async def _run_first_tick_wait_test() -> None:
    """Exercise identity-specific readiness and cancellation without sleeps."""
    provider = FakeMarketTickerStreamProvider()
    service = LiveMarketStreamService(market_service=provider)
    btc = await service.start(context=_context(symbol="BTCUSDT"))
    eth = await service.start(context=_context(symbol="ETHUSDT"))
    await provider.wait_started(symbol="BTCUSDT")
    await provider.wait_started(symbol="ETHUSDT")

    btc_wait = asyncio.create_task(
        service.wait_for_first_tick(identity=btc, timeout_seconds=1.0),
    )
    await asyncio.sleep(0)
    provider.publish(symbol="ETHUSDT", price=Decimal("202"))
    assert await service.wait_for_first_tick(identity=eth, timeout_seconds=1.0)
    assert not btc_wait.done()
    provider.publish(symbol="BTCUSDT", price=Decimal("101"))
    assert await btc_wait

    xrp = await service.start(context=_context(symbol="XRPUSDT"))
    await provider.wait_started(symbol="XRPUSDT")
    cancelled_wait = asyncio.create_task(
        service.wait_for_first_tick(identity=xrp, timeout_seconds=1.0),
    )
    await asyncio.sleep(0)
    cancelled_wait.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_wait

    await service.stop_all()


def test_stop_one_preserves_other_owned_stream_state() -> None:
    """Verify stopping BTC neither unsubscribes nor resets ETH."""
    asyncio.run(_run_stop_one_test())


async def _run_stop_one_test() -> None:
    """Stop one of two independently owned streams."""
    provider = FakeMarketTickerStreamProvider()
    service = LiveMarketStreamService(market_service=provider)
    btc = await service.start(context=_context(symbol="BTCUSDT"))
    eth = await service.start(context=_context(symbol="ETHUSDT"))
    await provider.wait_started(symbol="BTCUSDT")
    await provider.wait_started(symbol="ETHUSDT")

    assert await service.stop(identity=btc)
    assert service.get_stream_state(identity=btc) is None
    assert service.get_stream_state(identity=eth) is not None
    assert provider.stream_closed == ["BTCUSDT"]
    assert provider.unsubscribe_calls == ["BTCUSDT"]
    assert not await service.stop(identity=btc)

    await service.stop_all()


def test_stop_all_is_deterministic_and_cleans_every_owned_stream() -> None:
    """Verify shutdown orders independent cleanup by stream identity."""
    asyncio.run(_run_stop_all_test())


async def _run_stop_all_test() -> None:
    """Start in scrambled order then stop every owned stream sequentially."""
    provider = FakeMarketTickerStreamProvider()
    service = LiveMarketStreamService(market_service=provider)
    await service.start(context=_context(symbol="ETHUSDT"))
    await service.start(context=_context(symbol="BTCUSDT", interval=Interval.H1))
    await service.start(context=_context(symbol="BTCUSDT", interval=Interval.M15))
    await provider.wait_started(symbol="ETHUSDT")
    await provider.wait_started(symbol="BTCUSDT")

    await service.stop_all()

    assert service.stream_states == ()
    assert provider.unsubscribe_calls == ["BTCUSDT", "BTCUSDT", "ETHUSDT"]
    assert provider.stream_closed == ["BTCUSDT", "BTCUSDT", "ETHUSDT"]


def test_stop_all_continues_cleanup_after_one_unsubscribe_failure() -> None:
    """Verify one cleanup failure does not leave later streams owned."""
    asyncio.run(_run_stop_all_failure_test())


async def _run_stop_all_failure_test() -> None:
    """Exercise sequential cleanup and first-failure propagation."""
    provider = FakeMarketTickerStreamProvider(unsubscribe_failures={"BTCUSDT"})
    service = LiveMarketStreamService(market_service=provider)
    await service.start(context=_context(symbol="ETHUSDT"))
    await service.start(context=_context(symbol="BTCUSDT"))
    await provider.wait_started(symbol="ETHUSDT")
    await provider.wait_started(symbol="BTCUSDT")

    with pytest.raises(RuntimeError, match="BTCUSDT"):
        await service.stop_all()

    assert service.stream_states == ()
    assert provider.unsubscribe_calls == ["BTCUSDT", "ETHUSDT"]
    assert provider.stream_closed == ["BTCUSDT", "ETHUSDT"]


def test_one_stream_failure_is_visible_without_stopping_other_streams() -> None:
    """Verify task failure remains identity-specific and is observable."""
    asyncio.run(_run_stream_failure_test())


async def _run_stream_failure_test() -> None:
    """Fail BTC while ETH remains independently running."""
    provider = FakeMarketTickerStreamProvider()
    service = LiveMarketStreamService(market_service=provider)
    btc = await service.start(context=_context(symbol="BTCUSDT"))
    eth = await service.start(context=_context(symbol="ETHUSDT"))
    await provider.wait_started(symbol="BTCUSDT")
    await provider.wait_started(symbol="ETHUSDT")

    provider.fail(symbol="BTCUSDT")
    await provider.wait_failed(symbol="BTCUSDT")
    await asyncio.sleep(0)

    btc_state = service.get_stream_state(identity=btc)
    eth_state = service.get_stream_state(identity=eth)
    assert btc_state is not None and eth_state is not None
    assert btc_state.lifecycle_status is LiveMarketStreamLifecycleStatus.FAILED
    assert btc_state.failure_type == "RuntimeError"
    assert eth_state.lifecycle_status is LiveMarketStreamLifecycleStatus.RUNNING
    assert provider.unsubscribe_calls == []
    assert not await service.wait_for_first_tick(identity=btc, timeout_seconds=1.0)

    await service.stop_all()
