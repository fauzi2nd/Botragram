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

    async def start(self) -> None:
        """Initialize and start Telegram bot if enabled."""
        if not self._settings.enabled or not self._settings.bot_token:
            logger.info("Telegram bot is disabled or bot token is empty")
            return

        app = ApplicationBuilder().token(self._settings.bot_token).build()
        register_handlers(app)
        await app.initialize()
        await app.start()
        logger.info("Telegram bot initialized and started successfully")
