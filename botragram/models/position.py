"""
Botragram

Description:
    Trading position model.

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
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import Interval, PositionSide, StrategyType

__all__ = [
    "Position",
]


# =============================================================================
# Domain Models
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class Position:
    """Immutable trading position."""

    symbol: str
    side: PositionSide

    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal

    unrealized_pnl: Decimal
    leverage: int

    opened_at: datetime
    updated_at: datetime

    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    interval: Interval | None = None
    strategy_type: StrategyType | None = None
    protection_step: int = 0
    stop_loss_client_algo_id: str | None = None
    take_profit_client_algo_id: str | None = None

    def __post_init__(self) -> None:
        """Reject a shared client identity across distinct protection legs."""
        if (
            self.stop_loss_client_algo_id is not None
            and self.stop_loss_client_algo_id == self.take_profit_client_algo_id
        ):
            raise ValueError("STOP and TP protection identities must be distinct")

    @staticmethod
    def create_stop_loss_client_algo_id() -> str:
        """Create a stable client identity for one stop-loss protection leg."""
        return f"bsl-{uuid4().hex}"

    @staticmethod
    def create_take_profit_client_algo_id() -> str:
        """Create a stable client identity for one take-profit protection leg."""
        return f"btp-{uuid4().hex}"
