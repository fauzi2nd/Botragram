"""Durable intent for one outbound LIVE entry mutation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from botragram.enums import (
    Interval,
    OrderSide,
    OrderType,
    StrategyType,
    SubmissionAttemptStatus,
)

__all__ = ["SubmissionAttempt"]


@dataclass(slots=True, kw_only=True, frozen=True)
class SubmissionAttempt:
    """Immutable pre-exchange intent retained for later reconciliation."""

    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    signal_generated_at: datetime
    interval: Interval
    strategy_type: StrategyType | None
    status: SubmissionAttemptStatus
    created_at: datetime
    updated_at: datetime
    exchange_order_id: str | None = None
