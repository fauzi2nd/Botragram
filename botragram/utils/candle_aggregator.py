"""
Botragram

Description:
    Realtime OHLCV candlestick stream aggregator.

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
import logging
from datetime import datetime
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.models import Candle
from botragram.utils.candle_resampler import (
    get_bucket_close_time,
    get_bucket_open_time,
)

__all__ = [
    "RealtimeCandleAggregator",
]

# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")


# =============================================================================
# Aggregator Implementation
# =============================================================================
class RealtimeCandleAggregator:
    """Stateful aggregator converting streaming base candles into target candles."""

    __slots__ = (
        "_candle_count",
        "_close_price",
        "_current_bucket_close",
        "_current_bucket_open",
        "_high_price",
        "_low_price",
        "_open_price",
        "_symbol",
        "_target_interval",
        "_volume",
    )

    def __init__(self, *, target_interval: Interval) -> None:
        """Initialize the realtime candle aggregator."""
        self._target_interval: Interval = target_interval
        self._symbol: str | None = None
        self._current_bucket_open: datetime | None = None
        self._current_bucket_close: datetime | None = None
        self._open_price: Decimal = _DECIMAL_ZERO
        self._high_price: Decimal = _DECIMAL_ZERO
        self._low_price: Decimal = _DECIMAL_ZERO
        self._close_price: Decimal = _DECIMAL_ZERO
        self._volume: Decimal = _DECIMAL_ZERO
        self._candle_count: int = 0

    @property
    def target_interval(self) -> Interval:
        """Return the target aggregation timeframe."""
        return self._target_interval

    @property
    def symbol(self) -> str | None:
        """Return the symbol being aggregated, if any."""
        return self._symbol

    @property
    def candle_count(self) -> int:
        """Return the number of base candles in the current in-flight bucket."""
        return self._candle_count

    @property
    def current_candle(self) -> Candle | None:
        """Return the current forming candle, or None if no candles received."""
        if (
            self._current_bucket_open is None
            or self._current_bucket_close is None
            or self._symbol is None
        ):
            return None

        return Candle(
            symbol=self._symbol,
            interval=self._target_interval,
            open_time=self._current_bucket_open,
            close_time=self._current_bucket_close,
            open_price=self._open_price,
            high_price=self._high_price,
            low_price=self._low_price,
            close_price=self._close_price,
            volume=self._volume,
        )

    def update(self, candle: Candle) -> tuple[Candle | None, Candle]:
        """Process an incoming base candle and update internal aggregation state.

        Args:
            candle: Incoming base timeframe candle.

        Returns:
            A tuple of (closed_candle, current_forming_candle).
            If a new timeframe bucket opened, closed_candle contains the completed
            candle from the previous bucket; otherwise closed_candle is None.

        Raises:
            ValueError: If the candle symbol differs or interval is larger than target.
        """
        if candle.interval.seconds > self._target_interval.seconds:
            raise ValueError(
                f"Cannot aggregate from larger interval {candle.interval.value} "
                f"to target interval {self._target_interval.value}"
            )

        if self._symbol is None:
            self._symbol = candle.symbol
        elif candle.symbol != self._symbol:
            raise ValueError(
                f"Mismatched candle symbol: expected {self._symbol}, "
                f"got {candle.symbol}"
            )

        bucket_open = get_bucket_open_time(candle.open_time, self._target_interval)

        # First candle ever received
        if self._current_bucket_open is None:
            self._current_bucket_open = bucket_open
            self._current_bucket_close = get_bucket_close_time(
                bucket_open, self._target_interval
            )
            self._open_price = candle.open_price
            self._high_price = candle.high_price
            self._low_price = candle.low_price
            self._close_price = candle.close_price
            self._volume = candle.volume
            self._candle_count = 1

            forming = self.current_candle
            assert forming is not None
            return (None, forming)

        # Same bucket: update running OHLCV
        if bucket_open == self._current_bucket_open:
            if candle.high_price > self._high_price:
                self._high_price = candle.high_price
            if candle.low_price < self._low_price:
                self._low_price = candle.low_price
            self._close_price = candle.close_price
            self._volume += candle.volume
            self._candle_count += 1

            forming = self.current_candle
            assert forming is not None
            return (None, forming)

        # New bucket started: finalize the previous bucket
        if bucket_open > self._current_bucket_open:
            assert self._current_bucket_close is not None
            closed_candle = Candle(
                symbol=self._symbol,
                interval=self._target_interval,
                open_time=self._current_bucket_open,
                close_time=self._current_bucket_close,
                open_price=self._open_price,
                high_price=self._high_price,
                low_price=self._low_price,
                close_price=self._close_price,
                volume=self._volume,
            )

            # Re-initialize with the new bucket's candle
            self._current_bucket_open = bucket_open
            self._current_bucket_close = get_bucket_close_time(
                bucket_open, self._target_interval
            )
            self._open_price = candle.open_price
            self._high_price = candle.high_price
            self._low_price = candle.low_price
            self._close_price = candle.close_price
            self._volume = candle.volume
            self._candle_count = 1

            forming = self.current_candle
            assert forming is not None
            return (closed_candle, forming)

        # Out-of-order / stale candle (bucket_open < self._current_bucket_open)
        _LOGGER.warning(
            "Out-of-order candle ignored for %s: bucket %s < current %s",
            candle.symbol,
            bucket_open.isoformat(),
            self._current_bucket_open.isoformat(),
        )
        forming = self.current_candle
        assert forming is not None
        return (None, forming)

    def flush(self) -> Candle | None:
        """Finalize and return the in-progress candle as closed, resetting state."""
        candle = self.current_candle
        self.reset()
        return candle

    def reset(self) -> None:
        """Reset the aggregator state."""
        self._current_bucket_open = None
        self._current_bucket_close = None
        self._open_price = _DECIMAL_ZERO
        self._high_price = _DECIMAL_ZERO
        self._low_price = _DECIMAL_ZERO
        self._close_price = _DECIMAL_ZERO
        self._volume = _DECIMAL_ZERO
        self._candle_count = 0
