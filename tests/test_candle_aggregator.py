"""
Botragram

Description:
    Unit tests for RealtimeCandleAggregator.

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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval
from botragram.models import Candle
from botragram.utils.candle_aggregator import RealtimeCandleAggregator

__all__ = ()

_BASE_TIME = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def _create_1m_candle(
    *,
    minute: int,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
    volume: str = "10.0",
    symbol: str = "BTCUSDT",
) -> Candle:
    open_time = _BASE_TIME + timedelta(minutes=minute)
    close_time = open_time + timedelta(minutes=1)
    return Candle(
        symbol=symbol,
        interval=Interval.M1,
        open_time=open_time,
        close_time=close_time,
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
        volume=Decimal(volume),
    )


def test_aggregator_single_candle_forming() -> None:
    """First incoming candle produces no closed candle and initial forming candle."""
    aggregator = RealtimeCandleAggregator(target_interval=Interval.M5)
    c0 = _create_1m_candle(
        minute=0,
        open_price="100.0",
        high_price="105.0",
        low_price="98.0",
        close_price="102.0",
        volume="5.0",
    )

    closed, forming = aggregator.update(c0)

    assert closed is None
    assert forming.symbol == "BTCUSDT"
    assert forming.interval == Interval.M5
    assert forming.open_time == _BASE_TIME
    assert forming.close_time == _BASE_TIME + timedelta(minutes=5)
    assert forming.open_price == Decimal("100.0")
    assert forming.high_price == Decimal("105.0")
    assert forming.low_price == Decimal("98.0")
    assert forming.close_price == Decimal("102.0")
    assert forming.volume == Decimal("5.0")
    assert aggregator.candle_count == 1


def test_aggregator_same_bucket_accumulation() -> None:
    """Candles within the same 5m bucket update high, low, close, and volume."""
    aggregator = RealtimeCandleAggregator(target_interval=Interval.M5)

    c0 = _create_1m_candle(
        minute=0,
        open_price="100.0",
        high_price="105.0",
        low_price="98.0",
        close_price="102.0",
        volume="5.0",
    )
    c1 = _create_1m_candle(
        minute=1,
        open_price="102.0",
        high_price="110.0",  # new high
        low_price="101.0",
        close_price="108.0",
        volume="10.0",
    )
    c2 = _create_1m_candle(
        minute=2,
        open_price="108.0",
        high_price="109.0",
        low_price="95.0",  # new low
        close_price="96.0",  # latest close
        volume="7.5",
    )

    aggregator.update(c0)
    aggregator.update(c1)
    closed, forming = aggregator.update(c2)

    assert closed is None
    assert forming.open_price == Decimal("100.0")
    assert forming.high_price == Decimal("110.0")
    assert forming.low_price == Decimal("95.0")
    assert forming.close_price == Decimal("96.0")
    assert forming.volume == Decimal("22.5")
    assert aggregator.candle_count == 3


def test_aggregator_bucket_boundary_transition() -> None:
    """Crossing into a new bucket emits the previous completed candle."""
    aggregator = RealtimeCandleAggregator(target_interval=Interval.M5)

    # Minutes 0 to 4 (5 constituent 1m candles)
    for i in range(5):
        aggregator.update(
            _create_1m_candle(
                minute=i,
                open_price=f"{100 + i}",
                high_price=f"{102 + i}",
                low_price=f"{99 + i}",
                close_price=f"{101 + i}",
                volume="2.0",
            )
        )

    # Minute 5 belongs to the second 5m bucket (00:05 -> 00:10)
    c5 = _create_1m_candle(
        minute=5,
        open_price="200.0",
        high_price="205.0",
        low_price="198.0",
        close_price="202.0",
        volume="10.0",
    )

    closed, forming = aggregator.update(c5)

    assert closed is not None
    assert closed.open_time == _BASE_TIME
    assert closed.close_time == _BASE_TIME + timedelta(minutes=5)
    assert closed.open_price == Decimal("100")
    assert closed.high_price == Decimal("106")  # max(102+4) = 106
    assert closed.low_price == Decimal("99")  # min(99+0) = 99
    assert closed.close_price == Decimal("105")  # 101+4 = 105
    assert closed.volume == Decimal("10.0")  # 5 * 2.0 = 10.0

    # New forming candle has minute 5 state
    assert forming.open_time == _BASE_TIME + timedelta(minutes=5)
    assert forming.close_time == _BASE_TIME + timedelta(minutes=10)
    assert forming.open_price == Decimal("200.0")
    assert forming.volume == Decimal("10.0")
    assert aggregator.candle_count == 1


def test_aggregator_flush_and_reset() -> None:
    """Flush returns current in-flight candle and resets state."""
    aggregator = RealtimeCandleAggregator(target_interval=Interval.M5)
    c0 = _create_1m_candle(
        minute=0,
        open_price="100.0",
        high_price="105.0",
        low_price="98.0",
        close_price="102.0",
        volume="5.0",
    )
    aggregator.update(c0)

    flushed = aggregator.flush()
    assert flushed is not None
    assert flushed.open_price == Decimal("100.0")
    assert flushed.close_price == Decimal("102.0")

    # State is reset
    assert aggregator.current_candle is None
    assert aggregator.candle_count == 0
    assert aggregator.flush() is None


def test_aggregator_ignores_out_of_order_candles() -> None:
    """Out-of-order candle from older bucket does not corrupt current state."""
    aggregator = RealtimeCandleAggregator(target_interval=Interval.M5)
    c5 = _create_1m_candle(
        minute=5,
        open_price="150.0",
        high_price="155.0",
        low_price="149.0",
        close_price="152.0",
    )
    aggregator.update(c5)

    # Stale candle from minute 2
    c2 = _create_1m_candle(
        minute=2,
        open_price="100.0",
        high_price="105.0",
        low_price="98.0",
        close_price="102.0",
    )
    closed, forming = aggregator.update(c2)

    assert closed is None
    assert forming.open_price == Decimal("150.0")
    assert aggregator.candle_count == 1


def test_aggregator_symbol_mismatch_raises() -> None:
    """Mismatched symbol raises ValueError."""
    aggregator = RealtimeCandleAggregator(target_interval=Interval.M5)
    c_btc = _create_1m_candle(
        minute=0,
        open_price="100",
        high_price="101",
        low_price="99",
        close_price="100",
        symbol="BTCUSDT",
    )
    c_eth = _create_1m_candle(
        minute=1,
        open_price="10",
        high_price="11",
        low_price="9",
        close_price="10",
        symbol="ETHUSDT",
    )
    aggregator.update(c_btc)

    with pytest.raises(ValueError, match="Mismatched candle symbol"):
        aggregator.update(c_eth)


def test_aggregator_interval_larger_than_target_raises() -> None:
    """Input interval larger than target interval raises ValueError."""
    aggregator = RealtimeCandleAggregator(target_interval=Interval.M5)
    c_15m = Candle(
        symbol="BTCUSDT",
        interval=Interval.M15,
        open_time=_BASE_TIME,
        close_time=_BASE_TIME + timedelta(minutes=15),
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("95"),
        close_price=Decimal("102"),
        volume=Decimal("10"),
    )

    with pytest.raises(ValueError, match="Cannot aggregate from larger interval"):
        aggregator.update(c_15m)
