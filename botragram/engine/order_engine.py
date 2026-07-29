"""
Botragram

Description:
    Order engine for managing order placement and execution lifecycle.

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
import logging
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.order_side import OrderSide
from botragram.enums.order_type import OrderType
from botragram.exchanges.base.client import BaseExchangeClient
from botragram.exchanges.base.mapper import OrderResult

logger = logging.getLogger(__name__)


# =============================================================================
# Order Engine Class
# =============================================================================
class OrderEngine:
    """Engine responsible for submitting and tracking order executions."""

    def __init__(self, exchange_client: BaseExchangeClient) -> None:
        """Initialize OrderEngine.

        Args:
            exchange_client: Active exchange client instance.
        """
        self._exchange = exchange_client
        self._active_orders: dict[str, OrderResult] = {}

    async def execute_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> OrderResult:
        """Execute an order via the exchange client.

        Args:
            symbol: Trading pair symbol.
            side: Order side enum (BUY/SELL).
            order_type: Order type enum (LIMIT/MARKET).
            quantity: Order size quantity.
            price: Optional limit order price.

        Returns:
            OrderResult instance.
        """
        logger.info(
            f"Executing {side.value} {order_type.value} order for {symbol}: "
            f"qty={quantity}, price={price}"
        )
        result = await self._exchange.create_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
        )
        self._active_orders[result.order_id] = result
        return result

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an active order.

        Args:
            symbol: Symbol string.
            order_id: Order ID string.

        Returns:
            True if cancelled, False otherwise.
        """
        success = await self._exchange.cancel_order(
            symbol=symbol, order_id=order_id
        )
        if success:
            self._active_orders.pop(order_id, None)
            logger.info(f"Order cancelled: id={order_id}, symbol={symbol}")
        return success

    def get_active_orders(self) -> list[OrderResult]:
        """Get list of currently active orders.

        Returns:
            List of OrderResult instances.
        """
        return list(self._active_orders.values())
