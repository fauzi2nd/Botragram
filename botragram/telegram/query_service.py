"""Read-only live data provider for Telegram commands."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Protocol

from botragram.models import Order, Position, Ticker, Trade
from botragram.repositories import OrderRepository, PositionRepository, TradeRepository

__all__ = ["MarketTickListener", "TelegramQueryService"]


_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class MarketTickerProvider(Protocol):
    """Read the latest ticker for one market."""

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return a normalized ticker."""
        ...

    @property
    def is_stream_connected(self) -> bool:
        """Return whether the WebSocket transport is ready."""
        ...

    def stream_ticker(self, *, symbol: str) -> AsyncIterator[Ticker]:
        """Stream normalized ticker updates."""
        ...

    async def unsubscribe(self, *, symbol: str) -> None:
        """Stop active subscriptions for a symbol."""
        ...


class PaperBalanceProvider(Protocol):
    """Read reconstructed paper balance."""

    async def get_available_balance(self) -> Decimal:
        """Return available paper funds."""
        ...


class RuntimeSymbolProvider(Protocol):
    """Expose the currently selected runtime symbol."""

    @property
    def symbol(self) -> str:
        """Return the current normalized symbol."""
        ...

    def set_stream_enabled(self, enabled: bool) -> bool:
        """Record whether a market subscription is active."""
        ...

    def record_stream_tick(self, *, price: Decimal) -> None:
        """Record one market-stream ticker event."""
        ...


class MarketTickListener(Protocol):
    """Consume validated market ticks without owning the stream lifecycle."""

    async def on_market_tick(self, *, ticker: Ticker) -> None:
        """Process one normalized ticker event."""
        ...


@dataclass(slots=True, kw_only=True)
class TelegramQueryService:
    """Query current paper portfolio and market state without mutation."""

    symbol: str
    market_service: MarketTickerProvider
    paper_trading_service: PaperBalanceProvider
    position_repository: PositionRepository
    trade_repository: TradeRepository
    order_repository: OrderRepository
    runtime_control: RuntimeSymbolProvider | None = None
    tick_listeners: tuple[MarketTickListener, ...] = ()
    _stream_task: asyncio.Task[None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _stream_symbol: str | None = field(default=None, init=False)
    _last_stream_price: Decimal = field(default=_DECIMAL_ZERO, init=False)

    def __post_init__(self) -> None:
        """Normalize the configured trading symbol."""
        normalized_symbol = self.symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Telegram query symbol must not be empty")

        self.symbol = normalized_symbol

    async def get_positions(self) -> Sequence[Position]:
        """Return all persisted active paper positions."""
        return await self.position_repository.get_open_positions()

    async def get_available_balance(self) -> Decimal:
        """Return reconstructed free paper balance."""
        return await self.paper_trading_service.get_available_balance()

    async def get_latest_trades(self, *, limit: int) -> Sequence[Trade]:
        """Return the latest persisted paper fills."""
        if limit <= 0:
            raise ValueError("Telegram trade history limit must be greater than zero")

        count = await self.trade_repository.count()

        if count == 0:
            return ()

        return await self.trade_repository.get_latest(limit=min(limit, count))

    async def get_latest_orders(self, *, limit: int) -> Sequence[Order]:
        """Return the latest persisted paper orders."""
        if limit <= 0:
            raise ValueError("Telegram order history limit must be greater than zero")

        count = await self.order_repository.count()

        if count == 0:
            return ()

        return await self.order_repository.get_latest(limit=min(limit, count))

    async def get_last_price(self) -> Decimal:
        """Return public ticker price, falling back to a persisted position mark."""
        symbol = (
            self.runtime_control.symbol
            if self.runtime_control is not None
            else self.symbol
        )

        if self._stream_symbol == symbol and self._last_stream_price > 0:
            return self._last_stream_price

        try:
            ticker = await self.market_service.get_ticker(symbol=symbol)
            return ticker.last_price
        except Exception:
            _LOGGER.exception(
                "Live ticker unavailable for Telegram status: symbol=%s",
                symbol,
            )

        position = await self.position_repository.get_by_symbol(symbol=symbol)
        return position.current_price if position is not None else _DECIMAL_ZERO

    def is_stream_transport_connected(self) -> bool:
        """Return transport readiness without claiming an active subscription."""
        return self.market_service.is_stream_connected

    async def start_market_stream(self) -> bool:
        """Start one background ticker subscription for the selected symbol."""
        task = self._stream_task

        if task is not None and not task.done():
            return False

        symbol = (
            self.runtime_control.symbol
            if self.runtime_control is not None
            else self.symbol
        )
        self._stream_symbol = symbol
        self._stream_task = asyncio.create_task(
            self._consume_market_stream(symbol=symbol),
            name=f"telegram-market-stream:{symbol}",
        )

        if self.runtime_control is not None:
            self.runtime_control.set_stream_enabled(True)

        _LOGGER.info("Telegram market stream started: symbol=%s", symbol)
        return True

    async def stop_market_stream(self) -> bool:
        """Stop the background ticker subscription if it is active."""
        task = self._stream_task
        symbol = self._stream_symbol

        if task is None or task.done():
            if self.runtime_control is not None:
                self.runtime_control.set_stream_enabled(False)
            return False

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        if symbol is not None:
            await self.market_service.unsubscribe(symbol=symbol)

        self._stream_task = None
        self._stream_symbol = None

        if self.runtime_control is not None:
            self.runtime_control.set_stream_enabled(False)

        _LOGGER.info("Telegram market stream stopped: symbol=%s", symbol)
        return True

    async def close(self) -> None:
        """Release the optional background market subscription."""
        await self.stop_market_stream()

    async def _consume_market_stream(self, *, symbol: str) -> None:
        """Keep the latest streamed price available to Telegram queries."""
        try:
            async for ticker in self.market_service.stream_ticker(symbol=symbol):
                self._last_stream_price = ticker.last_price

                if self.runtime_control is not None:
                    self.runtime_control.record_stream_tick(
                        price=ticker.last_price,
                    )

                for listener in self.tick_listeners:
                    try:
                        await listener.on_market_tick(ticker=ticker)
                    except Exception:
                        _LOGGER.exception(
                            "Market tick listener failed: symbol=%s listener=%s",
                            symbol,
                            type(listener).__name__,
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Telegram market stream failed: symbol=%s", symbol)
        finally:
            if self.runtime_control is not None:
                self.runtime_control.set_stream_enabled(False)
