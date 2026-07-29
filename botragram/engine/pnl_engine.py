"""
Botragram

Description:
    PnL engine for calculating realized and unrealized profit/loss.

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
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums.position_side import PositionSide


# =============================================================================
# PnL Engine Class
# =============================================================================
class PnLEngine:
    """Engine responsible for calculating realized and unrealized PnL."""

    def calculate_unrealized_pnl(
        self,
        entry_price: Decimal,
        mark_price: Decimal,
        quantity: Decimal,
        side: PositionSide,
    ) -> Decimal:
        """Calculate Unrealized PnL for an open position.

        Args:
            entry_price: Position average entry price.
            mark_price: Current market mark price.
            quantity: Position size quantity.
            side: Position side (LONG/SHORT/BOTH).

        Returns:
            Calculated Unrealized PnL as Decimal.
        """
        if side == PositionSide.SHORT:
            return (entry_price - mark_price) * quantity
        return (mark_price - entry_price) * quantity

    def calculate_realized_pnl(
        self,
        entry_price: Decimal,
        exit_price: Decimal,
        quantity: Decimal,
        side: PositionSide,
        fee: Decimal = Decimal("0"),
    ) -> Decimal:
        """Calculate Realized PnL for a closed position.

        Args:
            entry_price: Position entry price.
            exit_price: Position exit price.
            quantity: Closed position quantity.
            side: Position side.
            fee: Total execution fees incurred.

        Returns:
            Calculated Realized PnL minus fees as Decimal.
        """
        if side == PositionSide.SHORT:
            gross_pnl = (entry_price - exit_price) * quantity
        else:
            gross_pnl = (exit_price - entry_price) * quantity

        return gross_pnl - fee
