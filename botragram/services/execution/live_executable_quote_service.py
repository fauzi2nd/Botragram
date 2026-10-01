"""Validate executable quote provenance for one fresh LIVE entry."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from botragram.enums import Interval, SignalType
from botragram.models import ExecutableQuote, Signal

__all__ = [
    "LIVE_MARKET_REFERENCE_REJECTED_REASON",
    "LIVE_STALE_SIGNAL_REASON",
    "get_executable_entry_price",
    "is_signal_stale",
]


LIVE_MARKET_REFERENCE_REJECTED_REASON: Final[str] = "market_reference_rejected"
LIVE_STALE_SIGNAL_REASON: Final[str] = "stale_signal"
_BASIS_POINTS: Final[Decimal] = Decimal("10000")
_DECIMAL_TWO: Final[Decimal] = Decimal("2")
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")


def get_executable_entry_price(
    *,
    quote: ExecutableQuote,
    signal: Signal,
    as_of: datetime,
    max_quote_age_ms: int,
    max_spread_bps: Decimal,
) -> Decimal | None:
    """Return a fresh side-aware price, or ``None`` when provenance is unsafe."""
    if max_quote_age_ms <= 0:
        raise ValueError("Maximum executable quote age must be greater than zero")
    if not max_spread_bps.is_finite() or max_spread_bps <= _DECIMAL_ZERO:
        raise ValueError("Maximum executable spread must be greater than zero")
    if quote.symbol.strip().upper() != signal.symbol.strip().upper():
        return None

    match signal.signal_type:
        case SignalType.BUY:
            entry_price = quote.ask_price
        case SignalType.SELL:
            entry_price = quote.bid_price
        case _:
            return None

    if not entry_price.is_finite() or entry_price <= _DECIMAL_ZERO:
        return None

    signal_generated_at = _normalize_utc_datetime(
        value=signal.generated_at,
        name="LIVE signal generated_at",
    )
    quote_time = _normalize_utc_datetime(
        value=quote.timestamp,
        name="LIVE executable quote timestamp",
    )
    if quote_time < signal_generated_at:
        return None

    quote_age_ms = (
        _normalize_utc_datetime(value=as_of, name="LIVE execution time") - quote_time
    ).total_seconds() * 1_000
    if quote_age_ms < 0 or quote_age_ms > max_quote_age_ms:
        return None

    midpoint = (quote.bid_price + quote.ask_price) / _DECIMAL_TWO
    if midpoint <= _DECIMAL_ZERO:
        return None
    spread_bps = (quote.ask_price - quote.bid_price) / midpoint * _BASIS_POINTS
    if spread_bps < _DECIMAL_ZERO or spread_bps > max_spread_bps:
        return None

    return entry_price


def is_signal_stale(
    *,
    signal: Signal,
    interval: Interval,
    as_of: datetime,
) -> bool:
    """Return whether execution reached the next close after signal creation."""
    execution_time = _normalize_utc_datetime(
        value=as_of,
        name="LIVE execution time",
    )
    signal_generated_at = _normalize_utc_datetime(
        value=signal.generated_at,
        name="LIVE signal generated_at",
    )
    return execution_time >= interval.next_close_time(close_time=signal_generated_at)


def _normalize_utc_datetime(*, value: datetime, name: str) -> datetime:
    """Require an aware timestamp and normalize it to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")

    return value.astimezone(UTC)
