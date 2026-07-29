"""
Botragram

Description:
    Position engine for tracking active market positions.

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
from botragram.exchanges.base.mapper import PositionInfo

logger = logging.getLogger(__name__)


# =============================================================================
# Position Engine Class
# =============================================================================
class PositionEngine:
    """Engine responsible for maintaining open positions state."""

    def __init__(self) -> None:
        """Initialize PositionEngine."""
        self._positions: dict[str, PositionInfo] = {}

    def update_position(self, position: PositionInfo) -> None:
        """Add or update position in active tracker.

        Args:
            position: PositionInfo model instance.
        """
        if position.size == Decimal("0"):
            self._positions.pop(position.symbol, None)
            logger.info(f"Position closed for symbol: {position.symbol}")
        else:
            self._positions[position.symbol] = position
            logger.info(
                f"Position updated for {position.symbol}: "
                f"side={position.position_side.value}, size={position.size}"
            )

    def get_position(self, symbol: str) -> PositionInfo | None:
        """Get active position info for symbol.

        Args:
            symbol: Symbol string.

        Returns:
            PositionInfo if exists, else None.
        """
        return self._positions.get(symbol)

    def has_active_position(self, symbol: str) -> bool:
        """Check whether an active position exists for symbol.

        Args:
            symbol: Symbol string.

        Returns:
            True if position size > 0, False otherwise.
        """
        pos = self._positions.get(symbol)
        return pos is not None and pos.size > Decimal("0")

    def get_all_positions(self) -> list[PositionInfo]:
        """Get list of all active positions.

        Returns:
            List of PositionInfo instances.
        """
        return list(self._positions.values())
