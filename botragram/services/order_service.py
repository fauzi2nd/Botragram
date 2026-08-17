"""
Botragram

Description:
    Trading order application service.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine import OrderEngine
from botragram.enums import OrderStatus, OrderType
from botragram.models import Order, RiskResult, Signal
from botragram.repositories import OrderRepository

__all__ = [
    "OrderService",
]


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class OrderService:
    """Submit, query, cancel, and persist trading orders."""

    order_engine: OrderEngine
    order_repository: OrderRepository

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        """Submit and persist an approved trading order.

        Args:
            signal: Trading signal to execute.
            risk_result: Approved risk evaluation result.
            order_type: Entry order type.
            price: Optional explicit limit-order price.

        Returns:
            Created and persisted order.
        """
        order = await self.order_engine.submit(
            signal=signal,
            risk_result=risk_result,
            order_type=order_type,
            price=price,
            client_order_id=client_order_id,
        )

        await self.order_repository.save(
            order=order,
        )

        return order

    async def cancel(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Cancel and persist an exchange order.

        Args:
            symbol: Trading pair symbol.
            order_id: Exchange order identifier.

        Returns:
            Cancelled order snapshot.
        """
        order = await self.order_engine.cancel(
            symbol=self._normalize_symbol(symbol),
            order_id=self._normalize_order_id(order_id),
        )

        await self.order_repository.save(
            order=order,
        )

        return order

    async def get(
        self,
        *,
        symbol: str,
        order_id: str,
        persist: bool = True,
    ) -> Order:
        """Fetch an exchange order.

        Args:
            symbol: Trading pair symbol.
            order_id: Exchange order identifier.
            persist: Whether the fetched snapshot should be persisted.

        Returns:
            Current order snapshot.
        """
        order = await self.order_engine.get(
            symbol=self._normalize_symbol(symbol),
            order_id=self._normalize_order_id(order_id),
        )

        if persist:
            await self.order_repository.save(
                order=order,
            )

        return order

    async def get_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Fetch and persist an exchange order by its client identity."""
        order = await self.order_engine.get_by_client_order_id(
            symbol=self._normalize_symbol(symbol),
            client_order_id=self._normalize_client_order_id(client_order_id),
        )
        await self.order_repository.save(order=order)
        return order

    async def get_stored(
        self,
        *,
        order_id: str,
        symbol: str | None = None,
    ) -> Order | None:
        """Return a persisted order by identifier."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        return await self.order_repository.get_by_id(
            order_id=self._normalize_order_id(order_id),
            symbol=normalized_symbol,
        )

    async def get_latest(
        self,
        *,
        limit: int,
        symbol: str | None = None,
        status: OrderStatus | None = None,
    ) -> Sequence[Order]:
        """Return the latest persisted orders."""
        if limit <= 0:
            raise ValueError("Order limit must be greater than zero")

        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        return await self.order_repository.get_latest(
            limit=limit,
            symbol=normalized_symbol,
            status=status,
        )

    async def get_open_orders(
        self,
        *,
        symbol: str | None = None,
    ) -> Sequence[Order]:
        """Return persisted open orders."""
        normalized_symbol = (
            self._normalize_symbol(symbol) if symbol is not None else None
        )

        return await self.order_repository.get_open_orders(
            symbol=normalized_symbol,
        )

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol

    @staticmethod
    def _normalize_order_id(
        order_id: str,
    ) -> str:
        """Normalize and validate an order identifier."""
        normalized_order_id = order_id.strip()

        if not normalized_order_id:
            raise ValueError("Order identifier must not be empty")

        return normalized_order_id

    @staticmethod
    def _normalize_client_order_id(client_order_id: str) -> str:
        """Normalize and validate a client-assigned order identity."""
        normalized_client_order_id = client_order_id.strip()
        if not normalized_client_order_id:
            raise ValueError("Client order identifier must not be empty")
        return normalized_client_order_id
