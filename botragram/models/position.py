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


_STOP_LOSS_CLIENT_ALGO_ID_PREFIX = "bsl-"
_TAKE_PROFIT_CLIENT_ALGO_ID_PREFIX = "btp-"
_CLIENT_ALGO_ID_HEX_LENGTH = 32
_LOWER_HEX_CHARACTERS = frozenset("0123456789abcdef")


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
    pending_stop_loss: Decimal | None = None
    pending_stop_loss_client_algo_id: str | None = None
    pending_protection_step: int = 0
    entry_client_order_id: str | None = None

    def __post_init__(self) -> None:
        """Validate distinct current and pending protection identities."""
        if (
            self.stop_loss_client_algo_id is not None
            and self.stop_loss_client_algo_id == self.take_profit_client_algo_id
        ):
            raise ValueError("STOP and TP protection identities must be distinct")

        pending_id = self.pending_stop_loss_client_algo_id
        has_pending = (
            self.pending_stop_loss is not None
            or pending_id is not None
            or self.pending_protection_step != 0
        )
        if not has_pending:
            return

        if self.pending_stop_loss is None or pending_id is None:
            raise ValueError(
                "Pending STOP replacement requires both trigger and client identity"
            )
        if self.pending_protection_step <= self.protection_step:
            raise ValueError(
                "Pending STOP replacement step must advance current protection"
            )
        if pending_id in {
            self.stop_loss_client_algo_id,
            self.take_profit_client_algo_id,
        }:
            raise ValueError(
                "Pending STOP replacement identity must be distinct from current legs"
            )

    @staticmethod
    def create_stop_loss_client_algo_id() -> str:
        """Create a stable client identity for one stop-loss protection leg."""
        return f"{_STOP_LOSS_CLIENT_ALGO_ID_PREFIX}{uuid4().hex}"

    @staticmethod
    def create_take_profit_client_algo_id() -> str:
        """Create a stable client identity for one take-profit protection leg."""
        return f"{_TAKE_PROFIT_CLIENT_ALGO_ID_PREFIX}{uuid4().hex}"

    @staticmethod
    def is_generated_stop_loss_client_algo_id(client_id: str | None) -> bool:
        """Return whether an identity has Botragram's generated STOP form."""
        if client_id is None or not client_id.startswith(
            _STOP_LOSS_CLIENT_ALGO_ID_PREFIX
        ):
            return False
        suffix = client_id.removeprefix(_STOP_LOSS_CLIENT_ALGO_ID_PREFIX)
        return len(suffix) == _CLIENT_ALGO_ID_HEX_LENGTH and all(
            character in _LOWER_HEX_CHARACTERS for character in suffix
        )
