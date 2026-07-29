"""
Botragram

Description:
    Telegram bot main runner class.

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
import logging
from typing import Any

# =============================================================================
# Third Party
# =============================================================================
from telegram.ext import ApplicationBuilder

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.telegram_settings import TelegramSettings
from botragram.engine.trading_engine import TradingEngine
from botragram.telegram.context import BotContext
from botragram.telegram.handlers import register_handlers

logger = logging.getLogger(__name__)

BOT_CONTEXT_KEY: str = "bot_context"


# =============================================================================
# Telegram Bot Class
# =============================================================================
class TelegramBot:
    """Telegram bot orchestrator for messaging and interaction."""

    def __init__(
        self,
        settings: TelegramSettings | None = None,
        engine: TradingEngine | None = None,
    ) -> None:
        """Initialize TelegramBot with settings and optional engine reference.

        Args:
            settings: Optional TelegramSettings object.
            engine: Optional TradingEngine to read live state from.
        """
        self._settings = settings or TelegramSettings()
        self._engine = engine
        self._app: Any = None

    def _build_bot_context(self) -> BotContext:
        """Build BotContext from live TradingEngine state.

        Returns:
            BotContext populated with current engine state.
        """
        if self._engine:
            return BotContext(
                is_running=self._engine.is_running,
                trade_mode=self._engine.trade_mode,
                symbol=self._engine.symbol,
                strategy_name=self._engine.strategy_name,
                exchange_type="BYBIT",
                last_price=self._engine.last_price,
                positions=[],
            )
        return BotContext()

    async def _refresh_context(self) -> None:
        """Refresh bot_data context from live engine state (called each tick)."""
        if self._app and self._engine:
            self._app.bot_data[BOT_CONTEXT_KEY] = self._build_bot_context()

    async def start(self) -> None:
        """Initialize, start Telegram bot, and begin long polling."""
        if not self._settings.enabled or not self._settings.bot_token:
            logger.info("Telegram bot is disabled or bot token is empty")
            return

        app = ApplicationBuilder().token(self._settings.bot_token).build()
        register_handlers(app)

        # Seed initial BotContext into bot_data
        app.bot_data[BOT_CONTEXT_KEY] = self._build_bot_context()

        await app.initialize()
        await app.start()
        if app.updater:
            await app.updater.start_polling()

        self._app = app
        logger.info("Telegram bot initialized and long polling started successfully")

    async def sync_engine_state(self) -> None:
        """Synchronize live engine state into bot_data (call from main loop)."""
        await self._refresh_context()

    async def stop(self) -> None:
        """Stop Telegram bot polling and shutdown application."""
        if self._app:
            if self._app.updater and self._app.updater.is_running:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped gracefully")
