"""
Botragram

Description:
    Profit and loss calculation engine.

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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import PositionSide
from botragram.models import Position

__all__ = [
    "PnLEngine",
]


# =============================================================================
# Numeric Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")
_DECIMAL_ONE = Decimal("1")
_DECIMAL_ONE_HUNDRED = Decimal("100")

# =============================================================================
# Error Messages
# =============================================================================
_ENTRY_PRICE_ERROR = "Entry price must be greater than zero"
_CURRENT_PRICE_ERROR = "Current or exit price must be greater than zero"
_QUANTITY_ERROR = "Position quantity must be greater than zero"
_LEVERAGE_ERROR = "Leverage must be greater than zero"


# =============================================================================
# PnL Engine
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PnLEngine:
    """Calculate realized and unrealized trading profit and loss."""

    def calculate_unrealized(
        self,
        *,
        position: Position,
        current_price: Decimal | None = None,
    ) -> Decimal:
        """Calculate unrealized PnL for an open position.

        Args:
            position: Open trading position.
            current_price: Optional current market price. When omitted,
                the current price stored in the position is used.

        Returns:
            Unrealized profit or loss.

        Raises:
            ValueError: If position values are invalid.
        """
        price = current_price if current_price is not None else position.current_price

        self._validate_position_values(
            entry_price=position.entry_price,
            current_price=price,
            quantity=position.quantity,
        )

        price_difference = self._calculate_price_difference(
            side=position.side,
            entry_price=position.entry_price,
            exit_price=price,
        )

        return price_difference * position.quantity

    def calculate_realized(
        self,
        *,
        side: PositionSide,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: Decimal,
        entry_fee: Decimal = _DECIMAL_ZERO,
        exit_fee: Decimal = _DECIMAL_ZERO,
    ) -> Decimal:
        """Calculate realized PnL after a position is closed.

        Args:
            side: Closed position direction.
            entry_price: Position entry price.
            exit_price: Position exit price.
            quantity: Closed position quantity.
            entry_fee: Fee paid when opening the position.
            exit_fee: Fee paid when closing the position.

        Returns:
            Realized profit or loss after fees.

        Raises:
            ValueError: If prices, quantity, or fees are invalid.
        """
        self._validate_position_values(
            entry_price=entry_price,
            current_price=exit_price,
            quantity=quantity,
        )

        if entry_fee < _DECIMAL_ZERO:
            raise ValueError("Entry fee must not be negative")

        if exit_fee < _DECIMAL_ZERO:
            raise ValueError("Exit fee must not be negative")

        gross_pnl = (
            self._calculate_price_difference(
                side=side,
                entry_price=entry_price,
                exit_price=exit_price,
            )
            * quantity
        )

        return gross_pnl - entry_fee - exit_fee

    def calculate_return_percentage(
        self,
        *,
        pnl: Decimal,
        entry_price: Decimal,
        quantity: Decimal,
    ) -> Decimal:
        """Calculate return relative to position notional.

        Args:
            pnl: Profit or loss amount.
            entry_price: Position entry price.
            quantity: Position quantity.

        Returns:
            Percentage return relative to entry notional.

        Raises:
            ValueError: If entry price or quantity is invalid.
        """
        if entry_price <= _DECIMAL_ZERO:
            raise ValueError(_ENTRY_PRICE_ERROR)

        if quantity <= _DECIMAL_ZERO:
            raise ValueError(_QUANTITY_ERROR)

        entry_notional = entry_price * quantity

        return pnl / entry_notional * _DECIMAL_ONE_HUNDRED

    def calculate_return_on_margin(
        self,
        *,
        pnl: Decimal,
        entry_price: Decimal,
        quantity: Decimal,
        leverage: int,
    ) -> Decimal:
        """Calculate return relative to initial margin.

        Args:
            pnl: Profit or loss amount.
            entry_price: Position entry price.
            quantity: Position quantity.
            leverage: Position leverage.

        Returns:
            Percentage return relative to initial margin.

        Raises:
            ValueError: If position values or leverage are invalid.
        """
        if leverage <= 0:
            raise ValueError(_LEVERAGE_ERROR)

        if entry_price <= _DECIMAL_ZERO:
            raise ValueError(_ENTRY_PRICE_ERROR)

        if quantity <= _DECIMAL_ZERO:
            raise ValueError("Position quantity must be greater than zero")

        initial_margin = entry_price * quantity / Decimal(leverage)

        return pnl / initial_margin * _DECIMAL_ONE_HUNDRED

    def calculate_total_unrealized(
        self,
        *,
        positions: Sequence[Position],
    ) -> Decimal:
        """Calculate total unrealized PnL across open positions.

        Args:
            positions: Open trading positions.

        Returns:
            Combined unrealized profit or loss.
        """
        return sum(
            (
                self.calculate_unrealized(
                    position=position,
                )
                for position in positions
            ),
            start=_DECIMAL_ZERO,
        )

    @staticmethod
    def _calculate_price_difference(
        *,
        side: PositionSide,
        entry_price: Decimal,
        exit_price: Decimal,
    ) -> Decimal:
        """Calculate side-aware price movement."""
        match side:
            case PositionSide.LONG:
                return exit_price - entry_price

            case PositionSide.SHORT:
                return entry_price - exit_price

            case _:
                raise ValueError(f"Unsupported position side: {side.value!r}")

    @staticmethod
    def _validate_position_values(
        *,
        entry_price: Decimal,
        current_price: Decimal,
        quantity: Decimal,
    ) -> None:
        """Validate values used by PnL calculations."""
        if entry_price <= _DECIMAL_ZERO:
            raise ValueError(_ENTRY_PRICE_ERROR)

        if current_price <= _DECIMAL_ZERO:
            raise ValueError(_CURRENT_PRICE_ERROR)

        if quantity <= _DECIMAL_ZERO:
            raise ValueError(_QUANTITY_ERROR)
