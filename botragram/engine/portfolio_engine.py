"""
Botragram

Description:
    Trading portfolio calculation engine.

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
    "PortfolioEngine",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")

_POSITION_QUANTITY_ERROR = "Position quantity must not be negative"
_POSITION_PRICE_ERROR = "Position current price must not be negative"


# =============================================================================
# Portfolio Engine
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class PortfolioEngine:
    """Calculate aggregate metrics for a collection of positions."""

    def calculate_total_notional(
        self,
        *,
        positions: Sequence[Position],
    ) -> Decimal:
        """Calculate total absolute position notional.

        Args:
            positions: Open trading positions.

        Returns:
            Sum of all position notional values.
        """
        self._validate_positions(
            positions=positions,
        )

        return sum(
            (position.quantity * position.current_price for position in positions),
            start=_DECIMAL_ZERO,
        )

    def calculate_long_exposure(
        self,
        *,
        positions: Sequence[Position],
    ) -> Decimal:
        """Calculate total long position exposure.

        Args:
            positions: Open trading positions.

        Returns:
            Combined notional value of long positions.
        """
        self._validate_positions(
            positions=positions,
        )

        return sum(
            (
                position.quantity * position.current_price
                for position in positions
                if position.side is PositionSide.LONG
            ),
            start=_DECIMAL_ZERO,
        )

    def calculate_short_exposure(
        self,
        *,
        positions: Sequence[Position],
    ) -> Decimal:
        """Calculate total short position exposure.

        Args:
            positions: Open trading positions.

        Returns:
            Combined absolute notional value of short positions.
        """
        self._validate_positions(
            positions=positions,
        )

        return sum(
            (
                position.quantity * position.current_price
                for position in positions
                if position.side is PositionSide.SHORT
            ),
            start=_DECIMAL_ZERO,
        )

    def calculate_net_exposure(
        self,
        *,
        positions: Sequence[Position],
    ) -> Decimal:
        """Calculate signed portfolio exposure.

        Positive values represent net-long exposure. Negative values
        represent net-short exposure.

        Args:
            positions: Open trading positions.

        Returns:
            Signed portfolio exposure.
        """
        long_exposure = self.calculate_long_exposure(
            positions=positions,
        )
        short_exposure = self.calculate_short_exposure(
            positions=positions,
        )

        return long_exposure - short_exposure

    def calculate_total_unrealized_pnl(
        self,
        *,
        positions: Sequence[Position],
    ) -> Decimal:
        """Calculate total unrealized PnL reported by positions.

        Args:
            positions: Open trading positions.

        Returns:
            Combined unrealized profit or loss.
        """
        self._validate_positions(
            positions=positions,
        )

        return sum(
            (position.unrealized_pnl for position in positions),
            start=_DECIMAL_ZERO,
        )

    def calculate_exposure_ratio(
        self,
        *,
        positions: Sequence[Position],
        account_equity: Decimal,
    ) -> Decimal:
        """Calculate total position exposure relative to account equity.

        Args:
            positions: Open trading positions.
            account_equity: Current account equity.

        Returns:
            Exposure ratio, where Decimal("1") represents 100%.

        Raises:
            ValueError: If account equity is not positive.
        """
        if account_equity <= _DECIMAL_ZERO:
            raise ValueError("Account equity must be greater than zero")

        total_notional = self.calculate_total_notional(
            positions=positions,
        )

        return total_notional / account_equity

    def count_open_positions(
        self,
        *,
        positions: Sequence[Position],
    ) -> int:
        """Count active non-zero positions.

        Args:
            positions: Trading positions.

        Returns:
            Number of positions with a positive quantity.
        """
        self._validate_positions(
            positions=positions,
        )

        return sum(1 for position in positions if position.quantity > _DECIMAL_ZERO)

    def has_position(
        self,
        *,
        positions: Sequence[Position],
        symbol: str,
    ) -> bool:
        """Return whether an active position exists for a symbol.

        Args:
            positions: Trading positions.
            symbol: Trading pair symbol.

        Returns:
            True when an active matching position exists.
        """
        normalized_symbol = self._normalize_symbol(symbol)

        self._validate_positions(
            positions=positions,
        )

        return any(
            position.symbol.upper() == normalized_symbol
            and position.quantity > _DECIMAL_ZERO
            for position in positions
        )

    @staticmethod
    def _validate_positions(
        *,
        positions: Sequence[Position],
    ) -> None:
        """Validate values used in portfolio calculations."""
        for position in positions:
            if position.quantity < _DECIMAL_ZERO:
                raise ValueError(_POSITION_QUANTITY_ERROR)

            if position.current_price < _DECIMAL_ZERO:
                raise ValueError(_POSITION_PRICE_ERROR)

    @staticmethod
    def _normalize_symbol(
        symbol: str,
    ) -> str:
        """Normalize and validate a trading symbol."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Trading symbol must not be empty")

        return normalized_symbol
