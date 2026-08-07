"""Telegram market-stream lifecycle tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import cast

from botragram.models import Ticker
from botragram.repositories import (
    OrderRepository,
    PositionRepository,
    TradeRepository,
)
from botragram.telegram.query_service import TelegramQueryService


@dataclass(slots=True)
class FakeStreamMarketService:
    """Yield one ticker and remain subscribed until cancelled."""

    ticker_published: asyncio.Event = field(default_factory=asyncio.Event)
    unsubscribe_calls: list[str] = field(default_factory=list[str])

    @property
    def is_stream_connected(self) -> bool:
        """Return a ready test transport."""
        return True

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return a deterministic fallback ticker."""
        return _create_ticker(symbol=symbol, price=Decimal("99"))

    async def stream_ticker(self, *, symbol: str) -> AsyncIterator[Ticker]:
        """Yield one streamed ticker and wait indefinitely."""
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
class FakePaperBalanceProvider:
    """Satisfy query service construction without portfolio access."""

    async def get_available_balance(self) -> Decimal:
        """Return a deterministic paper balance."""
        return Decimal("10000")


def _create_ticker(*, symbol: str, price: Decimal) -> Ticker:
    """Create one deterministic market ticker."""
    return Ticker(
        symbol=symbol,
        bid_price=price - Decimal("1"),
        ask_price=price + Decimal("1"),
        last_price=price,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_telegram_query_service_owns_real_stream_lifecycle() -> None:
    """Verify stream start, latest-price use, and deterministic cleanup."""
    asyncio.run(_run_stream_lifecycle_test())


async def _run_stream_lifecycle_test() -> None:
    """Start and stop a background ticker subscription."""
    market_service = FakeStreamMarketService()
    runtime_control = FakeRuntimeStreamControl()
    unused_repository = object()
    service = TelegramQueryService(
        symbol="BTCUSDT",
        market_service=market_service,
        paper_trading_service=FakePaperBalanceProvider(),
        position_repository=cast(PositionRepository, unused_repository),
        trade_repository=cast(TradeRepository, unused_repository),
        order_repository=cast(OrderRepository, unused_repository),
        runtime_control=runtime_control,
    )

    assert await service.start_market_stream()
    await asyncio.wait_for(market_service.ticker_published.wait(), timeout=1.0)

    assert runtime_control.stream_enabled
    assert runtime_control.stream_prices == [Decimal("101")]
    assert await service.get_last_price() == Decimal("101")
    assert await service.stop_market_stream()
    assert not runtime_control.stream_enabled
    assert market_service.unsubscribe_calls == ["BTCUSDT"]
