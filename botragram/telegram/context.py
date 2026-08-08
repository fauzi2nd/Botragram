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
from botragram.enums import ExchangeType, Interval, MarketType, StrategyType
from botragram.models import Order, Position, Trade

__all__ = [
    "ALLOWED_CHAT_IDS_KEY",
    "BOT_CONTEXT_KEY",
    "MARKET_SEARCH_PENDING_KEY",
    "BotContext",
    "BotQueryProvider",
    "BotMarketTypeSwitcher",
    "BotRuntimeControl",
]


BOT_CONTEXT_KEY: Final[str] = "bot_context"
ALLOWED_CHAT_IDS_KEY: Final[str] = "allowed_chat_ids"
MARKET_SEARCH_PENDING_KEY: Final[str] = "market_search_pending"


class BotQueryProvider(Protocol):
    """Read current application data for Telegram views."""

    async def get_positions(self) -> Sequence[Position]:
        """Return active positions."""
        ...

    async def get_trading_symbols(self) -> Sequence[str]:
        """Return exchange-supported active market symbols."""
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

    def is_stream_transport_connected(self) -> bool:
        """Return whether the exchange WebSocket transport is ready."""
        ...

    async def start_market_stream(self) -> bool:
        """Start ticker subscription for the selected symbol."""
        ...

    async def wait_for_first_stream_tick(
        self,
        *,
        timeout_seconds: float = 5.0,
    ) -> bool:
        """Wait briefly for the active subscription's first tick."""
        ...

    async def stop_market_stream(self) -> bool:
        """Stop the active ticker subscription."""
        ...


class BotMarketTypeSwitcher(Protocol):
    """Stage and commit safe exchange product restarts."""

    async def prepare(self, *, market_type: MarketType) -> bool:
        """Validate and stage a Spot or Futures switch."""
        ...

    def commit(self, *, market_type: MarketType) -> None:
        """Commit a prepared switch after its Telegram acknowledgement."""
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

    @property
    def symbol(self) -> str:
        """Return the symbol selected for future cycles."""
        ...

    @property
    def strategy_type(self) -> StrategyType:
        """Return the strategy selected for future cycles."""
        ...

    @property
    def stream_enabled(self) -> bool:
        """Return whether a market subscription is active."""
        ...

    @property
    def interval(self) -> Interval:
        """Return the interval selected for future cycles."""
        ...

    @property
    def market_type(self) -> MarketType:
        """Return the configured exchange product family."""
        ...

    def confirm_exchange(self, exchange_type: ExchangeType) -> bool:
        """Confirm the exchange connector loaded for this process."""
        ...

    def select_symbol(self, symbol: str) -> bool:
        """Select a trading symbol while paused."""
        ...

    def select_strategy(self, strategy_type: StrategyType) -> bool:
        """Select a strategy while paused."""
        ...

    def select_interval(self, interval: Interval) -> bool:
        """Select a candle interval while paused."""
        ...

    def get_missing_startup_requirements(self) -> tuple[str, ...]:
        """Return selections or stream state still blocking startup."""
        ...

    def get_missing_configuration_requirements(self) -> tuple[str, ...]:
        """Return manual selections required before stream startup."""
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
    market_type_switcher: BotMarketTypeSwitcher | None = None

    @property
    def market_type(self) -> MarketType:
        """Return the runtime market type or the safe Spot default."""
        control = self.runtime_control
        return control.market_type if control is not None else MarketType.SPOT
