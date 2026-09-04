"""
Botragram

Description:
    Backfill and gap-filler command parsing, composition, and execution.

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
import argparse
import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, time, timezone
from pathlib import Path
from time import monotonic
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config import Settings
from botragram.constants import (
    BINANCE_FUTURES_REST_BASE_URL,
    BINANCE_REST_BASE_URL,
    BYBIT_REST_BASE_URL,
    BYBIT_TESTNET_REST_BASE_URL,
)
from botragram.enums import ExchangeType, Interval, MarketType
from botragram.exchanges import ExchangeFactory
from botragram.exchanges.base import BaseStreamClient
from botragram.models import BackfillRequest, BackfillResult, Candle, Ticker
from botragram.services import CandleSyncService, MarketService
from botragram.storage.sqlite import (
    SQLiteCandleRepository,
    SQLiteDatabase,
    SQLiteMigrationManager,
)

__all__ = [
    "format_backfill_report",
    "is_backfill_command",
    "parse_backfill_request",
    "run_backfill_command",
]

# =============================================================================
# Constants
# =============================================================================
_BACKFILL_COMMAND: Final[str] = "backfill"


# =============================================================================
# Null Stream Client for REST-only operations
# =============================================================================
class _NullStreamClient(BaseStreamClient):
    """Stub stream client when only REST transport is required."""

    @property
    def is_connected(self) -> bool:
        return True

    async def connect(self) -> None:
        pass

    async def stream_ticker(self, *, symbol: str) -> AsyncIterator[Ticker]:
        if False:
            yield  # type: ignore[misc]

    async def stream_candles(
        self, *, symbol: str, interval: Interval
    ) -> AsyncIterator[Candle]:
        if False:
            yield  # type: ignore[misc]

    async def unsubscribe(self, *, symbol: str) -> None:
        pass

    async def close(self) -> None:
        pass


# =============================================================================
# Command Functions
# =============================================================================
def is_backfill_command(arguments: Sequence[str]) -> bool:
    """Return whether command-line arguments request candle backfill."""
    return bool(arguments) and arguments[0].strip().lower() == _BACKFILL_COMMAND


def parse_backfill_request(
    *,
    arguments: Sequence[str],
) -> BackfillRequest:
    """Parse command-line arguments into a validated BackfillRequest."""
    parser = argparse.ArgumentParser(
        prog="python main.py backfill",
        description=(
            "Synchronize and backfill candlestick market data "
            "into local SQLite storage."
        ),
    )
    parser.add_argument(
        "command",
        choices=(_BACKFILL_COMMAND,),
        help="Command name",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="",
        help="Comma-separated trading symbols (e.g. BTCUSDT,ETHUSDT)",
    )
    parser.add_argument(
        "--universe",
        type=int,
        default=None,
        help="Sync top N volume-ranked active symbols",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="1m",
        help="Candlestick timeframe (default: 1m)",
    )
    parser.add_argument(
        "--market-type",
        type=str,
        choices=("spot", "futures"),
        default="futures",
        help="Market type (default: futures)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Optional start date (YYYY-MM-DD) in UTC",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Run continuous periodic synchronization daemon",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=300,
        help="Delay in seconds between sync cycles when --watch is enabled",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Maximum parallel download requests (default: 3)",
    )
    parser.add_argument(
        "--database-path",
        type=str,
        default=None,
        help="Optional custom SQLite database file path",
    )

    parsed = parser.parse_args(args=list(arguments))

    # Parse symbols
    raw_symbols = parsed.symbols.strip()
    symbols_tuple = (
        tuple(s.strip().upper() for s in raw_symbols.split(",") if s.strip())
        if raw_symbols
        else ()
    )

    # Parse interval
    interval_value = parsed.interval.strip().lower()
    interval_match = next(
        (i for i in Interval if i.value.lower() == interval_value),
        None,
    )
    if interval_match is None:
        raise ValueError(f"Unsupported interval: {parsed.interval!r}")

    # Parse market type
    market_type = (
        MarketType.FUTURES
        if parsed.market_type.strip().lower() == "futures"
        else MarketType.SPOT
    )

    # Parse start time
    start_time: datetime | None = None
    if parsed.start:
        parsed_date = datetime.strptime(parsed.start.strip(), "%Y-%m-%d").date()
        start_time = datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)

    return BackfillRequest(
        symbols=symbols_tuple,
        universe_size=parsed.universe,
        interval=interval_match,
        market_type=market_type,
        start_time=start_time,
        watch=parsed.watch,
        watch_interval_seconds=parsed.interval_seconds,
        concurrency=parsed.concurrency,
        database_path=parsed.database_path,
    )


async def run_backfill_command(
    *,
    settings: Settings,
    request: BackfillRequest,
    stop_event: asyncio.Event | None = None,
) -> BackfillResult:
    """Execute backfill request against exchange REST API and SQLite database."""
    target_db_path = (
        Path(request.database_path)
        if request.database_path is not None
        else settings.app.database_path
    )
    target_db_path.parent.mkdir(parents=True, exist_ok=True)

    database = SQLiteDatabase(database_path=target_db_path)
    await database.connect()

    exchange_type = settings.exchange.exchange
    if exchange_type is ExchangeType.BYBIT:
        rest_base_url = (
            BYBIT_TESTNET_REST_BASE_URL
            if settings.exchange.testnet
            else BYBIT_REST_BASE_URL
        )
    else:
        rest_base_url = (
            BINANCE_FUTURES_REST_BASE_URL
            if request.market_type is MarketType.FUTURES
            else BINANCE_REST_BASE_URL
        )

    rest_client = ExchangeFactory.create_rest_client(
        exchange_type=exchange_type,
        base_url=rest_base_url,
    )
    exchange_client = ExchangeFactory.create_exchange_client(
        exchange_type=exchange_type,
        rest_client=rest_client,
        market_type=request.market_type,
    )

    await exchange_client.connect()
    try:
        await SQLiteMigrationManager(database=database).initialize()
        repo = SQLiteCandleRepository(database=database)

        stream_client = _NullStreamClient()
        market_service = MarketService(
            exchange_client=exchange_client,
            stream_client=stream_client,
            candle_repository=repo,
        )
        sync_service = CandleSyncService(
            market_service=market_service,
            candle_repository=repo,
        )

        async def _resolve_symbols() -> Sequence[str]:
            if request.universe_size is not None and request.universe_size > 0:
                entries = await market_service.get_market_universe(
                    quote_asset=settings.market.quote_asset,
                )
                return tuple(e.symbol for e in entries[: request.universe_size])
            return request.symbols

        if request.watch:
            await sync_service.run_periodic_sync(
                symbols_provider=_resolve_symbols,
                interval=request.interval,
                interval_seconds=request.watch_interval_seconds,
                stop_event=stop_event,
                concurrency=request.concurrency,
            )
            return BackfillResult(
                symbol_counts={},
                total_candles=0,
                duration_seconds=0.0,
                venue_name=f"{exchange_type.value.title()} (watch mode stopped)",
            )

        start_timer = monotonic()
        target_symbols = await _resolve_symbols()
        summary = await sync_service.sync_symbols(
            symbols=target_symbols,
            interval=request.interval,
            start_time=request.start_time,
            concurrency=request.concurrency,
        )
        elapsed = monotonic() - start_timer
        total = sum(summary.values())

        venue_title = exchange_type.value.title()
        net_type = "Testnet" if settings.exchange.testnet else "Mainnet"
        return BackfillResult(
            symbol_counts=summary,
            total_candles=total,
            duration_seconds=elapsed,
            venue_name=f"{venue_title} {net_type}",
        )
    finally:
        await exchange_client.close()
        await database.close()


def format_backfill_report(
    *,
    result: BackfillResult,
    request: BackfillRequest,
) -> str:
    """Format human-readable CLI report of completed backfill execution."""
    lines = [
        "",
        "BOTRAGRAM CANDLESTICK BACKFILL & SYNC",
        "=" * 72,
        f"Venue        : {result.venue_name} {request.market_type.value.upper()}",
        f"Interval     : {request.interval.value}",
        f"Symbols      : {len(result.symbol_counts)} total",
        f"Total Candles: {result.total_candles:,}",
        f"Duration     : {result.duration_seconds:.2f}s",
        "-" * 72,
        "SYNC SUMMARY PER SYMBOL",
    ]

    active_synced = [
        (sym, count) for sym, count in result.symbol_counts.items() if count > 0
    ]
    if active_synced:
        for idx, (sym, count) in enumerate(active_synced[:50], start=1):
            lines.append(f"  {idx:3d}. {sym:<14} : +{count:,} candles saved")
        if len(active_synced) > 50:
            lines.append(f"  ... and {len(active_synced) - 50} more symbols")
    else:
        lines.append("  All symbols were already up-to-date! (0 new candles required)")

    lines.append("=" * 72)
    return "\n".join(lines)
