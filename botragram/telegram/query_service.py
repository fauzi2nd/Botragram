"""Read-only live data provider for Telegram commands."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from botragram.models import Order, Position, Ticker, Trade
from botragram.repositories import OrderRepository, PositionRepository, TradeRepository

__all__ = ["TelegramQueryService"]


_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


class MarketTickerProvider(Protocol):
    """Read the latest ticker for one market."""

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return a normalized ticker."""
        ...


class PaperBalanceProvider(Protocol):
    """Read reconstructed paper balance."""

    async def get_available_balance(self) -> Decimal:
        """Return available paper funds."""
        ...


@dataclass(slots=True, kw_only=True, frozen=True)
class TelegramQueryService:
    """Query current paper portfolio and market state without mutation."""

    symbol: str
    market_service: MarketTickerProvider
    paper_trading_service: PaperBalanceProvider
    position_repository: PositionRepository
    trade_repository: TradeRepository
    order_repository: OrderRepository

    def __post_init__(self) -> None:
        """Normalize the configured trading symbol."""
        normalized_symbol = self.symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Telegram query symbol must not be empty")

        object.__setattr__(self, "symbol", normalized_symbol)

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
        try:
            ticker = await self.market_service.get_ticker(symbol=self.symbol)
            return ticker.last_price
        except Exception:
            _LOGGER.exception(
                "Live ticker unavailable for Telegram status: symbol=%s",
                self.symbol,
            )

        position = await self.position_repository.get_by_symbol(symbol=self.symbol)
        return position.current_price if position is not None else _DECIMAL_ZERO
