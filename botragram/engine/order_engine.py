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
from typing import Protocol

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import OrderSide, OrderType, SignalType
from botragram.exceptions import VenueRuleValidationError
from botragram.models import ExchangeSymbolRules, Order, RiskResult, Signal, Ticker

__all__ = [
    "OrderEngine",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")


class OrderExchangeClient(Protocol):
    """Provide the narrow exchange operations owned by the order engine."""

    async def get_ticker(self, *, symbol: str) -> Ticker:
        """Return a current typed market reference price."""
        ...

    async def get_market_entry_rules(self, *, symbol: str) -> ExchangeSymbolRules:
        """Return authoritative MARKET quantity rules."""
        ...

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
        """Create one order."""
        ...

    async def cancel_order(self, *, symbol: str, order_id: str) -> Order:
        """Cancel one order."""
        ...

    async def get_order(self, *, symbol: str, order_id: str) -> Order:
        """Return one order."""
        ...

    async def get_order_by_client_order_id(
        self, *, symbol: str, client_order_id: str
    ) -> Order:
        """Return one order by client identity."""
        ...


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

    exchange_client: OrderExchangeClient

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

    async def normalize_futures_market_quantity(
        self,
        *,
        symbol: str,
        quantity: Decimal,
    ) -> Decimal:
        """Normalize and validate a Futures MARKET quantity before mutation."""
        rules = await self.exchange_client.get_market_entry_rules(symbol=symbol)
        ticker = await self.exchange_client.get_ticker(symbol=symbol)
        normalized_quantity = self._round_down(
            quantity=quantity,
            step=rules.market_quantity_step,
        )
        self._validate_market_quantity(
            quantity=normalized_quantity,
            reference_price=ticker.last_price,
            symbol=symbol,
            minimum_quantity=rules.market_min_quantity,
            maximum_quantity=rules.market_max_quantity,
            step=rules.market_quantity_step,
            minimum_notional=rules.minimum_notional,
        )
        return normalized_quantity

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
    def _round_down(*, quantity: Decimal, step: Decimal) -> Decimal:
        """Round quantity downward to the exact exchange step grid."""
        if quantity <= _DECIMAL_ZERO:
            raise VenueRuleValidationError("Venue quantity must be greater than zero")
        if step <= _DECIMAL_ZERO:
            raise VenueRuleValidationError(
                "Venue quantity step must be greater than zero"
            )
        return (quantity // step) * step

    @staticmethod
    def _validate_market_quantity(
        *,
        quantity: Decimal,
        reference_price: Decimal,
        symbol: str,
        minimum_quantity: Decimal,
        maximum_quantity: Decimal,
        step: Decimal,
        minimum_notional: Decimal | None,
    ) -> None:
        """Reject an invalid venue quantity without clamping exposure upward."""
        if quantity <= _DECIMAL_ZERO:
            raise VenueRuleValidationError("Venue-normalized quantity is zero")
        if quantity < minimum_quantity:
            raise VenueRuleValidationError("Venue quantity is below the minimum")
        if quantity > maximum_quantity:
            raise VenueRuleValidationError("Venue quantity exceeds the maximum")
        if quantity % step != _DECIMAL_ZERO:
            raise VenueRuleValidationError("Venue quantity is not step-aligned")
        if reference_price <= _DECIMAL_ZERO:
            raise VenueRuleValidationError(
                "Venue reference price must be greater than zero"
            )
        if (
            minimum_notional is not None
            and quantity * reference_price < minimum_notional
        ):
            raise VenueRuleValidationError(
                f"Venue quantity for {symbol!r} is below the minimum notional"
            )

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
