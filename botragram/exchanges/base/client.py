"""
Botragram

Description:
    Base exchange client interface.

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
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, OrderSide, OrderType
from botragram.models import Account, Candle, Order, Position, Ticker, Trade

__all__ = [
    "BaseExchangeClient",
]


# =============================================================================
# Abstract Exchange Clients
# =============================================================================
class BaseExchangeClient(ABC):
    """Abstract interface implemented by exchange clients."""

    # =========================================================================
    # Lifecycle
    # =========================================================================

    @abstractmethod
    async def connect(self) -> None:
        """Initialize exchange connections and resources."""

    @abstractmethod
    async def close(self) -> None:
        """Close exchange connections and release resources."""

    @abstractmethod
    async def ping(self) -> bool:
        """Return whether the exchange is reachable."""

    # =========================================================================
    # Account and Market Data
    # =========================================================================

    @abstractmethod
    async def get_account(self) -> Account:
        """Return current exchange account information."""

    @abstractmethod
    async def get_ticker(
        self,
        *,
        symbol: str,
    ) -> Ticker:
        """Return the latest ticker for a trading symbol."""

    @abstractmethod
    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[Candle]:
        """Return candlestick market data."""

    @abstractmethod
    async def get_trades(
        self,
        *,
        symbol: str,
        limit: int,
    ) -> Sequence[Trade]:
        """Return executed trades for a symbol."""

    # =========================================================================
    # Orders
    # =========================================================================

    @abstractmethod
    async def create_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> Order:
        """Create an entry or standard exchange order."""

    @abstractmethod
    async def create_protection_orders(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> Sequence[Order]:
        """Create stop-loss and/or take-profit protection orders.

        Args:
            symbol: Trading pair symbol.
            side: Order side used to close or reduce the position.
            quantity: Quantity protected by the orders.
            stop_loss: Optional stop-loss trigger price.
            take_profit: Optional take-profit trigger price.

        Returns:
            Created protection orders.
        """

    @abstractmethod
    async def cancel_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Cancel an existing order."""

    @abstractmethod
    async def cancel_all_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Cancel all active orders, optionally filtered by symbol."""

    @abstractmethod
    async def get_order(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Return an order by its identifier."""

    @abstractmethod
    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open orders."""

    @abstractmethod
    async def get_open_protection_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return currently open conditional protection orders."""

    @abstractmethod
    async def ensure_stop_loss_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal,
    ) -> Order:
        """Ensure one matching stop-loss is active and remove older duplicates."""

    # =========================================================================
    # Positions
    # =========================================================================

    @abstractmethod
    async def get_positions(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Position]:
        """Return current trading positions."""

    @abstractmethod
    async def close_position(
        self,
        *,
        symbol: str,
    ) -> Order:
        """Close the active position for a trading symbol."""

    @abstractmethod
    async def close_all_positions(self) -> Sequence[Order]:
        """Close all active trading positions."""
