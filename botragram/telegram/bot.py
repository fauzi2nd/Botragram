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
from botragram.models import Notification
from botragram.telegram.context import (
    ALLOWED_CHAT_IDS_KEY,
    BOT_CONTEXT_KEY,
    BotContext,
)
from botragram.telegram.handlers import register_handlers

__all__ = [
    "TelegramBot",
]


# =============================================================================
# Constants
# =============================================================================
_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


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

    @property
    def is_running(self) -> bool:
        """Return whether Telegram polling resources are active."""
        return self._app is not None

    async def start(self) -> None:
        """Initialize Telegram resources and begin long polling."""
        if (
            not self._settings.enabled
            or not self._settings.bot_token
            or not self._settings.allowed_chat_ids
        ):
            _LOGGER.info(
                "Telegram bot is disabled or its token/chat allow-list is empty"
            )
            return

        app = ApplicationBuilder().token(self._settings.bot_token).build()
        register_handlers(app)
        app.bot_data[BOT_CONTEXT_KEY] = self._context
        app.bot_data[ALLOWED_CHAT_IDS_KEY] = frozenset(self._settings.allowed_chat_ids)
        updater = app.updater
        initialized = False
        started = False

        try:
            await app.initialize()
            initialized = True
            await app.start()
            started = True
            await app.bot.set_my_commands(
                [
                    BotCommand("start", "Mulai bot dan tampilkan menu utama"),
                    BotCommand("status", "Lihat status bot dan pasar"),
                    BotCommand("positions", "Lihat posisi trading aktif"),
                    BotCommand("balance", "Lihat saldo paper tersedia"),
                    BotCommand("history", "Lihat riwayat paper trading"),
                    BotCommand("market", "Pilih pair crypto saat bot dijeda"),
                    BotCommand("strategy", "Pilih strategy saat bot dijeda"),
                    BotCommand("interval", "Pilih candle interval saat bot dijeda"),
                    BotCommand("stream", "Kelola market ticker stream"),
                    BotCommand("pause", "Jeda siklus trading baru"),
                    BotCommand("resume", "Lanjutkan siklus trading"),
                    BotCommand("settings", "Lihat pengaturan bot"),
                    BotCommand("exchange", "Lihat exchange aktif"),
                    BotCommand("stop", "Lihat status penghentian bot"),
                ]
            )

            if updater is not None:
                await updater.start_polling()
        except BaseException:
            if updater is not None and updater.running:
                await updater.stop()

            if started:
                await app.stop()

            if initialized:
                await app.shutdown()

            raise

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
            self._app.bot_data[BOT_CONTEXT_KEY] = context

    async def publish(
        self,
        *,
        notification: Notification,
    ) -> None:
        """Send one notification to every configured chat safely."""
        if (
            not self._settings.enabled
            or not self._settings.bot_token
            or not self._settings.allowed_chat_ids
        ):
            return

        app = self._app

        if app is None:
            _LOGGER.warning(
                "Telegram notification skipped because the bot is not started: %s",
                notification.title,
            )
            return

        for chat_id in self._settings.allowed_chat_ids:
            try:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=notification.message,
                    parse_mode=self._settings.parse_mode,
                )
            except Exception:
                _LOGGER.exception(
                    "Telegram notification delivery failed: title=%s chat_id=%d",
                    notification.title,
                    chat_id,
                )

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
