"""
Botragram

Description:
    Telegram bot default constants.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

__all__ = [
    "DEFAULT_PARSE_MODE",
    "DEFAULT_MENU_COLUMNS",
    "CMD_START",
    "CMD_STATUS",
    "CMD_POSITIONS",
    "CMD_STOP",
    "CMD_SETTINGS",
    "MENU_STATUS",
    "MENU_POSITIONS",
    "MENU_MARKET",
    "MENU_ORDERS",
    "MENU_BALANCE",
    "MENU_HISTORY",
    "MENU_SETTINGS",
    "MENU_EXCHANGE",
    "MENU_STRATEGY",
    "MENU_STREAM",
    "MENU_START",
    "MENU_PAUSE",
    "MENU_TEST",
    "MENU_STOP",
]

# =============================================================================
# Telegram
# =============================================================================

DEFAULT_PARSE_MODE: str = "HTML"
DEFAULT_MENU_COLUMNS: int = 2

# =============================================================================
# Commands
# =============================================================================

CMD_START: str = "start"
CMD_STATUS: str = "status"
CMD_POSITIONS: str = "positions"
CMD_STOP: str = "stop"
CMD_SETTINGS: str = "settings"

# =============================================================================
# Main Menu
# =============================================================================

MENU_STATUS: str = "📊 Status"
MENU_POSITIONS: str = "📋 Positions"
MENU_MARKET: str = "📈 Market"
MENU_ORDERS: str = "📑 Orders"
MENU_BALANCE: str = "💰 Balance"
MENU_HISTORY: str = "📜 History"
MENU_SETTINGS: str = "⚙️ Settings"
MENU_EXCHANGE: str = "🔄 Exchange"
MENU_STRATEGY: str = "🧠 Strategy"
MENU_STREAM: str = "📡 Stream"

MENU_START: str = "▶️ Start Bot"
MENU_PAUSE: str = "⏸️ Pause Bot"
MENU_TEST: str = "🧪 Test"
MENU_STOP: str = "⏹️ Stop Bot"
