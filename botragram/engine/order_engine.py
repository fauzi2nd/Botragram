"""
Botragram

Description:
    Trading order execution engine.

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
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide, OrderType, SignalType
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Order, RiskResult, Signal

__all__ = [
    "OrderEngine",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Order Engine
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class OrderEngine:
    """Create and manage orders through an exchange client."""

    exchange_client: BaseExchangeClient

    async def submit(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        """Submit an approved trading signal as an exchange order.

        Args:
            signal: Trading signal to execute.
            risk_result: Approved risk evaluation result.
            order_type: Exchange order type.
            price: Optional limit-order price.

        Returns:
            Created exchange order.

        Raises:
            ValueError: If the signal or risk result cannot be executed.
        """
        self._validate_submission(
            signal=signal,
            risk_result=risk_result,
            order_type=order_type,
            price=price,
        )

        return await self.exchange_client.create_order(
            symbol=signal.symbol,
            side=self._resolve_order_side(signal.signal_type),
            order_type=order_type,
            quantity=risk_result.position.quantity,
            price=price,
            client_order_id=client_order_id,
        )

    async def cancel(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Cancel an active exchange order.

        Args:
            symbol: Trading pair symbol.
            order_id: Exchange order identifier.

        Returns:
            Cancelled exchange order.
        """
        return await self.exchange_client.cancel_order(
            symbol=symbol,
            order_id=order_id,
        )

    async def get(
        self,
        *,
        symbol: str,
        order_id: str,
    ) -> Order:
        """Return an exchange order by identifier.

        Args:
            symbol: Trading pair symbol.
            order_id: Exchange order identifier.

        Returns:
            Exchange order.
        """
        return await self.exchange_client.get_order(
            symbol=symbol,
            order_id=order_id,
        )

    async def get_by_client_order_id(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> Order:
        """Return an exchange order by its client-assigned identity."""
        return await self.exchange_client.get_order_by_client_order_id(
            symbol=symbol,
            client_order_id=client_order_id,
        )

    def _validate_submission(
        self,
        *,
        signal: Signal,
        risk_result: RiskResult,
        order_type: OrderType,
        price: Decimal | None,
    ) -> None:
        """Validate an order submission."""
        if not risk_result.approved:
            reason = risk_result.reason or "Risk evaluation rejected the signal"

            raise ValueError(f"Cannot submit rejected risk result: {reason}")

        if signal.signal_type is SignalType.HOLD:
            raise ValueError("Hold signals cannot create orders")

        if risk_result.position.quantity <= _DECIMAL_ZERO:
            raise ValueError("Order quantity must be greater than zero")

        if signal.price <= _DECIMAL_ZERO:
            raise ValueError("Signal price must be greater than zero")

        if order_type is OrderType.LIMIT and price is None:
            raise ValueError("Limit orders require an explicit price")

        if price is not None and price <= _DECIMAL_ZERO:
            raise ValueError("Order price must be greater than zero")

    @staticmethod
    def _resolve_order_side(
        signal_type: SignalType,
    ) -> OrderSide:
        """Convert a trading signal type into an order side."""
        match signal_type:
            case SignalType.BUY:
                return OrderSide.BUY

            case SignalType.SELL:
                return OrderSide.SELL

            case _:
                raise ValueError(
                    f"Unsupported signal type for order creation: {signal_type.value!r}"
                )
