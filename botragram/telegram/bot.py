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
from botragram.telegram.handlers import register_handlers

logger = logging.getLogger(__name__)


# =============================================================================
# Telegram Bot Class
# =============================================================================
class TelegramBot:
    """Telegram bot orchestrator for messaging and interaction."""

    def __init__(self, settings: TelegramSettings | None = None) -> None:
        """Initialize TelegramBot with settings.

        Args:
            settings: Optional TelegramSettings object.
        """
        self._settings = settings or TelegramSettings()
        self._app: Any = None

    async def start(self) -> None:
        """Initialize, start Telegram bot, and begin long polling."""
        if not self._settings.enabled or not self._settings.bot_token:
            logger.info("Telegram bot is disabled or bot token is empty")
            return

        app = ApplicationBuilder().token(self._settings.bot_token).build()
        register_handlers(app)
        await app.initialize()
        await app.start()
        if app.updater:
            await app.updater.start_polling()

        self._app = app
        logger.info("Telegram bot initialized and long polling started successfully")

    async def stop(self) -> None:
        """Stop Telegram bot polling and shutdown application."""
        if self._app:
            if self._app.updater and self._app.updater.is_running:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped gracefully")
