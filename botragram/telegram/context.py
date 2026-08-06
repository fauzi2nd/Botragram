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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.models import Order, Position, Trade

__all__ = [
    "ALLOWED_CHAT_IDS_KEY",
    "BOT_CONTEXT_KEY",
    "BotContext",
    "BotQueryProvider",
    "BotRuntimeControl",
]


BOT_CONTEXT_KEY: Final[str] = "bot_context"
ALLOWED_CHAT_IDS_KEY: Final[str] = "allowed_chat_ids"


class BotQueryProvider(Protocol):
    """Read current application data for Telegram views."""

    async def get_positions(self) -> Sequence[Position]:
        """Return active positions."""
        ...

    async def get_available_balance(self) -> Decimal:
        """Return available paper balance."""
        ...

    async def get_latest_trades(self, *, limit: int) -> Sequence[Trade]:
        """Return recent persisted fills."""
        ...

    async def get_latest_orders(self, *, limit: int) -> Sequence[Order]:
        """Return recent persisted orders."""
        ...

    async def get_last_price(self) -> Decimal:
        """Return the latest available market price."""
        ...


class BotRuntimeControl(Protocol):
    """Pause and resume future trading cycles."""

    @property
    def is_paused(self) -> bool:
        """Return whether trading cycles are paused."""
        ...

    def pause(self) -> bool:
        """Pause and return whether state changed."""
        ...

    def resume(self) -> bool:
        """Resume and return whether state changed."""
        ...


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
    query_provider: BotQueryProvider | None = None
    runtime_control: BotRuntimeControl | None = None
