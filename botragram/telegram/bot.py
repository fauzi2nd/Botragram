"""
Botragram

Description:
    Telegram bot lifecycle adapter.

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
import logging
from typing import Any, Final

# =============================================================================
# Third-Party Imports
# =============================================================================
from telegram import BotCommand
from telegram.ext import ApplicationBuilder

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.telegram_settings import TelegramSettings
from botragram.telegram.context import BotContext
from botragram.telegram.handlers import register_handlers

__all__ = [
    "TelegramBot",
]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_BOT_CONTEXT_KEY: Final[str] = "bot_context"


# =============================================================================
# Telegram Bot
# =============================================================================
class TelegramBot:
    """Own Telegram polling resources and displayed application context."""

    __slots__ = (
        "_app",
        "_context",
        "_settings",
    )

    def __init__(
        self,
        *,
        settings: TelegramSettings | None = None,
        context: BotContext | None = None,
    ) -> None:
        """Initialize the Telegram adapter.

        Args:
            settings: Telegram access and lifecycle settings.
            context: Initial state displayed by handlers.
        """
        self._settings = settings if settings is not None else TelegramSettings()
        self._context = context if context is not None else BotContext()
        self._app: Any = None

    async def start(self) -> None:
        """Initialize Telegram resources and begin long polling."""
        if not self._settings.enabled or not self._settings.bot_token:
            _LOGGER.info("Telegram bot is disabled or bot token is empty")
            return

        app = ApplicationBuilder().token(self._settings.bot_token).build()
        register_handlers(app)
        app.bot_data[_BOT_CONTEXT_KEY] = self._context

        await app.initialize()
        await app.start()
        await app.bot.set_my_commands(
            [
                BotCommand("start", "Mulai bot dan tampilkan menu utama"),
                BotCommand("status", "Lihat status bot dan pasar"),
                BotCommand("positions", "Lihat posisi trading aktif"),
                BotCommand("settings", "Lihat pengaturan bot"),
                BotCommand("exchange", "Lihat exchange aktif"),
                BotCommand("stop", "Lihat status penghentian bot"),
            ]
        )

        updater = app.updater

        if updater is not None:
            await updater.start_polling()

        self._app = app
        _LOGGER.info("Telegram bot polling started")

    async def sync_context(
        self,
        *,
        context: BotContext,
    ) -> None:
        """Replace state displayed by Telegram handlers."""
        self._context = context

        if self._app is not None:
            self._app.bot_data[_BOT_CONTEXT_KEY] = context

    async def stop(self) -> None:
        """Stop Telegram polling and release owned resources."""
        app = self._app
        self._app = None

        if app is None:
            return

        updater = app.updater

        if updater is not None and updater.running:
            await updater.stop()

        await app.stop()
        await app.shutdown()
        _LOGGER.info("Telegram bot stopped")
