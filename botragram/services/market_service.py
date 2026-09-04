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
from datetime import UTC, datetime

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.exchanges.base import BaseExchangeClient, BaseStreamClient
from botragram.models import Candle, ExecutableQuote, MarketUniverseEntry, Ticker
from botragram.repositories import CandleRepository
from botragram.utils.candle_aggregator import RealtimeCandleAggregator
from botragram.utils.candle_resampler import resample_candles

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
        return await self.exchange_client.get_trading_symbols(
            quote_asset=self._normalize_quote_asset(quote_asset),
        )

    async def get_market_universe(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[MarketUniverseEntry]:
        """Return exchange-provided market facts for one quote asset."""
        return await self.exchange_client.get_market_universe(
            quote_asset=self._normalize_quote_asset(quote_asset),
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
        prefer_stored: bool = False,
        as_of: datetime | None = None,
    ) -> Sequence[Candle]:
        """Fetch historical candles from the exchange or stored data.

        Args:
            symbol: Trading pair symbol.
            interval: Candlestick interval.
            limit: Maximum number of candles to fetch.
            start_time: Optional inclusive start time.
            end_time: Optional inclusive end time.
            persist: Whether fetched candles should be persisted.
            prefer_stored: Whether to return fresh persisted candles if available.
            as_of: Evaluation reference timestamp for candle freshness.

        Returns:
            Candles ordered from oldest to newest.

        Raises:
            ValueError: If the requested limit or datetime range is invalid.
        """
        if limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        if start_time is not None and end_time is not None and start_time > end_time:
            raise ValueError("Candle start time must not be after end time")

        normalized_symbol = self._normalize_symbol(symbol)

        if prefer_stored and start_time is None and end_time is None:
            stored_candles = await self._get_fresh_stored_candles(
                symbol=normalized_symbol,
                interval=interval,
                limit=limit,
                as_of=as_of,
            )
            if stored_candles is not None:
                return stored_candles

        candles = await self.exchange_client.get_candles(
            symbol=normalized_symbol,
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

    async def _get_fresh_stored_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        as_of: datetime | None,
    ) -> Sequence[Candle] | None:
        """Return stored candles if available and fresh, otherwise None."""
        direct_stored = await self.candle_repository.get_latest(
            symbol=symbol,
            interval=interval,
            limit=limit,
        )
        if len(direct_stored) >= limit:
            if self._is_candle_fresh(
                candle=direct_stored[-1],
                interval=interval,
                as_of=as_of,
            ):
                return direct_stored

        if interval is not Interval.M1:
            try:
                resampled = await self.get_stored_resampled_candles(
                    symbol=symbol,
                    target_interval=interval,
                    limit=limit,
                )
                if len(resampled) >= limit:
                    if self._is_candle_fresh(
                        candle=resampled[-1],
                        interval=interval,
                        as_of=as_of,
                    ):
                        return resampled
            except ValueError:
                pass

        return None

    @staticmethod
    def _is_candle_fresh(
        *,
        candle: Candle,
        interval: Interval,
        as_of: datetime | None,
    ) -> bool:
        """Check if candle's close_time is current relative to evaluation time."""
        ref_time = as_of if as_of is not None else datetime.now(UTC)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=UTC)
        close_time = candle.close_time
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=UTC)
        next_close = interval.next_close_time(close_time=close_time)
        return ref_time < next_close

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

    async def get_stored_resampled_candles(
        self,
        *,
        symbol: str,
        target_interval: Interval,
        limit: int,
        source_interval: Interval = Interval.M1,
        closed_only: bool = True,
        min_candles_per_bucket: int = 1,
    ) -> Sequence[Candle]:
        """Return resampled candles on-the-fly from persisted data.

        Args:
            symbol: Trading pair symbol.
            target_interval: Destination timeframe.
            limit: Maximum number of resampled candles to return.
            source_interval: Base timeframe stored in database (default: 1m).
            closed_only: Exclude the in-progress forming candle.
            min_candles_per_bucket: Minimum source candles required per bucket.

        Returns:
            Aggregated candles ordered from oldest to newest.

        Raises:
            ValueError: If limit <= 0 or intervals are incompatible.
        """
        if limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        normalized_symbol = self._normalize_symbol(symbol)

        if target_interval is source_interval:
            return await self.candle_repository.get_latest(
                symbol=normalized_symbol,
                interval=target_interval,
                limit=limit,
            )

        multiplier = max(1, target_interval.seconds // source_interval.seconds)
        source_limit = (limit + 2) * multiplier

        source_candles = await self.candle_repository.get_latest(
            symbol=normalized_symbol,
            interval=source_interval,
            limit=source_limit,
        )
        if not source_candles:
            return ()

        resampled = resample_candles(
            candles=source_candles,
            target_interval=target_interval,
            closed_only=closed_only,
            min_candles_per_bucket=min_candles_per_bucket,
        )
        if len(resampled) > limit:
            return resampled[-limit:]
        return resampled

    async def get_stored_resampled_candles_between(
        self,
        *,
        symbol: str,
        target_interval: Interval,
        start_time: datetime,
        end_time: datetime,
        source_interval: Interval = Interval.M1,
        closed_only: bool = True,
        min_candles_per_bucket: int = 1,
    ) -> Sequence[Candle]:
        """Return resampled candles within a datetime range using persisted data.

        Args:
            symbol: Trading pair symbol.
            target_interval: Destination timeframe.
            start_time: Inclusive start boundary.
            end_time: Inclusive end boundary.
            source_interval: Base timeframe stored in database (default: 1m).
            closed_only: Exclude the in-progress forming candle.
            min_candles_per_bucket: Minimum source candles required per bucket.

        Returns:
            Aggregated candles ordered from oldest to newest.

        Raises:
            ValueError: If start_time > end_time or intervals are incompatible.
        """
        if start_time > end_time:
            raise ValueError("Candle start time must not be after end time")

        normalized_symbol = self._normalize_symbol(symbol)

        if target_interval is source_interval:
            return await self.candle_repository.get_between(
                symbol=normalized_symbol,
                interval=target_interval,
                start_time=start_time,
                end_time=end_time,
            )

        source_candles = await self.candle_repository.get_between(
            symbol=normalized_symbol,
            interval=source_interval,
            start_time=start_time,
            end_time=end_time,
        )
        if not source_candles:
            return ()

        return resample_candles(
            candles=source_candles,
            target_interval=target_interval,
            closed_only=closed_only,
            min_candles_per_bucket=min_candles_per_bucket,
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

    async def stream_resampled_candles(
        self,
        *,
        symbol: str,
        target_interval: Interval,
        source_interval: Interval = Interval.M1,
        persist_source: bool = True,
        closed_only: bool = True,
    ) -> AsyncIterator[Candle]:
        """Stream real-time resampled candles aggregated on-the-fly from a base stream.

        Args:
            symbol: Trading pair symbol.
            target_interval: Destination timeframe.
            source_interval: Base timeframe received from exchange stream (default: 1m).
            persist_source: Whether incoming source candles are saved to storage.
            closed_only: When True, only yields closed candles when bucket boundary
                finishes. When False, yields the forming candle on each tick.

        Yields:
            Standardized target timeframe candle updates.
        """
        normalized_symbol = self._normalize_symbol(symbol)

        if target_interval is source_interval:
            async for candle in self.stream_candles(
                symbol=normalized_symbol,
                interval=source_interval,
                persist=persist_source,
            ):
                yield candle
            return

        aggregator = RealtimeCandleAggregator(target_interval=target_interval)

        async for source_candle in self.stream_client.stream_candles(
            symbol=normalized_symbol,
            interval=source_interval,
        ):
            if persist_source:
                await self.candle_repository.save(
                    candle=source_candle,
                )

            closed_candle, forming_candle = aggregator.update(source_candle)

            if closed_only:
                if closed_candle is not None:
                    yield closed_candle
            else:
                yield forming_candle

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
    def _normalize_quote_asset(
        quote_asset: str,
    ) -> str:
        """Normalize and validate a quote asset."""
        normalized_quote_asset = quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Quote asset must not be empty")

        return normalized_quote_asset

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol
