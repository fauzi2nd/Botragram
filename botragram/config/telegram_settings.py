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
from botragram.constants import DEFAULT_PARSE_MODE

__all__ = [
    "TelegramSettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class TelegramSettings:
    """Telegram bot access and notification settings."""

    bot_token: str = ""
    allowed_chat_ids: list[int] = field(default_factory=list[int])
    enabled: bool = False
    parse_mode: str = DEFAULT_PARSE_MODE
