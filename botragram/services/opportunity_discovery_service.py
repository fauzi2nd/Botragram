"""
Botragram

Description:
    Bounded market-wide actionable signal discovery service.

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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, SignalType
from botragram.models import Candle, Signal

__all__ = [
    "OpportunityDiscoveryService",
]


# =============================================================================
# Constants
# =============================================================================
_ACTIONABLE_ENTRY_SIGNAL_TYPES = frozenset({SignalType.BUY, SignalType.SELL})


# =============================================================================
# Service Contracts
# =============================================================================
class DiscoveryMarketDataProvider(Protocol):
    """Provide the market data required for opportunity discovery."""

    async def get_trading_symbols(self, *, quote_asset: str) -> Sequence[str]:
        """Return active symbols for one quote asset."""
        ...

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        persist: bool = True,
    ) -> Sequence[Candle]:
        """Return historical candles for one trading symbol."""
        ...


class DiscoveryStrategyProvider(Protocol):
    """Generate and persist one strategy signal."""

    async def generate_and_save(self, *, candles: Sequence[Candle]) -> Signal:
        """Generate and persist the signal for ordered candles."""
        ...


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class OpportunityDiscoveryService:
    """Discover deterministic, actionable strategy signals across a market."""

    market_service: DiscoveryMarketDataProvider
    strategy_service: DiscoveryStrategyProvider

    async def discover(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> Sequence[Signal]:
        """Return the highest-confidence actionable entry signals.

        Args:
            quote_asset: Quote asset that defines the exchange universe.
            interval: Candle interval evaluated by the active strategy.
            candle_limit: Number of historical candles per symbol.
            max_symbols: Maximum number of normalized symbols to analyze.
            top_n: Maximum number of ranked opportunities to return.

        Returns:
            Actionable BUY and SELL signals ordered by descending confidence and
            then ascending symbol. Symbols are analyzed sequentially, so at
            most one market-data and strategy operation is active at a time.

        Raises:
            ValueError: If a bounded discovery input is invalid.
            asyncio.CancelledError: Propagates cancellation immediately; no
                background discovery tasks are created.
            Exception: Propagates the first market-data or strategy failure and
                stops the discovery operation without analyzing later symbols.
        """
        normalized_quote_asset = self._normalize_quote_asset(quote_asset)
        self._validate_bounds(
            candle_limit=candle_limit,
            max_symbols=max_symbols,
            top_n=top_n,
        )
        symbols = await self.market_service.get_trading_symbols(
            quote_asset=normalized_quote_asset,
        )
        actionable_signals: list[Signal] = []

        for symbol in self._select_symbols(symbols=symbols, max_symbols=max_symbols):
            candles = await self.market_service.get_candles(
                symbol=symbol,
                interval=interval,
                limit=candle_limit,
                persist=False,
            )
            signal = await self.strategy_service.generate_and_save(candles=candles)

            if signal.signal_type in _ACTIONABLE_ENTRY_SIGNAL_TYPES:
                actionable_signals.append(signal)

        return tuple(
            sorted(
                actionable_signals,
                key=lambda signal: (-signal.confidence, signal.symbol),
            )[:top_n]
        )

    @staticmethod
    def _normalize_quote_asset(quote_asset: str) -> str:
        """Normalize and validate a quote asset."""
        normalized_quote_asset = quote_asset.strip().upper()

        if not normalized_quote_asset:
            raise ValueError("Quote asset must not be empty")

        return normalized_quote_asset

    @staticmethod
    def _validate_bounds(
        *,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
    ) -> None:
        """Validate the bounded discovery inputs."""
        if candle_limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        if max_symbols <= 0:
            raise ValueError("Maximum symbols must be greater than zero")

        if top_n <= 0:
            raise ValueError("Top N must be greater than zero")

    @staticmethod
    def _select_symbols(
        *,
        symbols: Sequence[str],
        max_symbols: int,
    ) -> tuple[str, ...]:
        """Normalize, deduplicate, and bound symbols deterministically."""
        normalized_symbols = {
            symbol.strip().upper() for symbol in symbols if symbol.strip()
        }
        return tuple(sorted(normalized_symbols))[:max_symbols]
