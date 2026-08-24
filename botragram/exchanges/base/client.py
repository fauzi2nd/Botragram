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
from botragram.models import (
    Account,
    Candle,
    ExchangeSymbolRules,
    ExecutableQuote,
    MarketUniverseEntry,
    Order,
    Position,
    Ticker,
    Trade,
)

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

    async def get_executable_quote(
        self,
        *,
        symbol: str,
    ) -> ExecutableQuote:
        """Return an exchange-provided bid/ask reference for a MARKET entry.

        Clients whose ticker endpoint supplies a timestamped bid and ask may use
        this truthful default. Product-specific clients override it when their
        executable quote endpoint has distinct semantics.
        """
        ticker = await self.get_ticker(symbol=symbol)
        return ExecutableQuote(
            symbol=ticker.symbol,
            bid_price=ticker.bid_price,
            ask_price=ticker.ask_price,
            timestamp=ticker.timestamp,
        )

    async def get_mark_price(self, *, symbol: str) -> Decimal:
        """Return the current trigger reference price for a protection order.

        Spot clients have no distinct mark price, so their typed ticker price is
        the closest available reference.  Futures clients override this method
        with their authoritative MARK_PRICE endpoint.
        """
        return (await self.get_ticker(symbol=symbol)).last_price

    @abstractmethod
    async def get_market_entry_rules(
        self,
        *,
        symbol: str,
    ) -> ExchangeSymbolRules:
        """Return authoritative quantity rules for a MARKET entry."""

    @abstractmethod
    async def get_trading_symbols(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[str]:
        """Return active trading symbols for one quote asset."""

    async def get_market_universe(
        self,
        *,
        quote_asset: str,
    ) -> Sequence[MarketUniverseEntry]:
        """Return typed market-universe facts when the exchange supports them."""
        del quote_asset
        raise NotImplementedError("Market-universe discovery is not supported")

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
        symbol: str | None,
        limit: int,
    ) -> Sequence[Trade]:
        """Return bounded account fills for an optional exchange symbol."""

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
        client_order_id: str | None = None,
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
        stop_loss_client_algo_id: str | None = None,
        take_profit_client_algo_id: str | None = None,
    ) -> Sequence[Order]:
        """Create stop-loss and/or take-profit protection orders.

        Args:
            symbol: Trading pair symbol.
            side: Order side used to close or reduce the position.
            quantity: Quantity protected by the orders.
            stop_loss: Optional stop-loss trigger price.
            take_profit: Optional take-profit trigger price.
            stop_loss_client_algo_id: Stable client identity for a new stop leg.
            take_profit_client_algo_id: Stable client identity for a new TP leg.

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
    async def get_order_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Return an order by its vendor-neutral client identity."""

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
    async def get_protection_order_by_client_id(
        self, *, symbol: str, client_id: str
    ) -> Order:
        """Return one conditional protection order by client identity."""

    async def cancel_protection_order(
        self,
        *,
        symbol: str,
        client_id: str,
    ) -> None:
        """Cancel one conditional protection order by durable client identity.

        Futures connectors with a dedicated conditional-order endpoint override
        this boundary. Connectors that do not support conditional protection
        cancellation fail closed instead of routing to an unrelated order API.
        """
        del symbol, client_id
        raise NotImplementedError("Protection-order cancellation is not supported")

    @abstractmethod
    async def ensure_stop_loss_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        stop_loss: Decimal,
        client_algo_id: str | None = None,
        previous_client_algo_id: str | None = None,
    ) -> Order:
        """Ensure one durable stop replacement and retire its predecessor."""

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
        client_order_id: str | None = None,
    ) -> Order:
        """Close the active position with an optional durable client identity."""

    @abstractmethod
    async def close_all_positions(self) -> Sequence[Order]:
        """Close all active trading positions."""
