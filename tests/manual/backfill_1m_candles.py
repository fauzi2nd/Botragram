"""
Botragram

Description:
    Manual script to backfill 1-minute historical candles from 2026-09-01 UTC
    to current time for top 150 volume symbols on Bybit Linear.

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
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app import SettingsManager
from botragram.enums import Interval
from botragram.exchanges.bybit import (
    BybitExchangeMapper,
    BybitFuturesExchangeClient,
    BybitRestClient,
)
from botragram.models import Candle
from botragram.storage.sqlite import SQLiteCandleRepository, SQLiteDatabase

# =============================================================================
# Constants
# =============================================================================
_TARGET_START: datetime = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
_TOP_COINS_COUNT: int = 150
_PAGE_LIMIT: int = 1000
_PACING_DELAY_SECONDS: float = 0.05


# =============================================================================
# Backfill Logic
# =============================================================================
async def backfill_symbol(
    *,
    rest_client: BybitRestClient,
    mapper: BybitExchangeMapper,
    candle_repository: SQLiteCandleRepository,
    symbol: str,
    start_time: datetime,
    end_time: datetime,
) -> int:
    """Fetch and persist 1m candles for one symbol from start_time to end_time."""
    current_end = end_time
    total_saved = 0

    while current_end > start_time:
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(current_end.timestamp() * 1000)

        response = await rest_client.get(
            "/v5/market/kline",
            params={
                "category": "linear",
                "symbol": symbol,
                "interval": "1",
                "start": start_ms,
                "end": end_ms,
                "limit": _PAGE_LIMIT,
            },
            authenticated=False,
        )
        if not isinstance(response, dict):
            break
        payload: dict[str, Any] = response

        raw_list = payload.get("result", {}).get("list", [])
        if not raw_list:
            break

        candles: list[Candle] = []
        for raw in raw_list:
            candle = mapper.map_candle(
                tuple(raw),
                symbol=symbol,
                interval=Interval.M1,
            )
            candles.append(candle)

        # Bybit returns newest first; sort ascending
        candles.sort(key=lambda c: c.open_time)

        # Persist batch
        await candle_repository.save_many(candles=candles)
        total_saved += len(candles)

        oldest_candle_time = candles[0].open_time
        if oldest_candle_time <= start_time or len(candles) < _PAGE_LIMIT:
            break

        current_end = oldest_candle_time - timedelta(minutes=1)
        await asyncio.sleep(_PACING_DELAY_SECONDS)

    return total_saved


async def main() -> None:
    """Initialize isolated DB and REST client, fetch top symbols, and backfill."""
    settings = SettingsManager().load()
    database = SQLiteDatabase(database_path=settings.app.database_path)
    await database.connect()
    candle_repository = SQLiteCandleRepository(database=database)

    exchange = settings.exchange
    if exchange.demo:
        rest_base_url = "https://api-demo.bybit.com"
    elif exchange.testnet:
        rest_base_url = "https://api-testnet.bybit.com"
    else:
        rest_base_url = "https://api.bybit.com"

    rest_client = BybitRestClient(
        base_url=rest_base_url,
        api_key=exchange.api_key,
        api_secret=exchange.api_secret,
    )
    mapper = BybitExchangeMapper()
    exchange_client = BybitFuturesExchangeClient(
        rest=rest_client,
        mapper=mapper,
    )
    await exchange_client.connect()

    now = datetime.now(UTC)
    print("=== Starting 1m Candle Backfill ===")
    print(f"Time Range: {_TARGET_START.isoformat()} to {now.isoformat()}")
    print(f"Target Coin Count: {_TOP_COINS_COUNT}")
    print(f"Database: {settings.app.database_path}\n")

    quote_asset = settings.market.quote_asset
    print(f"Fetching market universe for quote asset '{quote_asset}'...")
    entries = await exchange_client.get_market_universe(quote_asset=quote_asset)
    ranked_symbols = [entry.symbol for entry in entries[:_TOP_COINS_COUNT]]

    print(f"Retrieved {len(ranked_symbols)} symbols. Starting download...\n")

    success_count = 0
    failed_symbols: list[tuple[str, str]] = []

    for index, symbol in enumerate(ranked_symbols, start=1):
        try:
            saved = await backfill_symbol(
                rest_client=rest_client,
                mapper=mapper,
                candle_repository=candle_repository,
                symbol=symbol,
                start_time=_TARGET_START,
                end_time=now,
            )
            total_db = await candle_repository.count(
                symbol=symbol,
                interval=Interval.M1,
            )
            print(
                f"[{index}/{len(ranked_symbols)}] {symbol}: "
                f"+{saved} candles (Total in DB: {total_db})"
            )
            success_count += 1
        except Exception as error:
            print(
                f"[{index}/{len(ranked_symbols)}] {symbol}: FAILED ({error})",
                file=sys.stderr,
            )
            failed_symbols.append((symbol, str(error)))

        await asyncio.sleep(_PACING_DELAY_SECONDS)

    print("\n=== Backfill Summary ===")
    print(f"Total Symbols Attempted: {len(ranked_symbols)}")
    print(f"Successfully Backfilled: {success_count}")
    if failed_symbols:
        print(f"Failed Symbols ({len(failed_symbols)}):")
        for sym, err in failed_symbols:
            print(f"  - {sym}: {err}")
    print("Done!")

    await exchange_client.close()
    await database.close()


if __name__ == "__main__":
    asyncio.run(main())
