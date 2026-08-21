"""Focused per-position LIVE protection-monitor ownership tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from botragram.enums import Interval, StrategyType
from botragram.models import LiveRuntimePositionContext, Ticker
from botragram.services.live_protection_monitoring_service import (
    LiveProtectionMonitoringService,
    PositionProtectionTickHandler,
)


@dataclass(slots=True)
class FakeProtectionManager:
    """Record symbol-targeted monitoring ticks without exchange mutation."""

    error: BaseException | None = None
    received_prices: list[Decimal] = field(default_factory=list[Decimal])

    async def on_market_tick(self, *, ticker: Ticker) -> None:
        """Record a routed tick or raise the configured isolated failure."""
        if self.error is not None:
            raise self.error
        self.received_prices.append(ticker.last_price)


@dataclass(slots=True)
class FakeManagerFactory:
    """Create one independently observable manager for each runtime context."""

    managers: dict[str, FakeProtectionManager] = field(
        default_factory=dict[str, FakeProtectionManager],
    )

    def __call__(
        self,
        context: LiveRuntimePositionContext,
    ) -> PositionProtectionTickHandler:
        """Construct and retain the manager selected by normalized symbol."""
        manager = FakeProtectionManager()
        self.managers[context.symbol] = manager
        return manager


def _context(*, symbol: str) -> LiveRuntimePositionContext:
    """Create the narrow runtime metadata accepted by monitor ownership."""
    return LiveRuntimePositionContext(
        symbol=symbol,
        interval=Interval.M15,
        strategy_type=StrategyType.EMA_CROSS,
    )


def _ticker(*, symbol: str, price: Decimal) -> Ticker:
    """Create one deterministic market ticker."""
    return Ticker(
        symbol=symbol,
        bid_price=price - Decimal("1"),
        ask_price=price + Decimal("1"),
        last_price=price,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_one_context_is_registered_from_immutable_runtime_metadata() -> None:
    """Verify registration keeps only context metadata, not durable position facts."""
    factory = FakeManagerFactory()
    service = LiveProtectionMonitoringService(manager_factory=factory)
    context = _context(symbol=" btcusdt ")

    assert service.register(context=context)
    assert not service.register(context=_context(symbol="BTCUSDT"))
    assert tuple(state.context for state in service.monitor_states) == (
        _context(symbol="BTCUSDT"),
    )
    assert tuple(factory.managers) == ("BTCUSDT",)


def test_ticks_are_routed_only_to_the_matching_protection_context() -> None:
    """Verify BTC and ETH manager state cannot overwrite each other."""
    asyncio.run(_run_tick_routing_test())


async def _run_tick_routing_test() -> None:
    """Deliver independent BTC, ETH, and unmatched ticks."""
    factory = FakeManagerFactory()
    service = LiveProtectionMonitoringService(manager_factory=factory)
    service.register(context=_context(symbol="BTCUSDT"))
    service.register(context=_context(symbol="ETHUSDT"))

    await service.on_market_tick(ticker=_ticker(symbol="BTCUSDT", price=Decimal("101")))
    await service.on_market_tick(ticker=_ticker(symbol="ETHUSDT", price=Decimal("202")))
    await service.on_market_tick(ticker=_ticker(symbol="SOLUSDT", price=Decimal("303")))

    assert factory.managers["BTCUSDT"].received_prices == [Decimal("101")]
    assert factory.managers["ETHUSDT"].received_prices == [Decimal("202")]


def test_stop_one_preserves_other_monitor_without_touching_exchange_protection() -> (
    None
):
    """Verify monitor removal is runtime-only and leaves ETH ownership intact."""
    factory = FakeManagerFactory()
    service = LiveProtectionMonitoringService(manager_factory=factory)
    service.register(context=_context(symbol="BTCUSDT"))
    service.register(context=_context(symbol="ETHUSDT"))

    assert service.stop(symbol="btcusdt")
    assert [state.context.symbol for state in service.monitor_states] == ["ETHUSDT"]
    assert not service.stop(symbol="BTCUSDT")
    assert tuple(factory.managers) == ("BTCUSDT", "ETHUSDT")
    assert not hasattr(service, "exchange_client")


def test_stop_all_clears_contexts_in_deterministic_symbol_order() -> None:
    """Verify ownership reset does not depend on registration order."""
    factory = FakeManagerFactory()
    service = LiveProtectionMonitoringService(manager_factory=factory)
    service.register(context=_context(symbol="SOLUSDT"))
    service.register(context=_context(symbol="BTCUSDT"))
    service.register(context=_context(symbol="ETHUSDT"))

    assert [state.context.symbol for state in service.monitor_states] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    ]
    service.stop_all()
    assert service.monitor_states == ()


def test_one_manager_failure_is_identity_specific_and_sticky() -> None:
    """Keep BTC unhealthy until explicit runtime-owner reconstruction."""
    asyncio.run(_run_failure_isolation_test())


async def _run_failure_isolation_test() -> None:
    """Fail BTC once and prove later successful ticks cannot erase the failure."""
    factory = FakeManagerFactory()
    service = LiveProtectionMonitoringService(manager_factory=factory)
    service.register(context=_context(symbol="BTCUSDT"))
    service.register(context=_context(symbol="ETHUSDT"))
    factory.managers["BTCUSDT"].error = RuntimeError("configured failure")

    await service.on_market_tick(ticker=_ticker(symbol="BTCUSDT", price=Decimal("101")))
    await service.on_market_tick(ticker=_ticker(symbol="ETHUSDT", price=Decimal("202")))

    states = {state.context.symbol: state for state in service.monitor_states}
    assert states["BTCUSDT"].failure_type == "RuntimeError"
    assert states["ETHUSDT"].failure_type is None
    assert factory.managers["ETHUSDT"].received_prices == [Decimal("202")]

    factory.managers["BTCUSDT"].error = None
    await service.on_market_tick(ticker=_ticker(symbol="BTCUSDT", price=Decimal("103")))
    assert factory.managers["BTCUSDT"].received_prices == []
    states = {state.context.symbol: state for state in service.monitor_states}
    assert states["BTCUSDT"].failure_type == "RuntimeError"

    assert service.stop(symbol="BTCUSDT")
    assert service.register(context=_context(symbol="BTCUSDT"))
    await service.on_market_tick(ticker=_ticker(symbol="BTCUSDT", price=Decimal("104")))
    assert factory.managers["BTCUSDT"].received_prices == [Decimal("104")]
    states = {state.context.symbol: state for state in service.monitor_states}
    assert states["BTCUSDT"].failure_type is None


def test_tick_cancellation_propagates_without_mutating_other_contexts() -> None:
    """Verify owner never converts manager cancellation into a normal failure."""
    asyncio.run(_run_cancellation_test())


async def _run_cancellation_test() -> None:
    """Cancel BTC processing while ETH ownership remains intact."""
    factory = FakeManagerFactory()
    service = LiveProtectionMonitoringService(manager_factory=factory)
    service.register(context=_context(symbol="BTCUSDT"))
    service.register(context=_context(symbol="ETHUSDT"))
    factory.managers["BTCUSDT"].error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.on_market_tick(
            ticker=_ticker(symbol="BTCUSDT", price=Decimal("101"))
        )

    assert [state.context.symbol for state in service.monitor_states] == [
        "BTCUSDT",
        "ETHUSDT",
    ]
