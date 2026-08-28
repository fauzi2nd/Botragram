"""
Botragram

Description:
    Telegram bot lifecycle adapter.

Python:
    3.14+
"""

from __future__ import annotations

import logging
from typing import Any, Final

from telegram import BotCommand
from telegram.ext import ApplicationBuilder

from botragram.config.telegram_settings import TelegramSettings
from botragram.models import ExecutionAuthorization, Notification
from botragram.telegram.context import (
    ALLOWED_CHAT_IDS_KEY,
    BOT_CONTEXT_KEY,
    BotContext,
)
from botragram.telegram.handlers import register_handlers
from botragram.telegram.keyboards import (
    get_execution_authorization_keyboard,
    get_main_menu_keyboard,
)
from botragram.telegram.messages import get_execution_authorization_message

__all__ = ["TelegramBot", "get_bot_commands"]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
_TRADING_MODE_SWITCHED_MESSAGE: Final[str] = "Trading Mode Switched"


def get_bot_commands() -> tuple[BotCommand, ...]:
    """Return the unique public Telegram command registry."""
    commands = (
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
        BotCommand("risklimits", "Lihat limit entry runtime"),
        BotCommand("setrisklimits", "Ubah limit runtime saat dijeda"),
        BotCommand("exitstatus", "Lihat status operator exit"),
        BotCommand("closeposition", "Tutup satu posisi saat PAUSED"),
        BotCommand("closeall", "Tutup semua posisi saat PAUSED"),
        BotCommand("closeandswitch", "Flatten lalu ganti trading mode"),
        BotCommand("confirmexit", "Konfirmasi operator exit"),
        BotCommand("cancelexit", "Batalkan konfirmasi operator exit"),
        BotCommand("settings", "Lihat pengaturan bot"),
        BotCommand("exchange", "Lihat exchange aktif"),
        BotCommand("stop", "Lihat status penghentian bot"),
    )
    names = tuple(command.command for command in commands)
    if len(names) != len(set(names)):
        raise RuntimeError("Telegram command registry contains duplicate commands")
    return commands


class TelegramBot:
    """Own Telegram polling resources and displayed application context."""

    __slots__ = ("_app", "_context", "_settings")

    def __init__(
        self,
        *,
        settings: TelegramSettings | None = None,
        context: BotContext | None = None,
    ) -> None:
        self._settings = settings if settings is not None else TelegramSettings()
        self._context = context if context is not None else BotContext()
        self._app: Any = None

    @property
    def is_running(self) -> bool:
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
            await app.bot.set_my_commands(get_bot_commands())
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

    async def sync_context(self, *, context: BotContext) -> None:
        self._context = context
        if self._app is not None:
            self._app.bot_data[BOT_CONTEXT_KEY] = context

    async def publish_home_menu_refresh(self) -> None:
        """Publish the persistent home menu for the current initialized context."""
        if (
            not self._settings.enabled
            or not self._settings.bot_token
            or not self._settings.allowed_chat_ids
        ):
            return
        app = self._app
        if app is None:
            _LOGGER.warning(
                "Telegram home-menu refresh skipped because the bot is not started"
            )
            return

        runtime_control = self._context.runtime_control
        reply_markup = get_main_menu_keyboard(
            execution_policy=self._context.execution_policy,
            is_paused=(runtime_control is None or runtime_control.is_paused),
        )
        for chat_id in self._settings.allowed_chat_ids:
            try:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=_TRADING_MODE_SWITCHED_MESSAGE,
                    parse_mode=self._settings.parse_mode,
                    reply_markup=reply_markup,
                )
            except Exception:
                _LOGGER.exception(
                    "Telegram home-menu refresh delivery failed: chat_id=%d",
                    chat_id,
                )

    async def publish(self, *, notification: Notification) -> None:
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

    async def publish_execution_authorization(
        self,
        *,
        authorization: ExecutionAuthorization,
    ) -> None:
        if (
            not self._settings.enabled
            or not self._settings.bot_token
            or not self._settings.allowed_chat_ids
        ):
            return
        app = self._app
        if app is None:
            _LOGGER.warning(
                "Telegram authorization notification skipped because the bot is not "
                "started: authorization_id=%s",
                authorization.authorization_id,
            )
            return

        message = get_execution_authorization_message(authorization)
        reply_markup = get_execution_authorization_keyboard(
            authorization.authorization_id,
        )
        for chat_id in self._settings.allowed_chat_ids:
            try:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=self._settings.parse_mode,
                    reply_markup=reply_markup,
                )
            except Exception:
                _LOGGER.exception(
                    "Telegram authorization delivery failed: authorization_id=%s "
                    "chat_id=%d",
                    authorization.authorization_id,
                    chat_id,
                )

    async def stop(self) -> None:
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
