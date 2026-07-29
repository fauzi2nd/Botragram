"""
Botragram

Description:
    Main application orchestrator.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
import asyncio
import logging

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.settings_manager import SettingsManager
from botragram.app.startup import initialize_logging
from botragram.config.app_settings import AppSettings
from botragram.engine.trading_engine import TradingEngine
from botragram.exchanges.bybit.client import BybitClient
from botragram.telegram.bot import TelegramBot

logger = logging.getLogger("botragram")


# =============================================================================
# Application Orchestrator Class
# =============================================================================
class Application:
    """Main orchestrator for the Botragram trading bot application."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        settings_manager: SettingsManager | None = None,
    ) -> None:
        """Initialize main Application.

        Args:
            settings: Optional AppSettings instance.
            settings_manager: Optional SettingsManager instance.
        """
        self._manager = settings_manager or SettingsManager()
        self._settings = settings or self._manager.load_app_settings()

        # Components initialization
        ex_settings = self._manager.load_exchange_settings()
        mkt_settings = self._manager.load_market_settings()
        risk_settings = self._manager.load_risk_settings()
        strat_settings = self._manager.load_strategy_settings()
        tg_settings = self._manager.load_telegram_settings()

        exchange_client = BybitClient(
            api_key=ex_settings.api_key,
            api_secret=ex_settings.api_secret,
            testnet=ex_settings.testnet,
        )

        self._engine = TradingEngine(
            settings=self._settings,
            exchange_client=exchange_client,
            market_settings=mkt_settings,
            risk_settings=risk_settings,
            strategy_settings=strat_settings,
        )
        self._telegram_bot = TelegramBot(settings=tg_settings)

    @property
    def engine(self) -> TradingEngine:
        """Get active trading engine instance.

        Returns:
            TradingEngine instance.
        """
        return self._engine

    async def run(self) -> None:
        """Run application lifecycle and maintain main event loop."""
        initialize_logging()
        logger.info(f"Starting Botragram v{self._settings.version}...")
        await self._engine.start()
        await self._telegram_bot.start()
        logger.info("Botragram application started successfully. Press Ctrl+C to exit.")

        try:
            while self._engine.is_running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Shutdown signal received")
        finally:
            await self._engine.stop()
