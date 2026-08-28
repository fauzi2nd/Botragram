"""Immutable operator-exit intent, attempt, and observability models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from botragram.enums import (
    ExchangeEnvironment,
    ExecutionPolicy,
    OperatorExitAttemptStatus,
    OperatorExitStatus,
    OperatorExitType,
    PositionSide,
    TradeMode,
)
from botragram.models.position import Position

__all__ = [
    "OperatorExitAttempt",
    "OperatorExitConfirmation",
    "OperatorExitOperation",
    "OperatorExitSnapshot",
]


@dataclass(slots=True, kw_only=True, frozen=True)
class OperatorExitOperation:
    """Durable ownership of one confirmed operator portfolio action."""

    operation_id: str
    operation_type: OperatorExitType
    status: OperatorExitStatus
    requested_by: str
    created_at: datetime
    updated_at: datetime
    symbol: str | None = None
    target_execution_policy: ExecutionPolicy | None = None
    failure_reason: str | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class OperatorExitAttempt:
    """Durable identity for one reduce-only LIVE close mutation."""

    client_order_id: str
    operation_id: str
    symbol: str
    position_side: PositionSide
    quantity: Decimal
    status: OperatorExitAttemptStatus
    created_at: datetime
    updated_at: datetime
    exchange_order_id: str | None = None
    failure_reason: str | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class OperatorExitConfirmation:
    """Bounded process-local confirmation challenge with no fund mutation."""

    confirmation_id: str
    operation_type: OperatorExitType
    environment: str
    symbols: tuple[str, ...]
    required_token: str
    requires_typed_confirmation: bool
    expires_at: datetime
    target_execution_policy: ExecutionPolicy | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class OperatorExitSnapshot:
    """Truthful read-only operator-exit control-plane state."""

    status: OperatorExitStatus
    trade_mode: TradeMode
    exchange_environment: ExchangeEnvironment
    positions: tuple[Position, ...]
    closing_symbols: tuple[str, ...] = ()
    target_execution_policy: ExecutionPolicy | None = None
    failure_reason: str | None = None

