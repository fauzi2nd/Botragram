"""Durable performance record for one closed Botragram position lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from botragram.enums import (
    ClosedPositionProvenance,
    ClosedPositionReason,
    PositionSide,
)

__all__ = ["ClosedPositionLifecycle", "PendingClosedPositionLifecycle"]


@dataclass(slots=True, kw_only=True, frozen=True)
class PendingClosedPositionLifecycle:
    """Retain exact Botragram ownership before financial enrichment completes."""

    entry_client_order_id: str
    symbol: str
    position_side: PositionSide
    entry_order_id: str
    exit_client_order_id: str
    exit_order_id: str
    close_reason: ClosedPositionReason
    provenance: ClosedPositionProvenance
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Reject incomplete lifecycle ownership or naive timestamps."""
        for label, value in (
            ("entry client order ID", self.entry_client_order_id),
            ("symbol", self.symbol),
            ("entry order ID", self.entry_order_id),
            ("exit client order ID", self.exit_client_order_id),
            ("exit order ID", self.exit_order_id),
        ):
            if not value.strip():
                raise ValueError(f"Closed lifecycle {label} must not be empty")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("Closed lifecycle recorded_at must be timezone-aware")


@dataclass(slots=True, kw_only=True, frozen=True)
class ClosedPositionLifecycle:
    """Represent exactly one financially completed Botragram position lifecycle."""

    ownership: PendingClosedPositionLifecycle
    gross_realized_pnl: Decimal
    fee: Decimal
    fee_asset: str
    net_pnl: Decimal
    closed_at: datetime

    def __post_init__(self) -> None:
        """Validate finite financial values and authoritative close time."""
        for label, value in (
            ("gross realized PnL", self.gross_realized_pnl),
            ("fee", self.fee),
            ("net PnL", self.net_pnl),
        ):
            if not value.is_finite():
                raise ValueError(f"Closed lifecycle {label} must be finite")
        if self.fee < Decimal("0"):
            raise ValueError("Closed lifecycle fee must not be negative")
        if not self.fee_asset.strip():
            raise ValueError("Closed lifecycle fee asset must not be empty")
        if self.net_pnl != self.gross_realized_pnl - self.fee:
            raise ValueError("Closed lifecycle net PnL must equal gross PnL minus fee")
        if self.closed_at.tzinfo is None or self.closed_at.utcoffset() is None:
            raise ValueError("Closed lifecycle closed_at must be timezone-aware")

    @property
    def entry_client_order_id(self) -> str:
        """Return the canonical Botragram lifecycle identity."""
        return self.ownership.entry_client_order_id
