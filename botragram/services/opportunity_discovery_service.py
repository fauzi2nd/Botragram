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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle, Signal

__all__ = [
    "OpportunityDiscoveryService",
]


# =============================================================================
# Constants
# =============================================================================
_ACTIONABLE_ENTRY_SIGNAL_TYPES = frozenset({SignalType.BUY, SignalType.SELL})


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC discovery time."""
    return datetime.now(UTC)


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

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
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
    utc_now: Callable[[], datetime] = _utc_now

    async def discover(
        self,
        *,
        quote_asset: str,
        interval: Interval,
        candle_limit: int,
        max_symbols: int,
        top_n: int,
        strategy_type: StrategyType | None = None,
    ) -> Sequence[Signal]:
        """Return the highest-confidence actionable entry signals.

        Args:
            quote_asset: Quote asset that defines the exchange universe.
            interval: Candle interval evaluated by the active strategy.
            candle_limit: Number of closed historical candles per symbol.
            max_symbols: Maximum number of normalized symbols to analyze.
            top_n: Maximum number of ranked opportunities to return.
            strategy_type: Explicit strategy provenance required by autonomous
                LIVE. Omitted callers preserve the configured default strategy
                behavior used by existing non-LIVE discovery workflows.

        Returns:
            Actionable BUY and SELL signals ordered by descending confidence and
            then ascending symbol. Symbols are analyzed sequentially, so at
            most one market-data and strategy operation is active at a time.

        Raises:
            ValueError: If a bounded discovery input or timestamp is invalid.
            RuntimeError: If a symbol has no closed candles or a strategy
                produces a future-dated signal.
            asyncio.CancelledError: Propagates cancellation immediately; no
                background discovery tasks are created.
            Exception: Propagates the first market-data or strategy failure and
                stops discovery without analyzing later symbols.
        """
        normalized_quote_asset = self._normalize_quote_asset(quote_asset)
        self._validate_bounds(
            candle_limit=candle_limit,
            max_symbols=max_symbols,
            top_n=top_n,
        )
        as_of = self._normalize_utc_datetime(
            value=self.utc_now(),
            name="Discovery decision time",
        )
        symbols = await self.market_service.get_trading_symbols(
            quote_asset=normalized_quote_asset,
        )
        actionable_signals: list[Signal] = []

        for symbol in self._select_symbols(symbols=symbols, max_symbols=max_symbols):
            candles = await self.market_service.get_candles(
                symbol=symbol,
                interval=interval,
                limit=candle_limit + 1,
                persist=False,
            )
            closed_candles = self._select_closed_candles(
                candles=candles,
                as_of=as_of,
                candle_limit=candle_limit,
            )
            if not closed_candles:
                raise RuntimeError(
                    f"No closed candles available for discovery: {symbol}"
                )

            if strategy_type is not None:
                self._validate_closed_candle_provenance(
                    candles=closed_candles,
                    symbol=symbol,
                    interval=interval,
                )

            signal = await self.strategy_service.generate_and_save(
                candles=closed_candles,
                strategy_type=strategy_type,
            )
            signal_generated_at = self._normalize_utc_datetime(
                value=signal.generated_at,
                name="Signal generated_at",
            )
            if signal_generated_at > as_of:
                raise RuntimeError(
                    "Strategy generated a signal after the discovery decision time"
                )

            if strategy_type is not None:
                self._validate_signal_provenance(
                    signal=signal,
                    signal_generated_at=signal_generated_at,
                    symbol=symbol,
                    latest_closed_candle=closed_candles[-1],
                    strategy_type=strategy_type,
                )

            if signal.signal_type in _ACTIONABLE_ENTRY_SIGNAL_TYPES:
                actionable_signals.append(signal)

        return tuple(
            sorted(
                actionable_signals,
                key=lambda signal: (-signal.confidence, signal.symbol),
            )[:top_n]
        )

    @classmethod
    def _validate_closed_candle_provenance(
        cls,
        *,
        candles: Sequence[Candle],
        symbol: str,
        interval: Interval,
    ) -> None:
        """Require every strategy candle to match the discovery context."""
        for candle in candles:
            if cls._normalize_symbol(candle.symbol) != symbol:
                raise RuntimeError(
                    "Closed-candle symbol does not match discovery symbol"
                )
            if candle.interval is not interval:
                raise RuntimeError(
                    "Closed-candle interval does not match discovery interval"
                )

    @classmethod
    def _validate_signal_provenance(
        cls,
        *,
        signal: Signal,
        signal_generated_at: datetime,
        symbol: str,
        latest_closed_candle: Candle,
        strategy_type: StrategyType,
    ) -> None:
        """Bind one generated signal to the exact closed-candle context."""
        if cls._normalize_symbol(signal.symbol) != symbol:
            raise RuntimeError("Strategy signal symbol does not match discovery symbol")
        if signal.strategy_name != strategy_type.value:
            raise RuntimeError(
                "Strategy signal name does not match explicit strategy context"
            )

        latest_close_time = cls._normalize_utc_datetime(
            value=latest_closed_candle.close_time,
            name="Latest closed candle close_time",
        )
        if signal_generated_at != latest_close_time:
            raise RuntimeError(
                "Strategy signal generated_at does not match latest closed candle"
            )

    @classmethod
    def _select_closed_candles(
        cls,
        *,
        candles: Sequence[Candle],
        as_of: datetime,
        candle_limit: int,
    ) -> tuple[Candle, ...]:
        """Return the latest bounded candles closed by the decision time."""
        closed_candles = tuple(
            candle
            for candle in candles
            if cls._normalize_utc_datetime(
                value=candle.close_time,
                name="Candle close_time",
            )
            <= as_of
        )
        return closed_candles[-candle_limit:]

    @staticmethod
    def _normalize_utc_datetime(*, value: datetime, name: str) -> datetime:
        """Require an aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")

        return value.astimezone(UTC)

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Normalize and validate one discovery symbol."""
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("Discovery symbol must not be empty")
        return normalized_symbol

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
        """Validate discovery bounds before any market access."""
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
