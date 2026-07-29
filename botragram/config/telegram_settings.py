"""
Botragram

Description:
    Telegram bot configuration settings.

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
from dataclasses import dataclass, field

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.telegram import DEFAULT_PARSE_MODE


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(slots=True)
class TelegramSettings:
    """Telegram bot access and notification settings."""

    bot_token: str = ""
    allowed_chat_ids: list[int] = field(default_factory=list[int])
    enabled: bool = True
    parse_mode: str = DEFAULT_PARSE_MODE
