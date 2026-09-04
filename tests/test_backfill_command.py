"""
Botragram

Description:
    Unit tests for backfill command parser and report formatting.

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
from datetime import datetime, timezone

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.backfill_command import (
    format_backfill_report,
    is_backfill_command,
    parse_backfill_request,
)
from botragram.enums import Interval, MarketType
from botragram.models import BackfillRequest, BackfillResult

__all__ = ()


def test_is_backfill_command() -> None:
    """Detect backfill command arguments correctly."""
    assert is_backfill_command(("backfill", "--symbols", "BTCUSDT")) is True
    assert is_backfill_command(("backtest", "--symbol", "BTCUSDT")) is False
    assert is_backfill_command(()) is False


def test_parse_backfill_request_explicit_symbols() -> None:
    """Parse explicit symbol list and optional arguments."""
    req = parse_backfill_request(
        arguments=(
            "backfill",
            "--symbols",
            "btcusdt, ethusdt",
            "--interval",
            "1m",
            "--market-type",
            "futures",
            "--start",
            "2026-09-01",
            "--concurrency",
            "5",
            "--database-path",
            "data/custom.db",
        )
    )

    assert req.symbols == ("BTCUSDT", "ETHUSDT")
    assert req.universe_size is None
    assert req.interval is Interval.M1
    assert req.market_type is MarketType.FUTURES
    assert req.start_time == datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    assert req.concurrency == 5
    assert req.database_path == "data/custom.db"
    assert req.watch is False


def test_parse_backfill_request_universe_and_watch() -> None:
    """Parse discovery universe size and watch flags."""
    req = parse_backfill_request(
        arguments=(
            "backfill",
            "--universe",
            "150",
            "--watch",
            "--interval-seconds",
            "600",
        )
    )

    assert req.universe_size == 150
    assert req.watch is True
    assert req.watch_interval_seconds == 600


def test_parse_backfill_request_invalid() -> None:
    """Raise ValueError when required inputs or boundaries are invalid."""
    with pytest.raises(ValueError, match="either explicit symbols or universe_size"):
        parse_backfill_request(arguments=("backfill",))

    with pytest.raises(ValueError, match="Unsupported interval"):
        parse_backfill_request(
            arguments=("backfill", "--symbols", "BTCUSDT", "--interval", "99x")
        )


def test_format_backfill_report() -> None:
    """Format human-readable CLI report."""
    req = BackfillRequest(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval=Interval.M1,
    )
    res = BackfillResult(
        symbol_counts={"BTCUSDT": 100, "ETHUSDT": 50},
        total_candles=150,
        duration_seconds=1.25,
        venue_name="Bybit Mainnet",
    )

    report = format_backfill_report(result=res, request=req)
    assert "BOTRAGRAM CANDLESTICK BACKFILL & SYNC" in report
    assert "Bybit Mainnet FUTURES" in report
    assert "Total Candles: 150" in report
    assert "BTCUSDT" in report
    assert "+100 candles saved" in report
