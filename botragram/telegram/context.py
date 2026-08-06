"""
Botragram

Description:
    Shared state exposed to Telegram handlers.

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
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models import Position

__all__ = [
    "BotContext",
]


# =============================================================================
# Bot Context
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
)
class BotContext:
    """Store the application state displayed by Telegram handlers."""

    is_running: bool = False
    trade_mode: str = "PAPER"
    symbol: str = "BTCUSDT"
    strategy_name: str = "EMA_CROSS"
    exchange_type: str = "BINANCE"
    last_price: Decimal = Decimal("0")
    positions: tuple[Position, ...] = ()
