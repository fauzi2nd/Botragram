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
    "MENU_ACTIVITY",
    "MENU_CONFIGURATION",
    "MENU_DASHBOARD",
    "MENU_HOME",
    "MENU_STATUS",
    "MENU_POSITIONS",
    "MENU_MARKET",
    "MENU_MARKET_OVERVIEW",
    "MENU_ORDERS",
    "MENU_BALANCE",
    "MENU_HISTORY",
    "MENU_SETTINGS",
    "MENU_EXCHANGE",
    "MENU_INTERVAL",
    "MENU_STRATEGY",
    "MENU_STREAM",
    "MENU_START",
    "MENU_PAUSE",
    "MENU_TEST",
    "MENU_STOP",
    "MENU_TRADING",
    "TELEGRAM_MARKET_SYMBOLS",
    "TELEGRAM_INTERVALS",
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

MENU_DASHBOARD: str = "📊 Dashboard"
MENU_TRADING: str = "🤖 Trading"
MENU_CONFIGURATION: str = "⚙️ Configuration"
MENU_ACTIVITY: str = "🗂 Activity"
MENU_HOME: str = "🏠 Home"

# =============================================================================
# Main Menu
# =============================================================================

MENU_STATUS: str = "📊 Status"
MENU_POSITIONS: str = "📋 Positions"
MENU_MARKET: str = "🔎 Select Market"
MENU_MARKET_OVERVIEW: str = "📈 Market Overview"
MENU_ORDERS: str = "📑 Orders"
MENU_BALANCE: str = "💰 Balance"
MENU_HISTORY: str = "📜 History"
MENU_SETTINGS: str = "⚙️ Settings"
MENU_EXCHANGE: str = "🔄 Exchange"
MENU_INTERVAL: str = "⏱️ Interval"
MENU_STRATEGY: str = "🧠 Strategy"
MENU_STREAM: str = "📡 Stream"

MENU_START: str = "▶️ Start Bot"
MENU_PAUSE: str = "⏸️ Pause Bot"
MENU_TEST: str = "🧪 Test"
MENU_STOP: str = "⏹️ Stop Bot"

# Runtime-selectable markets deliberately use one quote asset so balance and
# risk calculations remain comparable across selections.
TELEGRAM_MARKET_SYMBOLS: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
)

TELEGRAM_INTERVALS: tuple[str, ...] = (
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "1d",
)
