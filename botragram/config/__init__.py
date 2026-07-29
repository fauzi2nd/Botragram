"""
Botragram

Description:
    Configuration package for Botragram.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.config.app_settings import AppSettings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.config.telegram_settings import TelegramSettings

__all__ = ["AppSettings", "ExchangeSettings", "TelegramSettings"]
