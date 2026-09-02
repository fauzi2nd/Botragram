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
from decimal import Decimal
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle, Signal
from botragram.utils.validator import validate_symbol

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
    """Generate and persist strategy signals for discovery."""

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Generate one signal without persistence."""
        ...

    async def save_signal(
        self,
        *,
        signal: Signal,
    ) -> None:
        """Persist one already-validated signal."""
        ...

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Generate and persist the signal for legacy discovery paths."""
        ...


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class OpportunityDiscoveryService:
    """Discover deterministic, actionable strategy signals across a market."""

    market_service: DiscoveryMarketDataProvider
    strategy_service: DiscoveryStrategyProvider
    min_confidence: Decimal = Decimal("0")
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
        selected_symbols = self._select_symbols(
            symbols=symbols,
            max_symbols=max_symbols,
        )
        return await self._discover_selected_symbols(
            symbols=selected_symbols,
            interval=interval,
            candle_limit=candle_limit,
            top_n=top_n,
            strategy_type=strategy_type,
            as_of=as_of,
        )

    async def discover_symbols(
        self,
        *,
        symbols: Sequence[str],
        interval: Interval,
        candle_limit: int,
        top_n: int,
        strategy_type: StrategyType,
    ) -> Sequence[Signal]:
        """Discover an explicit ordered batch with strict strategy provenance.

        Args:
            symbols: Ranked symbols to analyze in their supplied order.
            interval: Candle interval evaluated by the explicit strategy.
            candle_limit: Number of closed historical candles per symbol.
            top_n: Maximum number of ranked opportunities to return.
            strategy_type: Required strategy identity for LIVE provenance.

        Returns:
            Actionable signals ranked by confidence and symbol.

        Raises:
            ValueError: If the explicit batch or a discovery bound is invalid.
            RuntimeError: If market data or signal provenance is unsafe.
            asyncio.CancelledError: Propagates cancellation without advancing
                any caller-owned discovery-universe cursor.
        """
        self._validate_explicit_bounds(
            candle_limit=candle_limit,
            top_n=top_n,
        )
        selected_symbols = self._select_explicit_symbols(symbols=symbols)
        as_of = self._normalize_utc_datetime(
            value=self.utc_now(),
            name="Discovery decision time",
        )
        return await self._discover_selected_symbols(
            symbols=selected_symbols,
            interval=interval,
            candle_limit=candle_limit,
            top_n=top_n,
            strategy_type=strategy_type,
            as_of=as_of,
        )

    async def _discover_selected_symbols(
        self,
        *,
        symbols: Sequence[str],
        interval: Interval,
        candle_limit: int,
        top_n: int,
        strategy_type: StrategyType | None,
        as_of: datetime,
    ) -> tuple[Signal, ...]:
        """Evaluate one already-normalized symbol batch sequentially."""
        actionable_signals: list[Signal] = []
        effective_candle_limit = candle_limit
        if strategy_type is not None:
            get_minimum = getattr(self.strategy_service, "get_minimum_candles", None)
            if callable(get_minimum):
                candidate_minimum = get_minimum(strategy_type=strategy_type)
                if isinstance(candidate_minimum, int) and not isinstance(
                    candidate_minimum, bool
                ):
                    effective_candle_limit = max(candle_limit, candidate_minimum)

        for symbol in symbols:
            candles = await self.market_service.get_candles(
                symbol=symbol,
                interval=interval,
                limit=effective_candle_limit + 1,
                persist=False,
            )
            closed_candles = self._select_closed_candles(
                candles=candles,
                as_of=as_of,
                candle_limit=effective_candle_limit,
                require_strict_sequence=strategy_type is not None,
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
                self._validate_latest_closed_candle_freshness(
                    candle=closed_candles[-1],
                    interval=interval,
                    as_of=as_of,
                )

            if strategy_type is None:
                signal = await self.strategy_service.generate_and_save(
                    candles=closed_candles,
                    strategy_type=None,
                )
            else:
                signal = self.strategy_service.generate_signal(
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
                await self.strategy_service.save_signal(
                    signal=signal,
                )

            if (
                signal.signal_type in _ACTIONABLE_ENTRY_SIGNAL_TYPES
                and signal.confidence >= self.min_confidence
            ):
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
            cls._validate_closed_candle_price_provenance(candle=candle)

    @staticmethod
    def _validate_closed_candle_price_provenance(*, candle: Candle) -> None:
        """Require finite positive OHLC values with a valid candle price shape."""
        prices = (
            candle.open_price,
            candle.high_price,
            candle.low_price,
            candle.close_price,
        )

        if any(not price.is_finite() for price in prices):
            raise RuntimeError("Closed-candle OHLC prices must be finite")
        if any(price <= 0 for price in prices):
            raise RuntimeError("Closed-candle OHLC prices must be greater than zero")
        if candle.low_price > candle.high_price:
            raise RuntimeError("Closed-candle low_price must not exceed high_price")
        if not candle.low_price <= candle.open_price <= candle.high_price:
            raise RuntimeError("Closed-candle open_price must be within low/high range")
        if not candle.low_price <= candle.close_price <= candle.high_price:
            raise RuntimeError(
                "Closed-candle close_price must be within low/high range"
            )

    @classmethod
    def _validate_closed_candle_sequence(
        cls,
        *,
        candles: Sequence[Candle],
    ) -> None:
        """Require valid candle windows and strictly increasing time identities."""
        previous_open_time: datetime | None = None
        previous_close_time: datetime | None = None

        for candle in candles:
            open_time = cls._normalize_utc_datetime(
                value=candle.open_time,
                name="Closed candle open_time",
            )
            close_time = cls._normalize_utc_datetime(
                value=candle.close_time,
                name="Closed candle close_time",
            )

            if open_time >= close_time:
                raise RuntimeError("Closed-candle open_time must be before close_time")
            if previous_open_time is not None and open_time <= previous_open_time:
                raise RuntimeError(
                    "Closed-candle open_time sequence must be strictly increasing"
                )
            if previous_close_time is not None and close_time <= previous_close_time:
                raise RuntimeError(
                    "Closed-candle close_time sequence must be strictly increasing"
                )
            if previous_close_time is not None and open_time < previous_close_time:
                raise RuntimeError("Closed-candle windows must not overlap")

            previous_open_time = open_time
            previous_close_time = close_time

    @classmethod
    def _validate_latest_closed_candle_freshness(
        cls,
        *,
        candle: Candle,
        interval: Interval,
        as_of: datetime,
    ) -> None:
        """Require the latest explicit-strategy candle to still be current."""
        latest_close_time = cls._normalize_utc_datetime(
            value=candle.close_time,
            name="Latest closed candle close_time",
        )
        next_expected_close_time = interval.next_close_time(
            close_time=latest_close_time,
        )

        if as_of >= next_expected_close_time:
            raise RuntimeError("Latest closed candle is stale for discovery interval")

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
        if not signal.confidence.is_finite():
            raise RuntimeError("Strategy signal confidence must be finite")
        if signal.confidence < 0 or signal.confidence > 1:
            raise RuntimeError(
                "Strategy signal confidence must be between zero and one"
            )
        if signal.price != latest_closed_candle.close_price:
            raise RuntimeError(
                "Strategy signal price does not match latest closed candle"
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
        require_strict_sequence: bool = False,
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
        if require_strict_sequence:
            cls._validate_closed_candle_sequence(candles=closed_candles)
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
    def _validate_explicit_bounds(
        *,
        candle_limit: int,
        top_n: int,
    ) -> None:
        """Validate explicit-batch bounds before any market access."""
        if candle_limit <= 0:
            raise ValueError("Candle limit must be greater than zero")

        if top_n <= 0:
            raise ValueError("Top N must be greater than zero")

    @classmethod
    def _select_explicit_symbols(
        cls,
        *,
        symbols: Sequence[str],
    ) -> tuple[str, ...]:
        """Normalize and deduplicate an explicit batch without reordering it."""
        selected_symbols: list[str] = []
        seen_symbols: set[str] = set()

        for symbol in symbols:
            normalized_symbol = cls._normalize_symbol(symbol)
            validate_symbol(normalized_symbol)
            if normalized_symbol in seen_symbols:
                continue
            seen_symbols.add(normalized_symbol)
            selected_symbols.append(normalized_symbol)

        if not selected_symbols:
            raise ValueError("Explicit discovery symbols must not be empty")

        return tuple(selected_symbols)

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
