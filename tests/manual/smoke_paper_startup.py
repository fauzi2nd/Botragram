"""Bounded real-network smoke test for safe paper-mode startup."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from botragram.app import DependencyProvider, SettingsManager
from botragram.enums import TradeMode


async def _run_smoke() -> None:
    """Start real public dependencies, probe health, then shut down safely."""
    settings = SettingsManager().load()

    if settings.app.trade_mode is not TradeMode.PAPER:
        raise RuntimeError("Smoke startup is restricted to PAPER trade mode")

    with TemporaryDirectory() as temporary_directory:
        provider = DependencyProvider(
            database_path=Path(temporary_directory) / "smoke.db",
            settings=settings,
        )

        try:
            await provider.initialize()
            health = await provider.health_service.check()
            ticker = await provider.market_service.get_ticker(
                symbol=settings.market.symbol,
            )
            balance = await provider.paper_trading_service.get_available_balance()
            await provider.runtime_reporter.on_started()

            print("Paper startup smoke test passed")
            print(f"Database healthy: {health.database_healthy}")
            print(f"Exchange healthy: {health.exchange_healthy}")
            print(f"Telegram running: {provider.telegram_bot.is_running}")
            print(f"Ticker symbol: {ticker.symbol}")
            print(f"Ticker positive: {ticker.last_price > 0}")
            print(f"Paper balance positive: {balance > 0}")
        finally:
            await provider.close()


async def main() -> None:
    """Run the smoke test under a strict global timeout."""
    async with asyncio.timeout(30):
        await _run_smoke()


if __name__ == "__main__":
    asyncio.run(main())
