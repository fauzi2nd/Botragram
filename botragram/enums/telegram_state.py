"""
Botragram

Description:
    Telegram bot state enumeration.

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
from enum import Enum, unique


# =============================================================================
# Enums
# =============================================================================
@unique
class TelegramState(str, Enum):
    """State of Telegram bot user interaction."""

    IDLE = "IDLE"
    AWAITING_INPUT = "AWAITING_INPUT"
    MONITORING = "MONITORING"
