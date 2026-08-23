"""
Botragram

Description:
    Market data access and persistence service.

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
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.exchanges.base import BaseExchangeClient, BaseStreamClient
from botragram.models import Candle, ExecutableQuote, Ticker
from botragram.repositories import CandleRepository

__all__ = [
    "MarketService",
]


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class MarketService:
    """Provide market data through exchange and repository dependencies."""

    exchange_client: BaseExchangeClient
    stream_client: BaseStreamClient
    candle_repository: CandleRepository

    @property
    def is_stream_connected(self) -> bool:
        """Return whether the WebSocket transport session is ready."""
        return self.stream_client.is_connected

    async def get_ticker(
        self,
        *,
        symbol: str,
    ) -> Ticker:
        """Return the latest ticker for a trading symbol.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Latest standardized ticker.
        """
        return await self.exchange_client.get_ticker(
            symbol=self._normalize_symbol(symbol),
        )

    async def get_executable_quote(
        self,
        *,
        symbol: str,
    ) -> ExecutableQuote:
        """Return the current executable bid/ask quote for a trading symbol."""
        return await self.exchange_client.get_executable_quote(
            symbol=self._normalize_symbol(symbol),
        )

    async def get_trading_symbols(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[str]:
        """Return exchange-supported active symbols for one quote asset."""
        normalized_quote_asset = quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Quote asset must not be empty")

        return await self.exchange_client.get_trading_symbols(
            quote_asset=normalized_quote_asset,
        )

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        persist: bool = True,
    ) -> Sequence[Candle]:
        """Fetch historical candles from the exchange.

        Args:
            symbol: Trading pair symbol.
            interval: Candlestick interval.
            limit: Maximum number of candles to fetch.
            start_time: Optional inclusive start time.
            end_time: Optional inclusive end time.
            persist: Whether fetched candles should be persisted.

        Returns:
            Candles ordered from oldest to newest.

        Raises:
            ValueError: If the requested limit or datetime range is invalid.
        """
        if limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("Candle start time must not be after end time")

        candles = await self.exchange_client.get_candles(
            symbol=self._normalize_symbol(symbol),
            interval=interval,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )

        if persist and candles:
            await self.candle_repository.save_many(
                candles=candles,
            )

        return candles

    async def get_stored_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
    ) -> Sequence[Candle]:
        """Return the latest persisted candles.

        Args:
            symbol: Trading pair symbol.
            interval: Candle interval.
            limit: Maximum number of candles to return.

        Returns:
            Stored candles ordered from oldest to newest.

        Raises:
            ValueError: If the requested limit is invalid.
        """
        if limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        return await self.candle_repository.get_latest(
            symbol=self._normalize_symbol(symbol),
            interval=interval,
            limit=limit,
        )

    async def stream_ticker(
        self,
        *,
        symbol: str,
    ) -> AsyncIterator[Ticker]:
        """Stream ticker updates for a trading symbol.

        Args:
            symbol: Trading pair symbol.

        Yields:
            Standardized ticker updates.
        """
        normalized_symbol = self._normalize_symbol(symbol)

        async for ticker in self.stream_client.stream_ticker(
            symbol=normalized_symbol,
        ):
            yield ticker

    async def stream_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        persist: bool = True,
    ) -> AsyncIterator[Candle]:
        """Stream candle updates for a trading symbol.

        Args:
            symbol: Trading pair symbol.
            interval: Candlestick interval.
            persist: Whether streamed candles should be persisted.

        Yields:
            Standardized candle updates.
        """
        normalized_symbol = self._normalize_symbol(symbol)

        async for candle in self.stream_client.stream_candles(
            symbol=normalized_symbol,
            interval=interval,
        ):
            if persist:
                await self.candle_repository.save(
                    candle=candle,
                )

            yield candle

    async def unsubscribe(
        self,
        *,
        symbol: str,
    ) -> None:
        """Stop active market streams for a trading symbol.

        Args:
            symbol: Trading pair symbol.
        """
        await self.stream_client.unsubscribe(
            symbol=self._normalize_symbol(symbol),
        )

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol
