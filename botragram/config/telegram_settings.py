"""
Botragram

Description:
    Telegram settings model.

Python:
    3.14+
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TelegramSettings:
    """Telegram settings container."""

    token: str = ""
    chat_id: str = ""
