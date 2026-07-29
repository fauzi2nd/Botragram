"""
Botragram

Description:
    Shared bot context for passing live engine state to Telegram handlers.

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
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.exchanges.base.mapper import PositionInfo


# =============================================================================
# Bot Context Dataclass
# =============================================================================
@dataclass
class BotContext:
    """Shared context object injected into Telegram bot_data."""

    is_running: bool = False
    trade_mode: str = "PAPER"
    symbol: str = "BTCUSDT"
    strategy_name: str = "EMA_CROSS"
    exchange_type: str = "BYBIT"
    last_price: Decimal = field(default_factory=lambda: Decimal("0"))
    positions: list[PositionInfo] = field(default_factory=lambda: list[PositionInfo]())
