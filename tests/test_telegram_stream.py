"""Telegram market-stream lifecycle tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast

import pytest

from botragram.enums import Interval, StrategyType
from botragram.models import LiveRuntimePositionContext, Ticker
from botragram.repositories import (
    OrderRepository,
    PositionRepository,
    TradeRepository,
)
from botragram.services.live_market_stream_service import LiveMarketStreamService
from botragram.telegram.query_service import TelegramQueryService


@dataclass(slots=True)
class FakeStreamMarketService:
    """Yield one ticker and remain subscribed until cancelled."""

    ticker_published: asyncio.Event = field(default_factory=asyncio.Event)
    trading_symbol_calls: int = 0
    stream_calls: list[str] = field(default_factory=list[str])
    unsubscribe_calls: list[str] = field(default_factory=list[str])

    @property
    def is_stream_connected(self) -> bool:
        """Return a ready test transport."""
        return True

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return a deterministic fallback ticker."""
        return _create_ticker(symbol=symbol, price=Decimal("99"))

    async def get_trading_symbols(self, *, quote_asset: str) -> tuple[str, ...]:
        """Return deterministic active symbols for query caching."""
        assert quote_asset == "USDT"
        self.trading_symbol_calls += 1
        return ("BTCUSDT", "ETHUSDT")

    async def stream_ticker(self, *, symbol: str) -> AsyncIterator[Ticker]:
        """Yield one streamed ticker and wait indefinitely."""
        self.stream_calls.append(symbol)
        yield _create_ticker(symbol=symbol, price=Decimal("101"))
        self.ticker_published.set()
        await asyncio.Event().wait()

    async def unsubscribe(self, *, symbol: str) -> None:
        """Record stream cleanup."""
        self.unsubscribe_calls.append(symbol)


@dataclass(slots=True)
class FakeRuntimeStreamControl:
    """Expose selected symbol and capture subscription state."""

    symbol: str = "BTCUSDT"
    interval: Interval = Interval.M15
    strategy_type: StrategyType = StrategyType.EMA_CROSS
    stream_enabled: bool = False
    stream_prices: list[Decimal] = field(default_factory=list[Decimal])

    def set_stream_enabled(self, enabled: bool) -> bool:
        """Store subscription state and return whether it changed."""
        changed = self.stream_enabled is not enabled
        self.stream_enabled = enabled
        return changed

    def record_stream_tick(self, *, price: Decimal) -> None:
        """Record one streamed ticker price."""
        self.stream_prices.append(price)


@dataclass(slots=True)
class FakeTickListener:
    """Record delegated ticker delivery without owning the stream."""

    prices: list[Decimal] = field(default_factory=list[Decimal])

    async def on_market_tick(self, *, ticker: Ticker) -> None:
        """Record the exact ticker price once."""
        self.prices.append(ticker.last_price)


@dataclass(slots=True)
class FakePaperBalanceProvider:
    """Satisfy query service construction and record portfolio access."""

    calls: int = 0

    async def get_available_balance(self) -> Decimal:
        """Return a deterministic paper balance."""
        self.calls += 1
        return Decimal("10000")


@dataclass(slots=True)
class FakeLiveBalanceProvider:
    """Return deterministic LIVE balance without paper reconstruction."""

    balance: Decimal
    calls: int = 0

    async def get_free_balance(self, *, asset: str) -> Decimal:
        """Return the configured LIVE balance."""
        assert asset == "USDT"
        self.calls += 1
        return self.balance


def _create_ticker(*, symbol: str, price: Decimal) -> Ticker:
    """Create one deterministic market ticker."""
    return Ticker(
        symbol=symbol,
        bid_price=price - Decimal("1"),
        ask_price=price + Decimal("1"),
        last_price=price,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_telegram_query_service_uses_live_balance_provider() -> None:
    """Keep LIVE status balance reads out of PaperTradingService."""
    asyncio.run(_run_live_balance_provider_test())


async def _run_live_balance_provider_test() -> None:
    """Read LIVE free balance without reconstructing a paper portfolio."""
    market_service = FakeStreamMarketService()
    runtime_control = FakeRuntimeStreamControl()
    stream_owner = LiveMarketStreamService(
        market_service=market_service,
        runtime_control=runtime_control,
    )
    unused_repository = object()
    paper_balance = FakePaperBalanceProvider()
    live_balance = FakeLiveBalanceProvider(balance=Decimal("321.50"))
    service = TelegramQueryService(
        symbol="BTCUSDT",
        market_service=market_service,
        paper_trading_service=paper_balance,
        live_balance_provider=live_balance,
        position_repository=cast(PositionRepository, unused_repository),
        trade_repository=cast(TradeRepository, unused_repository),
        order_repository=cast(OrderRepository, unused_repository),
        market_stream_service=stream_owner,
        runtime_control=runtime_control,
    )

    assert await service.get_available_balance() == Decimal("321.50")
    assert live_balance.calls == 1
    assert paper_balance.calls == 0


def test_telegram_query_service_owns_real_stream_lifecycle() -> None:
    """Verify stream start, latest-price use, and deterministic cleanup."""
    asyncio.run(_run_stream_lifecycle_test())


async def _run_stream_lifecycle_test() -> None:
    """Start and stop a background ticker subscription."""
    market_service = FakeStreamMarketService()
    runtime_control = FakeRuntimeStreamControl()
    tick_listener = FakeTickListener()
    stream_owner = LiveMarketStreamService(
        market_service=market_service,
        runtime_control=runtime_control,
        tick_listeners=(tick_listener,),
    )
    unused_repository = object()
    service = TelegramQueryService(
        symbol="BTCUSDT",
        market_service=market_service,
        paper_trading_service=FakePaperBalanceProvider(),
        position_repository=cast(PositionRepository, unused_repository),
        trade_repository=cast(TradeRepository, unused_repository),
        order_repository=cast(OrderRepository, unused_repository),
        market_stream_service=stream_owner,
        runtime_control=runtime_control,
    )

    assert not hasattr(service, "_stream_task")
    assert not hasattr(service, "_first_tick_event")
    assert not await service.stop_market_stream()
    assert not await service.wait_for_first_stream_tick(timeout_seconds=1.0)
    assert await service.start_market_stream()
    assert await service.wait_for_first_stream_tick(timeout_seconds=1.0)
    await asyncio.wait_for(market_service.ticker_published.wait(), timeout=1.0)

    assert runtime_control.stream_enabled
    assert market_service.stream_calls == ["BTCUSDT"]
    assert runtime_control.stream_prices == [Decimal("101")]
    assert tick_listener.prices == [Decimal("101")]
    assert await service.get_last_price() == Decimal("101")
    assert tuple(await service.get_trading_symbols()) == ("BTCUSDT", "ETHUSDT")
    assert tuple(await service.get_trading_symbols()) == ("BTCUSDT", "ETHUSDT")
    assert market_service.trading_symbol_calls == 1
    assert await service.stop_market_stream()
    assert not runtime_control.stream_enabled
    assert market_service.unsubscribe_calls == ["BTCUSDT"]
    await service.close()
    assert market_service.unsubscribe_calls == ["BTCUSDT"]


def test_owner_shutdown_stops_telegram_stream_once() -> None:
    """Verify provider-style owner shutdown is the only stream cleanup path."""
    asyncio.run(_run_owner_shutdown_test())


async def _run_owner_shutdown_test() -> None:
    """Start through Telegram then stop through the canonical owner once."""
    market_service = FakeStreamMarketService()
    runtime_control = FakeRuntimeStreamControl()
    stream_owner = LiveMarketStreamService(
        market_service=market_service,
        runtime_control=runtime_control,
    )
    unused_repository = object()
    service = TelegramQueryService(
        symbol="BTCUSDT",
        market_service=market_service,
        paper_trading_service=FakePaperBalanceProvider(),
        position_repository=cast(PositionRepository, unused_repository),
        trade_repository=cast(TradeRepository, unused_repository),
        order_repository=cast(OrderRepository, unused_repository),
        market_stream_service=stream_owner,
        runtime_control=runtime_control,
    )

    assert await service.start_market_stream()
    assert await service.wait_for_first_stream_tick(timeout_seconds=1.0)
    await stream_owner.stop_all()
    await service.close()

    assert market_service.unsubscribe_calls == ["BTCUSDT"]


def test_telegram_stream_compatibility_rejects_multiple_owned_streams() -> None:
    """Verify singular Telegram wrappers never choose a stream arbitrarily."""
    asyncio.run(_run_multi_stream_ambiguity_test())


async def _run_multi_stream_ambiguity_test() -> None:
    """Install two owner streams before invoking singular Telegram compatibility."""
    market_service = FakeStreamMarketService()
    runtime_control = FakeRuntimeStreamControl()
    stream_owner = LiveMarketStreamService(
        market_service=market_service,
        runtime_control=runtime_control,
    )
    unused_repository = object()
    service = TelegramQueryService(
        symbol="BTCUSDT",
        market_service=market_service,
        paper_trading_service=FakePaperBalanceProvider(),
        position_repository=cast(PositionRepository, unused_repository),
        trade_repository=cast(TradeRepository, unused_repository),
        order_repository=cast(OrderRepository, unused_repository),
        market_stream_service=stream_owner,
        runtime_control=runtime_control,
    )
    await stream_owner.start(
        context=LiveRuntimePositionContext(
            symbol="BTCUSDT",
            interval=Interval.M15,
            strategy_type=StrategyType.EMA_CROSS,
        ),
    )
    await stream_owner.start(
        context=LiveRuntimePositionContext(
            symbol="ETHUSDT",
            interval=Interval.H1,
            strategy_type=StrategyType.EMA_CROSS,
        ),
    )
    await asyncio.wait_for(market_service.ticker_published.wait(), timeout=1.0)

    with pytest.raises(RuntimeError, match="multiple owned streams"):
        await service.stop_market_stream()

    await stream_owner.stop_all()
