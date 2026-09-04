"""
Botragram

Description:
    Unit tests for deterministic candlestick resampling engine.

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
from botragram.utils.candle_resampler import resample_candles


# =============================================================================
# Helper Fixtures / Builders
# =============================================================================
def _make_1m_candle(
    *,
    symbol: str = "BTCUSDT",
    open_time: datetime,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
    volume: str,
) -> Candle:
    return Candle(
        symbol=symbol,
        interval=Interval.M1,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open_price=Decimal(open_price),
        high_price=Decimal(high_price),
        low_price=Decimal(low_price),
        close_price=Decimal(close_price),
        volume=Decimal(volume),
    )


# =============================================================================
# Tests
# =============================================================================
def test_resample_candles_empty() -> None:
    """Empty input returns empty tuple."""
    assert resample_candles(candles=(), target_interval=Interval.M5) == ()


def test_resample_same_interval_returns_sorted() -> None:
    """Resampling to the same interval returns source candles sorted."""
    base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    c1 = _make_1m_candle(
        open_time=base_time + timedelta(minutes=1),
        open_price="101",
        high_price="102",
        low_price="100",
        close_price="101.5",
        volume="1.5",
    )
    c0 = _make_1m_candle(
        open_time=base_time,
        open_price="100",
        high_price="101",
        low_price="99",
        close_price="100.5",
        volume="1.0",
    )

    # Pass unordered
    result = resample_candles(candles=[c1, c0], target_interval=Interval.M1)
    assert len(result) == 2
    assert result[0].open_time == base_time
    assert result[1].open_time == base_time + timedelta(minutes=1)


def test_resample_1m_to_5m_ohlcv_accuracy() -> None:
    """Resample 5 continuous 1m candles into a single 5m candle with exact OHLCV."""
    base_time = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    candles = [
        _make_1m_candle(
            open_time=base_time + timedelta(minutes=0),
            open_price="100.0",
            high_price="105.0",
            low_price="99.0",
            close_price="104.0",
            volume="10.5",
        ),
        _make_1m_candle(
            open_time=base_time + timedelta(minutes=1),
            open_price="104.0",
            high_price="110.0",  # Highest
            low_price="103.0",
            close_price="108.0",
            volume="20.25",
        ),
        _make_1m_candle(
            open_time=base_time + timedelta(minutes=2),
            open_price="108.0",
            high_price="109.0",
            low_price="95.0",  # Lowest
            close_price="97.0",
            volume="15.0",
        ),
        _make_1m_candle(
            open_time=base_time + timedelta(minutes=3),
            open_price="97.0",
            high_price="102.0",
            low_price="96.5",
            close_price="101.0",
            volume="8.75",
        ),
        _make_1m_candle(
            open_time=base_time + timedelta(minutes=4),
            open_price="101.0",
            high_price="103.0",
            low_price="100.0",
            close_price="102.5",  # Final close
            volume="5.5",
        ),
    ]

    result = resample_candles(candles=candles, target_interval=Interval.M5)
    assert len(result) == 1
    candle = result[0]

    assert candle.symbol == "BTCUSDT"
    assert candle.interval == Interval.M5
    assert candle.open_time == base_time
    assert candle.close_time == base_time + timedelta(minutes=5)
    assert candle.open_price == Decimal("100.0")
    assert candle.high_price == Decimal("110.0")
    assert candle.low_price == Decimal("95.0")
    assert candle.close_price == Decimal("102.5")
    # Volume: 10.5 + 20.25 + 15.0 + 8.75 + 5.5 = 60.0
    assert candle.volume == Decimal("60.0")


def test_resample_closed_only_drops_trailing_in_progress() -> None:
    """When closed_only=True, incomplete trailing bucket is dropped."""
    base_time = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    # 7 candles: 5 complete the 12:00-12:05 bucket, 2 enter the 12:05-12:10 bucket
    candles = [
        _make_1m_candle(
            open_time=base_time + timedelta(minutes=i),
            open_price="100",
            high_price="105",
            low_price="95",
            close_price="102",
            volume="1",
        )
        for i in range(7)
    ]

    # closed_only=True: only the first 5m bucket is emitted
    closed_result = resample_candles(
        candles=candles,
        target_interval=Interval.M5,
        closed_only=True,
    )
    assert len(closed_result) == 1
    assert closed_result[0].open_time == base_time

    # closed_only=False: both buckets are emitted
    all_result = resample_candles(
        candles=candles,
        target_interval=Interval.M5,
        closed_only=False,
    )
    assert len(all_result) == 2
    assert all_result[0].open_time == base_time
    assert all_result[1].open_time == base_time + timedelta(minutes=5)
    assert all_result[1].volume == Decimal("2")


def test_resample_min_candles_per_bucket_filtering() -> None:
    """min_candles_per_bucket skips buckets without sufficient coverage."""
    base_time = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    # Bucket 1: 5 candles (minutes 0 to 4)
    # Bucket 2: only 2 candles (minutes 5 and 6)
    # We close at minute 10 by providing minute 9
    candles = [
        _make_1m_candle(
            open_time=base_time + timedelta(minutes=i),
            open_price="100",
            high_price="105",
            low_price="95",
            close_price="102",
            volume="1",
        )
        for i in (0, 1, 2, 3, 4, 5, 6, 9)
    ]

    result = resample_candles(
        candles=candles,
        target_interval=Interval.M5,
        closed_only=True,
        min_candles_per_bucket=5,
    )
    # Only bucket 1 has >= 5 candles; bucket 2 has only 3 candles (5, 6, 9)
    assert len(result) == 1
    assert result[0].open_time == base_time


def test_resample_1m_to_1h_alignment() -> None:
    """Resampling 60 1m candles into 1h aligns to the top of the hour."""
    base_time = datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)
    candles = [
        _make_1m_candle(
            open_time=base_time + timedelta(minutes=i),
            open_price=f"{1000 + i}",
            high_price=f"{1010 + i}",
            low_price=f"{990 + i}",
            close_price=f"{1005 + i}",
            volume="2.5",
        )
        for i in range(60)
    ]

    result = resample_candles(candles=candles, target_interval=Interval.H1)
    assert len(result) == 1
    h1 = result[0]
    assert h1.interval == Interval.H1
    assert h1.open_time == base_time
    assert h1.close_time == base_time + timedelta(hours=1)
    assert h1.open_price == Decimal("1000")
    assert h1.close_price == Decimal("1064")
    assert h1.volume == Decimal("150.0")


def test_resample_validation_errors() -> None:
    """Invalid configurations raise ValueError."""
    base_time = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    c1 = _make_1m_candle(
        open_time=base_time,
        open_price="100",
        high_price="101",
        low_price="99",
        close_price="100",
        volume="1",
    )

    # 1. Downsampling error
    c_5m = Candle(
        symbol="BTCUSDT",
        interval=Interval.M5,
        open_time=base_time,
        close_time=base_time + timedelta(minutes=5),
        open_price=Decimal("100"),
        high_price=Decimal("101"),
        low_price=Decimal("99"),
        close_price=Decimal("100"),
        volume=Decimal("1"),
    )
    with pytest.raises(ValueError, match="Cannot downsample"):
        resample_candles(candles=[c_5m], target_interval=Interval.M1)

    # 2. Mixed symbols error
    c_eth = Candle(
        symbol="ETHUSDT",
        interval=Interval.M1,
        open_time=base_time + timedelta(minutes=1),
        close_time=base_time + timedelta(minutes=2),
        open_price=Decimal("100"),
        high_price=Decimal("101"),
        low_price=Decimal("99"),
        close_price=Decimal("100"),
        volume=Decimal("1"),
    )
    with pytest.raises(ValueError, match="Mixed symbols"):
        resample_candles(candles=[c1, c_eth], target_interval=Interval.M5)

    # 3. Mixed intervals error
    with pytest.raises(ValueError, match="Mixed intervals"):
        resample_candles(candles=[c1, c_5m], target_interval=Interval.M15)

    # 4. Timezone naive error
    c_naive = Candle(
        symbol="BTCUSDT",
        interval=Interval.M1,
        open_time=datetime(2026, 9, 1, 10, 0),  # Naive
        close_time=datetime(2026, 9, 1, 10, 1),
        open_price=Decimal("100"),
        high_price=Decimal("101"),
        low_price=Decimal("99"),
        close_price=Decimal("100"),
        volume=Decimal("1"),
    )
    with pytest.raises(ValueError, match="must be timezone-aware"):
        resample_candles(candles=[c_naive], target_interval=Interval.M5)

    # 5. Invalid min_candles_per_bucket
    with pytest.raises(ValueError, match="min_candles_per_bucket must be at least 1"):
        resample_candles(
            candles=[c1], target_interval=Interval.M5, min_candles_per_bucket=0
        )
