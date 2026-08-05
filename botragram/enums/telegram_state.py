"""
Botragram

Description:
    Telegram conversation state enumeration.

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
from enum import unique

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.base import BaseEnum

__all__ = ["TelegramState"]


# =============================================================================
# Enums
# =============================================================================
@unique
class TelegramState(BaseEnum):
    """Supported Telegram conversation states."""

    IDLE = "idle"
    WAITING_INPUT = "waiting_input"

    CONFIGURING = "configuring"

    RUNNING = "running"
